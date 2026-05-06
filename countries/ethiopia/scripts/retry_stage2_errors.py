"""
Retry stage-2 rows that errored on the first run.

Reads stage2_results.csv, finds rows where stage2_decision == 'error',
looks up each by elmis_title in matches_minilm.csv, re-calls the LLM,
and overwrites the error rows in place.

Usage:
    python scripts/retry_stage2_errors.py
    python scripts/retry_stage2_errors.py --provider deepseek
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent.parent
ROOT_DIR = BASE_DIR.parent.parent
INPUT_CSV = BASE_DIR / "outputs" / "matches_minilm.csv"
RESULTS_CSV = BASE_DIR / "outputs" / "stage2_results.csv"
CONFIG_PATH = BASE_DIR / "config.json"

sys.path.insert(0, str(Path(__file__).parent))
from llm_provider import make_provider  # noqa: E402

# Reuse helpers from 00_run_stage2.py via runtime import
import importlib.util
_spec = importlib.util.spec_from_file_location("stage2", Path(__file__).parent / "00_run_stage2.py")
_stage2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_stage2)
build_prompt = _stage2.build_prompt
load_esco_lookups = _stage2.load_esco_lookups
normalise = _stage2.normalise

load_dotenv(ROOT_DIR / ".env")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["gemini", "deepseek"], default=None)
    args = ap.parse_args()

    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    llm_cfg = dict(cfg.get("llm") or {})
    if args.provider:
        llm_cfg["provider"] = args.provider

    print("Loading data...")
    results = pd.read_csv(RESULTS_CSV).fillna("")
    matches = pd.read_csv(INPUT_CSV).fillna("")
    matches_idx = matches.set_index("informal work in eng", drop=False)
    uri_lookup, isco4_labels = load_esco_lookups()

    err_mask = results["stage2_decision"] == "error"
    err_rows = results[err_mask]
    print(f"Error rows to retry: {len(err_rows)}")
    if len(err_rows) == 0:
        print("Nothing to do.")
        return

    provider = make_provider(llm_cfg)
    model_name = getattr(provider, "model_name", "")
    print(f"Provider: {provider.name} / {model_name}")

    fixed = 0
    still_err = 0
    for i, r in err_rows.iterrows():
        title = r["elmis_title"]
        if title not in matches_idx.index:
            print(f"  [skip] {title!r} not in matches_minilm.csv")
            continue
        match_row = matches_idx.loc[title]
        if isinstance(match_row, pd.DataFrame):
            match_row = match_row.iloc[0]

        prompt, candidates = build_prompt(match_row, uri_lookup, isco4_labels)
        raw = provider.generate_json(prompt)
        norm = normalise(raw, candidates)

        for col, val in norm.items():
            results.at[i, col] = val
        results.at[i, "raw_response"] = json.dumps(raw, ensure_ascii=False) if raw else ""
        results.at[i, "llm_provider"] = provider.name
        results.at[i, "llm_model"] = model_name

        if norm["stage2_decision"] == "error":
            still_err += 1
            print(f"  [still err]  {title!r}")
        else:
            fixed += 1
            sel = norm["stage2_selected_index"] or "-"
            print(f"  [{norm['stage2_decision']:9s}] sel={sel} conf={norm['stage2_confidence']}  | {title!r}")

    results.to_csv(RESULTS_CSV, index=False, encoding="utf-8-sig")
    print(f"\nFixed: {fixed} | Still errored: {still_err}")
    print(f"Updated: {RESULTS_CSV}")


if __name__ == "__main__":
    main()
