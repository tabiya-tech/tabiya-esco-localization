"""
Stage-2 LLM matching for Ethiopia ELMIS.

Methodology recap (see countries/ethiopia/docs/SESSION_CONTEXT.md):
  Stage 1 - NEL classifier produces top-5 ESCO candidates per ELMIS title
            (already done; output at outputs/matches_minilm.csv).
  Stage 2 - For titles whose stage-1 best-similarity is BELOW the auto-pass
            threshold (default 0.85), present the top-5 candidates to an LLM
            and ask it to pick the best one or say no_match.
  Stage 3 - Human review for stage-2 no_match + low-confidence picks.
  Stage 4 - New-local promotion for unmatched titles.

This script implements Stage 2.

Provider switch:
  The LLM provider is read from config.json's `llm` block. ELMIS can switch
  between Gemini and DeepSeek by editing one field:
      "llm": { "provider": "gemini" }     # or "deepseek"
  Override at the CLI with --provider gemini|deepseek.

Inputs:
  - countries/ethiopia/outputs/matches_minilm.csv      (stage-1 NEL results)
  - countries/ethiopia/config.json                     (thresholds, llm config)
  - shared_data/esco_taxonomy/occupations.csv          (ESCO descriptions)
  - shared_data/esco_taxonomy/occupation_groups.csv    (ISCO group labels)

Outputs:
  - countries/ethiopia/outputs/stage2_results.csv      (one row per stage-2 input)
  - countries/ethiopia/outputs/stage2_results.csv.checkpoint.json  (resume state)

Usage:
    python scripts/00_run_stage2.py
    python scripts/00_run_stage2.py --provider deepseek
    python scripts/00_run_stage2.py --limit 50         # smoke-test
    python scripts/00_run_stage2.py --threshold 0.80   # override pass threshold
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent.parent
ROOT_DIR = BASE_DIR.parent.parent
SHARED = ROOT_DIR / "shared_data" / "esco_taxonomy"
INPUT_CSV = BASE_DIR / "outputs" / "matches_minilm.csv"
CONFIG_PATH = BASE_DIR / "config.json"
OUTPUT_CSV = BASE_DIR / "outputs" / "stage2_results.csv"
CHECKPOINT = OUTPUT_CSV.with_suffix(".csv.checkpoint.json")

sys.path.insert(0, str(Path(__file__).parent))
from llm_provider import make_provider  # noqa: E402

load_dotenv(ROOT_DIR / ".env")

OUTPUT_FIELDS = [
    "elmis_title",
    "amharic",
    "sector",
    "sub_sector",
    "professional_formal",
    "stage1_best_score",
    "stage1_best_label",
    "stage1_best_uri",
    "stage2_decision",        # match | no_match | error
    "stage2_selected_index",  # 1..5 or empty
    "stage2_selected_label",
    "stage2_selected_uri",
    "stage2_selected_isco4",
    "stage2_confidence",      # high | medium | low
    "stage2_rationale",
    "llm_provider",
    "llm_model",
    "raw_response",
]


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise SystemExit(f"Missing {CONFIG_PATH}")
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_esco_lookups() -> tuple[dict, dict]:
    """Return (uri -> {label, isco4, description}, isco4 -> group_label)."""
    o = pd.read_csv(SHARED / "occupations.csv", low_memory=False)
    uri_lookup = {}
    for _, r in o.iterrows():
        desc = str(r.get("DESCRIPTION", "") or "")[:400]
        uri_lookup[r["ORIGINURI"]] = {
            "label": r["PREFERREDLABEL"],
            "isco4": str(r["OCCUPATIONGROUPCODE"]),
            "description": desc,
        }
    g = pd.read_csv(SHARED / "occupation_groups.csv")
    g4 = g[g["CODE"].astype(str).str.len() == 4]
    isco4_labels = dict(zip(g4["CODE"].astype(str), g4["PREFERREDLABEL"]))
    return uri_lookup, isco4_labels


def select_stage2_input(matches: pd.DataFrame, threshold: float) -> pd.DataFrame:
    """Rows where stage-1 best score is below the auto-pass threshold."""
    matches = matches.copy()
    matches["best_score"] = pd.to_numeric(matches["best_score"], errors="coerce").fillna(0.0)
    return matches[matches["best_score"] < threshold].reset_index(drop=True)


def build_prompt(row, uri_lookup: dict, isco4_labels: dict) -> tuple[str, list[dict]]:
    """Return (prompt, candidate_list_for_lookup)."""
    candidates = []
    for k in range(1, 6):
        label = row.get(f"m{k}_label", "")
        uri = row.get(f"m{k}_uri", "")
        score = row.get(f"m{k}_score", "")
        if not uri or not label:
            continue
        info = uri_lookup.get(uri, {})
        isco4 = info.get("isco4", "")
        group_label = isco4_labels.get(isco4, "")
        candidates.append({
            "rank": k,
            "label": label,
            "uri": uri,
            "score": score,
            "isco4": isco4,
            "group_label": group_label,
            "description": info.get("description", ""),
        })

    cand_lines = []
    for c in candidates:
        cand_lines.append(
            f"{c['rank']}. {c['label']}  "
            f"[similarity {c['score']} | ISCO {c['isco4']} {c['group_label']}]\n"
            f"   {c['description']}"
        )
    cand_text = "\n".join(cand_lines)

    elmis_title = row.get("informal work in eng", "")
    amharic = row.get("Profession in Amharic", "")
    sector = row.get("sector", "")
    sub_sector = row.get("sub sector", "")
    pf = row.get("professional/ formal", "")

    prompt = f"""You are matching an Ethiopia ELMIS occupational title to its best European ESCO equivalent.

