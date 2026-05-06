"""
Re-run stage-2 LLM matching for no_match titles using an expanded candidate pool.

Motivation:
  Stage-2 only saw the 5 NEL classifier candidates. Some no_match decisions
  may reflect a missing-from-top-5 problem rather than a true new_local. We
  test this by adding all ESCO occupations sitting in the sub-sector's mapped
  ISCO 4-digit group (only when the sub-sector has a 'map' decision).

Inputs:
  - outputs/stage2_results.csv          (per-title stage-2 output; we read no_match)
  - outputs/matches_minilm.csv          (original NEL top-5 per title)
  - outputs/subsector_isco_map.csv      (sub-sector -> ISCO 4-digit mapping)
  - shared_data/esco_taxonomy/occupations.csv
  - shared_data/esco_taxonomy/occupation_groups.csv

Output:
  - outputs/stage2_no_match_retry.csv   (one row per processed no_match title)

Methodology:
  - For each stage-2 no_match title with mapping_decision == 'map':
      pool = NEL top-5 + every ESCO occupation in the mapped ISCO 4-digit (no cap, no 3-digit fallback).
      Dedupe by URI. Tag source per candidate (stage-1 classifier vs sub-sector ISCO group).
      Send to LLM with neutral framing.
  - Skip titles whose sub-sector decision is 'no_map' (different problem).

Provider switching: same as 00_run_stage2.py - reads config.json llm.provider.

Usage:
    python scripts/01_no_match_retry_expanded_pool.py
    python scripts/01_no_match_retry_expanded_pool.py --workers 10
    python scripts/01_no_match_retry_expanded_pool.py --dry-run     # show first prompt
    python scripts/01_no_match_retry_expanded_pool.py --limit 5     # smoke test
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent.parent
ROOT_DIR = BASE_DIR.parent.parent
SHARED = ROOT_DIR / "shared_data" / "esco_taxonomy"

CONFIG_PATH = BASE_DIR / "config.json"
STAGE2_RESULTS = BASE_DIR / "outputs" / "stage2_results.csv"
MATCHES_CSV = BASE_DIR / "outputs" / "matches_minilm.csv"
SUBSECTOR_MAP = BASE_DIR / "outputs" / "subsector_isco_map.csv"
OUTPUT_CSV = BASE_DIR / "outputs" / "stage2_no_match_retry.csv"

sys.path.insert(0, str(Path(__file__).parent))
from llm_provider import make_provider  # noqa: E402

load_dotenv(ROOT_DIR / ".env")

OUTPUT_FIELDS = [
    "elmis_title",
    "amharic",
    "sector",
    "sub_sector",
    "professional_formal",
    "subsector_isco4",
    "candidate_pool_size",
    "n_from_nel",
    "n_from_isco_group",
    "stage1_best_score",
    "original_decision",       # always 'no_match' for this script
    "retry_decision",          # match | no_match | error
    "retry_selected_index",
    "retry_selected_label",
    "retry_selected_uri",
    "retry_selected_isco4",
    "retry_pick_source",       # nel | isco_group | (empty for no_match)
    "retry_confidence",
    "retry_rationale",
    "llm_provider",
    "llm_model",
    "raw_response",
]

SRC_NEL = "stage-1 classifier"
SRC_ISCO = "sub-sector ISCO group"


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_esco() -> tuple[dict, dict, dict]:
    """Return (uri_to_info, isco4_to_uris, isco4_labels)."""
    o = pd.read_csv(SHARED / "occupations.csv", low_memory=False)
    uri_info = {}
    isco4_to_uris: dict[str, list[str]] = {}
    for _, r in o.iterrows():
        uri = r["ORIGINURI"]
        isco4 = str(r["OCCUPATIONGROUPCODE"])
        uri_info[uri] = {
            "label": r["PREFERREDLABEL"],
            "isco4": isco4,
            "description": str(r.get("DESCRIPTION", "") or "")[:400],
        }
        isco4_to_uris.setdefault(isco4, []).append(uri)

    g = pd.read_csv(SHARED / "occupation_groups.csv")
    g4 = g[g["CODE"].astype(str).str.len() == 4]
    isco4_labels = dict(zip(g4["CODE"].astype(str), g4["PREFERREDLABEL"]))
    return uri_info, isco4_to_uris, isco4_labels


def load_subsector_map() -> dict:
    df = pd.read_csv(SUBSECTOR_MAP).fillna("")
    df["sector"] = df["sector"].astype(str).str.strip()
    df["sub_sector"] = df["sub_sector"].astype(str).str.strip()
    out = {}
    for _, r in df.iterrows():
        code = str(r["isco_code"]).strip() if r["isco_code"] else ""
        if code.endswith(".0"):
            code = code[:-2]
        out[(r["sector"], r["sub_sector"])] = {
            "decision": r["mapping_decision"],
            "isco_code": code,
        }
    return out


def select_candidates(match_row, isco4: str,
                      uri_info: dict, isco4_to_uris: dict) -> list[dict]:
    """Combine NEL top-5 + every ESCO occupation in the ISCO 4-digit group."""
    seen = set()
    out = []
    # NEL
    for k in range(1, 6):
        uri = match_row.get(f"m{k}_uri", "")
        label = match_row.get(f"m{k}_label", "")
        score = match_row.get(f"m{k}_score", "")
        if not uri or uri in seen:
            continue
        info = uri_info.get(uri, {})
        seen.add(uri)
        out.append({
            "source": SRC_NEL,
            "uri": uri,
            "label": label or info.get("label", ""),
            "isco4": info.get("isco4", ""),
            "description": info.get("description", ""),
            "similarity": str(score) if score != "" else None,
        })
    # ISCO group
    for uri in isco4_to_uris.get(isco4, []):
        if uri in seen:
            continue
        info = uri_info.get(uri, {})
        seen.add(uri)
        out.append({
            "source": SRC_ISCO,
            "uri": uri,
            "label": info.get("label", ""),
            "isco4": info.get("isco4", ""),
            "description": info.get("description", ""),
            "similarity": None,
        })
    return out


def build_prompt(row, candidates: list[dict], isco4_labels: dict) -> str:
    cand_lines = []
    for i, c in enumerate(candidates, 1):
        sim_str = f" | similarity {c['similarity']}" if c["similarity"] else ""
        group_label = isco4_labels.get(c["isco4"], "")
        cand_lines.append(
            f"{i}. [{c['source']}] {c['label']}  [ISCO {c['isco4']} {group_label}{sim_str}]\n"
            f"   {c['description']}"
        )
    cand_text = "\n".join(cand_lines)

    elmis_title = row.get("informal work in eng", "")
    amharic = row.get("Profession in Amharic", "")
    sector = row.get("sector", "")
    sub_sector = row.get("sub sector", "")
    pf = row.get("professional/ formal", "")

    return f"""You are matching an Ethiopia ELMIS occupational title to its best European ESCO equivalent.

