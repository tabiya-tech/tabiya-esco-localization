"""
Match a list of job titles against a Tabiya/ESCO taxonomy via the NEL v2 service
and write per-title top-K matches to CSV. Does NOT download or enrich the
full taxonomy — purely a matching probe.

The currently-configured NEL model on the classifier service is what gets used
(set via https://app.dev.classifier.tabiya.tech/configuration). Pass --label so
the model used is recorded in the output filename and as a column.

Usage:
    python match_titles_topk.py \
        --input output_with_sectors.csv \
        --label minilm \
        --nel-url https://dev.classifier.tabiya.tech \
        --nel-api-key $NEL_API_KEY

Output: matches_<label>.csv  (one row per input title, top-5 matches as wide cols)
"""

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

import requests

# ── Confidence thresholds (same as build_ethiopian_taxonomy.py) ───────────────
EXACT_THRESHOLD = 0.95
HIGH_CONF_THRESHOLD = 0.85
MIN_SIMILARITY = 0.50

# ── NEL config ────────────────────────────────────────────────────────────────
NEL_BATCH_SIZE = 100
TOP_K = 5
_MAX_RETRIES = 6
_RETRY_BASE_DELAY = 10.0

TITLE_COLUMN = "informal work in eng"
AMHARIC_COLUMN = "Profession in Amharic"


def confidence_level(score: float) -> str:
    if score >= EXACT_THRESHOLD:
        return "exact"
    if score >= HIGH_CONF_THRESHOLD:
        return "high_confidence"
    return "low_similarity"


def nel_link_batch(session, nel_url, titles, nel_api_key):
    payload = {
        "entities": [{"text": t, "entity_type": "occupation"} for t in titles],
        "top_k": TOP_K,
        "min_similarity": MIN_SIMILARITY,
    }
    headers = {"X-API-Key": nel_api_key} if nel_api_key else {}
    delay = _RETRY_BASE_DELAY
    for attempt in range(1, _MAX_RETRIES + 1):
        resp = session.post(nel_url, json=payload, headers=headers, timeout=120)
        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt == _MAX_RETRIES:
                resp.raise_for_status()
            print(f"\n  [{resp.status_code}] retry in {delay:.0f}s ({attempt}/{_MAX_RETRIES})...", end="", flush=True)
            time.sleep(delay)
            delay *= 2
            continue
        resp.raise_for_status()
        return resp.json()["linked_entities"]
    raise RuntimeError("NEL batch failed after retries")


def load_checkpoint(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"results": [], "next_index": 0}