ELMIS TITLE
- English title:     {elmis_title}
- Amharic title:     {amharic}
- Sector:            {sector}
- Sub-sector:        {sub_sector}
- Profession class:  {pf}    (P = professional, F = formal informal)

CANDIDATE ESCO OCCUPATIONS (ranked by stage-1 semantic similarity classifier):
{cand_text}

YOUR JOB
Pick the candidate that best describes the same work as the ELMIS title.

Guidelines:
- The ELMIS title may use Ethiopian or African phrasing; treat it as a plausible local variant of the ESCO occupation if the underlying work overlaps clearly.
- Use the sector and sub-sector to disambiguate when several candidates have similar labels but sit in different work domains.
- Pay attention to seniority cues in the ELMIS title (manager, technician, assistant, designer, engineer): the right ESCO match should be at the same seniority level, not just the same field.
- Prefer a less-than-perfect but domain-correct match over a label-similar match in the wrong domain.
- If no candidate describes the same work, choose "no_match" - the title will go to human review.

OUTPUT - return ONLY valid JSON, no prose:
{{
  "decision": "match" | "no_match",
  "selected_index": <integer 1..5> or null,
  "confidence": "high" | "medium" | "low",
  "rationale": "<one short sentence>"
}}

Rules:
- decision = "match" requires selected_index to be the rank (1..5) of the chosen candidate.
- decision = "no_match" requires selected_index = null.
- confidence reflects how clearly the chosen candidate (or no_match decision) is the right answer."""

    return prompt, candidates


def normalise(raw, candidates: list[dict]) -> dict:
    """Coerce LLM output into our schema. Returns dict with stage2_* keys."""
    if not raw:
        return {
            "stage2_decision": "error",
            "stage2_selected_index": "",
            "stage2_selected_label": "",
            "stage2_selected_uri": "",
            "stage2_selected_isco4": "",
            "stage2_confidence": "low",
            "stage2_rationale": "[error] LLM returned no parseable JSON",
        }
    if not isinstance(raw, dict):
        return {
            "stage2_decision": "error",
            "stage2_selected_index": "",
            "stage2_selected_label": "",
            "stage2_selected_uri": "",
            "stage2_selected_isco4": "",
            "stage2_confidence": "low",
            "stage2_rationale": f"[error] LLM returned {type(raw).__name__}, expected JSON object",
        }

    decision = (raw.get("decision") or "").strip().lower()
    confidence = (raw.get("confidence") or "").strip().lower()
    if confidence not in {"high", "medium", "low"}:
        confidence = "low"
    rationale = (raw.get("rationale") or "").strip()

    if decision not in {"match", "no_match"}:
        decision = "error"

    if decision == "match":
        idx = raw.get("selected_index")
        try:
            idx = int(idx)
        except (TypeError, ValueError):
            idx = None
        chosen = next((c for c in candidates if c["rank"] == idx), None)
        if not chosen:
            return {
                "stage2_decision": "error",
                "stage2_selected_index": str(idx) if idx is not None else "",
                "stage2_selected_label": "",
                "stage2_selected_uri": "",
                "stage2_selected_isco4": "",
                "stage2_confidence": "low",
                "stage2_rationale": f"[error] selected_index {idx!r} not in 1..{len(candidates)}; rationale: {rationale}",
            }
        return {
            "stage2_decision": "match",
            "stage2_selected_index": str(idx),
            "stage2_selected_label": chosen["label"],
            "stage2_selected_uri": chosen["uri"],
            "stage2_selected_isco4": chosen["isco4"],
            "stage2_confidence": confidence,
            "stage2_rationale": rationale,
        }

    if decision == "no_match":
        return {
            "stage2_decision": "no_match",
            "stage2_selected_index": "",
            "stage2_selected_label": "",
            "stage2_selected_uri": "",
            "stage2_selected_isco4": "",
            "stage2_confidence": confidence,
            "stage2_rationale": rationale,
        }

    return {
        "stage2_decision": "error",
        "stage2_selected_index": "",
        "stage2_selected_label": "",
        "stage2_selected_uri": "",
        "stage2_selected_isco4": "",
        "stage2_confidence": "low",
        "stage2_rationale": f"[error] decision={raw.get('decision')!r}; rationale: {rationale}",
    }


def load_existing(out_path: Path) -> int:
    """Return number of rows already present (for resume)."""
    if not out_path.exists():
        return 0
    df = pd.read_csv(out_path)
    return len(df)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["gemini", "deepseek"], default=None,
                    help="Override config.json llm.provider")
    ap.add_argument("--threshold", type=float, default=None,
                    help="Stage-1 score below which titles are sent to stage-2 (default: config.json stage2.auto_pass_threshold or 0.85)")
    ap.add_argument("--limit", type=int, default=None, help="Process at most N rows (smoke test)")
    ap.add_argument("--workers", type=int, default=1, help="Concurrent LLM calls (default 1; try 10 on paid Gemini tier)")
    ap.add_argument("--dry-run", action="store_true", help="Print first prompt and exit")
    args = ap.parse_args()

    cfg = load_config()
    llm_cfg = dict(cfg.get("llm") or {})
    if args.provider:
        llm_cfg["provider"] = args.provider
    if not llm_cfg.get("provider"):
        sys.exit("config.json llm.provider not set and --provider not given")

    threshold = args.threshold
    if threshold is None:
        threshold = float(((cfg.get("stage2") or {}).get("auto_pass_threshold")) or 0.85)

    print("=" * 70)
    print("ETHIOPIA STAGE-2 LLM MATCHING")
    print("=" * 70)
    print(f"  Provider:           {llm_cfg.get('provider')}")
    print(f"  Auto-pass at:       stage1_best_score >= {threshold}")

    matches = pd.read_csv(INPUT_CSV).fillna("")
    stage2_input = select_stage2_input(matches, threshold)
    print(f"  Stage-1 rows total: {len(matches)}")
    print(f"  Going to stage-2:   {len(stage2_input)}")

    uri_lookup, isco4_labels = load_esco_lookups()
    print(f"  ESCO occupations:   {len(uri_lookup)}")

    if args.dry_run:
        if len(stage2_input) == 0:
            print("\nNo rows under threshold to send.")
            return
        prompt, _ = build_prompt(stage2_input.iloc[0], uri_lookup, isco4_labels)
        print("\n--- SAMPLE PROMPT (first stage-2 row) ---")
        print(prompt)
        return

    provider = make_provider(llm_cfg)
    model_name = getattr(provider, "model_name", "")
    print(f"  LLM model:          {model_name}")

    # Resume support
    already_done = load_existing(OUTPUT_CSV)
    if already_done:
        print(f"  Resuming - {already_done} rows already in {OUTPUT_CSV.name}")

    pending = stage2_input.iloc[already_done:].reset_index(drop=True)
    if args.limit:
        pending = pending.head(args.limit)
    print(f"  Processing this run: {len(pending)}")
    if not len(pending):
        print("Nothing to do.")
        return

    write_header = not OUTPUT_CSV.exists()
    f = open(OUTPUT_CSV, "a", encoding="utf-8-sig", newline="")
    w = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS, quoting=csv.QUOTE_ALL)
    if write_header:
        w.writeheader()
        f.flush()

    counts = {"match": 0, "no_match": 0, "error": 0}

    def process_one(args_tuple):
        i_local, row = args_tuple
        prompt, candidates = build_prompt(row, uri_lookup, isco4_labels)
        raw = provider.generate_json(prompt)
        normalised = normalise(raw, candidates)
        out = {
            "elmis_title": row.get("informal work in eng", ""),
            "amharic": row.get("Profession in Amharic", ""),
            "sector": row.get("sector", ""),
            "sub_sector": row.get("sub sector", ""),
            "professional_formal": row.get("professional/ formal", ""),
            "stage1_best_score": row.get("best_score", ""),
            "stage1_best_label": row.get("m1_label", ""),
            "stage1_best_uri": row.get("m1_uri", ""),
            "llm_provider": provider.name,
            "llm_model": model_name,
            "raw_response": json.dumps(raw, ensure_ascii=False) if raw else "",
            **normalised,
        }
        return i_local, out

    workers = max(1, args.workers)
    print(f"  Workers:            {workers}")

    try:
        inputs = [(i, row) for i, row in pending.iterrows()]
        if workers == 1:
            iterator = (process_one(x) for x in inputs)
        else:
            executor = ThreadPoolExecutor(max_workers=workers)
            iterator = executor.map(process_one, inputs)

        for i_local, out in iterator:
            w.writerow(out)
            f.flush()
            counts[out["stage2_decision"]] = counts.get(out["stage2_decision"], 0) + 1
            tag = out["stage2_decision"]
            sel = out["stage2_selected_index"] or "-"
            conf = out["stage2_confidence"]
            elmis_print = (out["elmis_title"][:42] + "...") if len(out["elmis_title"]) > 45 else out["elmis_title"]
            print(f"  [{i_local+1+already_done:5d}/{len(stage2_input)}] {elmis_print:48s} -> {tag:9s} sel={sel:>2s} conf={conf}")

        if workers > 1:
            executor.shutdown(wait=True)
    finally:
        f.close()

    print("\n" + "=" * 70)
    print("DONE")
    print(f"  match:    {counts['match']}")
    print(f"  no_match: {counts['no_match']}")
    print(f"  errors:   {counts['error']}")
    print(f"  output:   {OUTPUT_CSV}")
    if counts["error"] > 0:
        print(f"\n  Re-run to retry only the error rows? (Not auto - inspect them first.)")


if __name__ == "__main__":
    main()