ELMIS TITLE
- English title:     {elmis_title}
- Amharic title:     {amharic}
- Sector:            {sector}
- Sub-sector:        {sub_sector}
- Profession class:  {pf}    (P = professional, F = formal informal)

CANDIDATE ESCO OCCUPATIONS
The candidate list comes from two retrieval methods, neither of which is more authoritative than the other - judge each candidate on its own merits, not by source:
  - "[stage-1 classifier]" : top-5 from a semantic similarity classifier
  - "[sub-sector ISCO group]" : every ESCO occupation in the ISCO 4-digit group implied by the ELMIS sub-sector

{cand_text}

YOUR JOB
Pick the candidate that best describes the same work as the ELMIS title.

Guidelines:
- The ELMIS title may use Ethiopian or African phrasing; treat it as a plausible local variant of the ESCO occupation if the underlying work overlaps clearly.
- Use the sector and sub-sector to disambiguate when several candidates have similar labels but sit in different work domains.
- Pay attention to seniority cues in the ELMIS title (manager, technician, assistant, designer, engineer): the right ESCO match should be at the same seniority level, not just the same field.
- Prefer a less-than-perfect but domain-correct match over a label-similar match in the wrong domain.
- Do NOT favor candidates by source. Both sources can yield right or wrong matches.
- If no candidate describes the same work, choose "no_match" - the title will go to human review.

OUTPUT - return ONLY valid JSON, no prose:
{{
  "decision": "match" | "no_match",
  "selected_index": <integer 1..N> or null,
  "confidence": "high" | "medium" | "low",
  "rationale": "<one short sentence>"
}}