def save_checkpoint(path, results, next_index):
    """Atomic-ish write with retries: Dropbox/AV on Windows occasionally locks
    files during rename, so we retry a few times before falling back to a
    direct in-place write."""
    tmp = path + ".tmp"
    payload = json.dumps({"results": results, "next_index": next_index})
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(payload)
    for delay in (0.1, 0.3, 0.7, 1.5, 3.0):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(delay)
    # Last resort: write directly (non-atomic). The .jsonl is the real backup.
    try:
        os.remove(tmp)
    except OSError:
        pass
    with open(path, "w", encoding="utf-8") as f:
        f.write(payload)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--label", required=True, help="Short tag for the NEL model in use, e.g. minilm or gemini")
    ap.add_argument("--output", default=None, help="Output CSV path (default: matches_<label>.csv)")
    ap.add_argument("--nel-url", default="https://dev.classifier.tabiya.tech")
    ap.add_argument("--nel-api-key", default=os.environ.get("NEL_API_KEY", ""))
    args = ap.parse_args()

    nel_endpoint = args.nel_url.rstrip("/") + "/v2/nel"
    out_path = Path(args.output) if args.output else Path(f"matches_{args.label}.csv")
    checkpoint_path = str(out_path) + ".checkpoint.json"
    raw_jsonl_path = out_path.with_suffix(".jsonl")  # full payload per title, just in case

    # ── Health check ──────────────────────────────────────────────────────────
    base = args.nel_url.rstrip("/")
    print(f"NEL service:   {base}")
    h = requests.get(f"{base}/v2/nel/health", timeout=15)
    h.raise_for_status()
    print(f"  health: {h.json()}")

    # ── Input ─────────────────────────────────────────────────────────────────
    with open(args.input, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        sys.exit("Input CSV is empty.")
    if TITLE_COLUMN not in rows[0]:
        sys.exit(f"Expected column {TITLE_COLUMN!r} not in input. Found: {list(rows[0].keys())}")
    print(f"Input:         {args.input}  ({len(rows)} rows)")
    print(f"Output:        {out_path}")
    print(f"Raw payloads:  {raw_jsonl_path}")
    print(f"Top-K:         {TOP_K}  | min_similarity: {MIN_SIMILARITY}")

    # ── NEL loop with checkpointing ───────────────────────────────────────────
    cp = load_checkpoint(checkpoint_path)
    results = cp["results"]
    start = cp["next_index"]
    if start > 0:
        print(f"  Resuming from row {start}/{len(rows)}")

    session = requests.Session()
    raw_f = open(raw_jsonl_path, "a", encoding="utf-8")  # append so resume keeps prior

    try:
        for batch_start in range(start, len(rows), NEL_BATCH_SIZE):
            batch = rows[batch_start : batch_start + NEL_BATCH_SIZE]
            titles = [r[TITLE_COLUMN].strip() for r in batch]
            try:
                linked = nel_link_batch(session, nel_endpoint, titles, args.nel_api_key)
            except requests.RequestException as e:
                print(f"\n[ERROR] {e}\n  Re-run the same command to resume from row {batch_start}.", file=sys.stderr)
                sys.exit(1)

            for r, entity in zip(batch, linked):
                results.append({"input_row": r, "matches": entity.get("matches", [])})
                raw_f.write(json.dumps({"input_row": r, "entity": entity}, ensure_ascii=False) + "\n")

            next_index = min(batch_start + NEL_BATCH_SIZE, len(rows))
            raw_f.flush()
            save_checkpoint(checkpoint_path, results, next_index)
            print(f"  {next_index}/{len(rows)} processed", end="\r", flush=True)
            time.sleep(0.05)
    finally:
        raw_f.close()

    print()

    # ── Wide CSV output ───────────────────────────────────────────────────────
    input_cols = list(rows[0].keys())
    match_cols = []
    for k in range(1, TOP_K + 1):
        match_cols += [f"m{k}_label", f"m{k}_uri", f"m{k}_score", f"m{k}_confidence"]
    headers = input_cols + ["nel_model_label", "n_matches", "best_score", "best_confidence"] + match_cols

    n_with_match = 0
    counts = {"exact": 0, "high_confidence": 0, "low_similarity": 0}
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerow(headers)
        for res in results:
            row = res["input_row"]
            matches = res["matches"]
            best_score = matches[0]["similarity_score"] if matches else 0.0
            best_conf = confidence_level(best_score) if matches else ""
            if matches:
                n_with_match += 1
                counts[best_conf] = counts.get(best_conf, 0) + 1

            line = [row.get(c, "") for c in input_cols]
            line += [args.label, len(matches), f"{best_score:.4f}", best_conf]
            for k in range(TOP_K):
                if k < len(matches):
                    m = matches[k]
                    score = m["similarity_score"]
                    line += [
                        m["entity"]["preferred_label"],
                        m["entity"]["origin_uri"],
                        f"{score:.4f}",
                        confidence_level(score),
                    ]
                else:
                    line += ["", "", "", ""]
            w.writerow(line)

    # ── Summary ───────────────────────────────────────────────────────────────
    total = len(results)
    print(f"\nDone. {n_with_match}/{total} titles got at least one match.")
    print(f"  by best-match confidence:")
    for k in ("exact", "high_confidence", "low_similarity"):
        print(f"    {k}: {counts.get(k, 0)}")
    print(f"\nCSV:  {out_path}")
    print(f"JSONL (raw): {raw_jsonl_path}")

    if os.path.exists(checkpoint_path):
        os.remove(checkpoint_path)


if __name__ == "__main__":
    main()