Rules:
- decision = "match" requires selected_index to be the rank (1..{len(candidates)}) of the chosen candidate.
- decision = "no_match" requires selected_index = null.
- confidence reflects how clearly the chosen candidate (or no_match decision) is the right answer."""


def normalise(raw, candidates: list[dict]) -> dict:
    base = {
        "retry_decision": "error",
        "retry_selected_index": "",
        "retry_selected_label": "",
        "retry_selected_uri": "",
        "retry_selected_isco4": "",
        "retry_pick_source": "",
        "retry_confidence": "low",
        "retry_rationale": "",
    }
    if not raw or not isinstance(raw, dict):
        base["retry_rationale"] = f"[error] LLM returned {type(raw).__name__ if raw else 'no'} parseable JSON"
        return base

    decision = (raw.get("decision") or "").strip().lower()
    confidence = (raw.get("confidence") or "").strip().lower()
    if confidence not in {"high", "medium", "low"}:
        confidence = "low"
    rationale = (raw.get("rationale") or "").strip()

    if decision == "no_match":
        return {
            **base,
            "retry_decision": "no_match",
            "retry_confidence": confidence,
            "retry_rationale": rationale,
        }
    if decision != "match":
        base["retry_rationale"] = f"[error] decision={raw.get('decision')!r}; rationale: {rationale}"
        return base

    idx = raw.get("selected_index")
    try:
        idx = int(idx)
    except (TypeError, ValueError):
        idx = None
    if not idx or idx < 1 or idx > len(candidates):
        base["retry_rationale"] = f"[error] selected_index {idx!r} out of range; rationale: {rationale}"
        base["retry_selected_index"] = str(idx) if idx is not None else ""
        return base

    chosen = candidates[idx - 1]
    pick_src = "nel" if chosen["source"] == SRC_NEL else "isco_group"
    return {
        "retry_decision": "match",
        "retry_selected_index": str(idx),
        "retry_selected_label": chosen["label"],
        "retry_selected_uri": chosen["uri"],
        "retry_selected_isco4": chosen["isco4"],
        "retry_pick_source": pick_src,
        "retry_confidence": confidence,
        "retry_rationale": rationale,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["gemini", "deepseek"], default=None)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    llm_cfg = dict(cfg.get("llm") or {})
    if args.provider:
        llm_cfg["provider"] = args.provider

    print("=" * 70)
    print("STAGE-2 NO_MATCH RETRY  (expanded candidate pool: NEL + sub-sector ISCO)")
    print("=" * 70)

    print("Loading inputs...")
    stage2 = pd.read_csv(STAGE2_RESULTS).fillna("")
    matches = pd.read_csv(MATCHES_CSV).fillna("")
    matches_idx = matches.set_index("informal work in eng", drop=False)
    sub_map = load_subsector_map()
    uri_info, isco4_to_uris, isco4_labels = load_esco()

    no_match = stage2[stage2["stage2_decision"] == "no_match"].copy()
    no_match["sector"] = no_match["sector"].astype(str).str.strip()
    no_match["sub_sector"] = no_match["sub_sector"].astype(str).str.strip()

    # Filter to mapped sub-sectors
    def has_map(r) -> bool:
        info = sub_map.get((r["sector"], r["sub_sector"]))
        return bool(info is not None and info["decision"] == "map" and info["isco_code"])

    mask = no_match.apply(has_map, axis=1).astype(bool)
    in_scope = no_match[mask].reset_index(drop=True)
    print(f"  Stage-2 no_match total:                 {len(no_match)}")
    print(f"  In scope (sub-sector mapping == 'map'): {len(in_scope)}")
    if args.limit:
        in_scope = in_scope.head(args.limit)
        print(f"  Limited to:                             {len(in_scope)}")

    if args.dry_run:
        if len(in_scope) == 0:
            print("Nothing to send.")
            return
        r = in_scope.iloc[0]
        match_row = matches_idx.loc[r["elmis_title"]]
        if isinstance(match_row, pd.DataFrame):
            match_row = match_row.iloc[0]
        info = sub_map[(r["sector"], r["sub_sector"])]
        cands = select_candidates(match_row, info["isco_code"], uri_info, isco4_to_uris)
        prompt = build_prompt(match_row, cands, isco4_labels)
        print(f"\nFirst row: {r['elmis_title']!r}")
        print(f"  ISCO 4-digit: {info['isco_code']}")
        print(f"  Pool size:    {len(cands)}  (NEL: {sum(1 for c in cands if c['source']==SRC_NEL)}, ISCO: {sum(1 for c in cands if c['source']==SRC_ISCO)})")
        print(f"\n--- PROMPT ---")
        print(prompt)
        return

    provider = make_provider(llm_cfg)
    model_name = getattr(provider, "model_name", "")
    print(f"  Provider:                               {provider.name} / {model_name}")
    print(f"  Workers:                                {args.workers}")

    write_header = not OUTPUT_CSV.exists()
    f = open(OUTPUT_CSV, "w" if write_header else "a", encoding="utf-8-sig", newline="")
    w = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS, quoting=csv.QUOTE_ALL)
    if write_header:
        w.writeheader()
        f.flush()

    def process_one(args_tuple):
        i_local, r = args_tuple
        title = r["elmis_title"]
        match_row = matches_idx.loc[title]
        if isinstance(match_row, pd.DataFrame):
            match_row = match_row.iloc[0]
        info = sub_map[(r["sector"], r["sub_sector"])]
        isco4 = info["isco_code"]
        cands = select_candidates(match_row, isco4, uri_info, isco4_to_uris)
        n_nel = sum(1 for c in cands if c["source"] == SRC_NEL)
        n_isco = sum(1 for c in cands if c["source"] == SRC_ISCO)

        prompt = build_prompt(match_row, cands, isco4_labels)
        raw = provider.generate_json(prompt)
        norm = normalise(raw, cands)

        out = {
            "elmis_title": title,
            "amharic": r["amharic"],
            "sector": r["sector"],
            "sub_sector": r["sub_sector"],
            "professional_formal": r["professional_formal"],
            "subsector_isco4": isco4,
            "candidate_pool_size": len(cands),
            "n_from_nel": n_nel,
            "n_from_isco_group": n_isco,
            "stage1_best_score": r["stage1_best_score"],
            "original_decision": r["stage2_decision"],
            "llm_provider": provider.name,
            "llm_model": model_name,
            "raw_response": json.dumps(raw, ensure_ascii=False) if raw else "",
            **norm,
        }
        return i_local, out

    counts = {"match": 0, "no_match": 0, "error": 0}
    pick_src_counts = {"nel": 0, "isco_group": 0}

    inputs = [(i, r) for i, r in in_scope.iterrows()]
    workers = max(1, args.workers)
    try:
        if workers == 1:
            iterator = (process_one(x) for x in inputs)
        else:
            executor = ThreadPoolExecutor(max_workers=workers)
            iterator = executor.map(process_one, inputs)

        for i_local, out in iterator:
            w.writerow(out)
            f.flush()
            counts[out["retry_decision"]] = counts.get(out["retry_decision"], 0) + 1
            if out["retry_pick_source"]:
                pick_src_counts[out["retry_pick_source"]] = pick_src_counts.get(out["retry_pick_source"], 0) + 1
            tag = out["retry_decision"]
            sel = out["retry_selected_index"] or "-"
            src = out["retry_pick_source"] or "-"
            conf = out["retry_confidence"]
            elmis = (out["elmis_title"][:42] + "...") if len(out["elmis_title"]) > 45 else out["elmis_title"]
            print(f"  [{i_local+1:3d}/{len(in_scope)}] {elmis:48s} -> {tag:9s} sel={sel:>3s} src={src:10s} conf={conf}")

        if workers > 1:
            executor.shutdown(wait=True)
    finally:
        f.close()

    print("\n" + "=" * 70)
    print("DONE")
    print(f"  match:    {counts['match']}    (flips from no_match -> match)")
    print(f"  no_match: {counts['no_match']}  (still no_match)")
    print(f"  errors:   {counts['error']}")
    print(f"  flip rate: {100*counts['match']/max(1,len(in_scope)):.1f}% of {len(in_scope)} retried")
    print()
    print(f"  Of the flips, picked from:")
    print(f"    NEL pool (was already an option):       {pick_src_counts['nel']}")
    print(f"    sub-sector ISCO group (NEW candidate):  {pick_src_counts['isco_group']}")
    print(f"\n  output: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
