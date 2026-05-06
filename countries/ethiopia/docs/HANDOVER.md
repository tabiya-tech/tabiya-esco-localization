# Ethiopia taxonomy localization — handover

**Status:** stage 1 (MiniLM NEL matching) complete and ready to be folded into `TabiyaESCO_Localization/`. Gemini comparison parked — see *Known blocker* below.

## What was done

Took the 4,135 ELMIS-supplied Ethiopian job titles in `output_with_sectors.csv` and linked each to its top-5 ESCO occupations using the deployed Tabiya classifier's NEL v2 service (`https://dev.classifier.tabiya.tech`) against the Tabiya (ESCO 1.1.1) **v2.0.1-rc.1** taxonomy (model id `68933862382aab4c7de13ec6`).

Per-title results, per-match similarity scores, and confidence labels (`exact ≥0.95 / high_confidence ≥0.85 / low_similarity ≥0.50`) are preserved in CSV form so they can drive any downstream review (manual or LLM).

## Artifacts (in this folder unless noted)

### Canonical output — use this as stage 1 input

- `matches_minilm.csv` — 4,135 rows × top-5 matches each, wide-format. Columns: source columns (English title, Amharic title, sector, sub sector, professional/formal flag), `nel_model_label`, `n_matches`, `best_score`, `best_confidence`, then `m1_label / m1_uri / m1_score / m1_confidence` … `m5_…`. UTF-8-BOM so Excel renders Amharic correctly.
- `matches_minilm.jsonl` — raw per-title NEL response (one JSON object per line). Useful if a later stage wants fields beyond the 5 we wrote into the CSV (e.g. `uuid`, `uuid_history`, full `alt_labels` of the matched ESCO entry).

### Source / inputs

- `output_with_sectors.csv` — the input title list. Required column for the script: `informal work in eng`. Optional: `Profession in Amharic`, plus sector metadata that's just passed through.
- Baseline taxonomy: `../TabiyaESCO_Localization/shared_data/esco_taxonomy/occupations.csv` (v2.0.1-rc — diffs vs rc.1 are scope notes only, no `ALTLABELS` changes per release notes).

### Scripts

- `match_titles_topk.py` — what produced `matches_minilm.csv`. Slimmed-down NEL matcher: no taxonomy download, no enrichment, top-K configurable (constant `TOP_K = 5`), resumable checkpoints. **This is the right script to carry into the localization repo.**
- `build_ethiopian_taxonomy.py` — colleague's original full-pipeline script (downloads taxonomy, enriches `occupations.csv`, only keeps best-confidence-per-occupation). Kept unmodified for reference. Loses per-title scores, which is why we wrote `match_titles_topk.py`.
- `compare_methods.py` — built earlier to A/B the colleague's MiniLM vs Gemini zips; only relevant if Gemini is revisited.

### Pre-existing artifacts from the colleague's runs

- `ethiopian_taxonomy_all-MiniLM-L6-v2-occupation-fine-tuned.zip`, `ethiopian_taxonomy_gemini-embedding-001.zip` — full enriched taxonomies (occupations.csv with appended alt-labels + a per-occupation `CONFIDENCE` column, plus passthrough taxonomy files). Note these were built against *different* taxonomy snapshots (`v2.0.1-rc.1` vs `v2.0.1-rc`), and per-title scores are not preserved.
- `_unpacked/` — both zips extracted, used for the comparison script.
- `comparison_minilm_vs_gemini.{xlsx,csv}` — diff against the v2.0.1-rc baseline: 1,419 agree / 2,716 disagree / 0 unmatched out of 4,135. Only useful if Gemini comes back into play.

## How to reproduce stage 1

```bash
cd <ethiopia-working-dir>
export NEL_API_KEY=<the AIza... key currently used>
python match_titles_topk.py \
  --input output_with_sectors.csv \
  --label minilm \
  --nel-url https://dev.classifier.tabiya.tech
```

Runs in ~2 minutes. Writes `matches_minilm.csv` and `matches_minilm.jsonl`. Resumable via `matches_minilm.csv.checkpoint.json` if interrupted.

Stats from this run (for parity-checking any re-runs):
- 4,135 / 4,135 matched
- 96 exact / 1,516 high_confidence / 2,523 low_similarity (best-of-top-5 per title)

## Known blocker — Gemini path

The colleague's earlier Gemini run (96 exact / **2,910 high** / 1,162 low — note the high-confidence inflation discussed previously) cannot currently be reproduced via the deployed classifier with our API key:

- We confirmed by running the script twice — once after toggling the NEL model in the configuration UI to `models/gemini-embedding-001` — and got bit-identical results to the MiniLM run on all 4,135 titles. So the UI toggle didn't propagate to API-key-authenticated requests.
- Most likely the model selected at `app.dev.classifier.tabiya.tech/configuration` is scoped to the Firebase-authenticated UI session, not to API-key calls.

**To unblock**, options are:

1. Ask the classifier owner how to select the NEL model for API-key requests (per-key binding? request header?).
2. Auth via Firebase access token (`Authorization: Bearer …`) instead of `X-API-Key`. `match_titles_topk.py` would need a small tweak.
3. Bypass the classifier and run NEL locally with a Google AI Studio Gemini key (embed all 3,074 v2.0.1-rc.1 occupations once, embed inputs, cosine-similarity top-5). Defensible but methodologically distinct from the deployed classifier — flag in any write-up.

## Suggested home in `TabiyaESCO_Localization/`

Following the existing `countries/{kenya_kesco,zambia,argentina_cno2017}` convention:

```
countries/ethiopia/
  data/
    output_with_sectors.csv               # input from ELMIS
  scripts/
    match_titles_topk.py                  # ours
    build_ethiopian_taxonomy.py           # colleague's original (reference)
  outputs/
    matches_minilm.csv                    # stage 1 canonical
    matches_minilm.jsonl                  # raw NEL payloads
  docs/
    HANDOVER.md                           # this file
  config.json                             # taxonomy_model_id, nel_url, etc.
```

Pull `config.json` keys from the existing kenya/zambia configs for the right shape; the only Ethiopia-specific values are `taxonomy_model_id=68933862382aab4c7de13ec6` and the input CSV column names (`informal work in eng`, `Profession in Amharic`).

## Open questions for whoever picks this up

- Are the MiniLM thresholds (`0.95 / 0.85 / 0.50`) appropriate for Ethiopia, or should they be re-derived against a manually-validated sample? Same question that applied to Kenya/Zambia probably applies here.
- The Amharic alt-labels: the colleague flagged these as "still questionable" — they're being added 1:1 to whichever ESCO occupation the English title linked to, which assumes the Amharic title is a faithful translation of the English. Worth a sanity-check pass.
- 7 source titles in `output_with_sectors.csv` are duplicates that linked to different occupations on different runs (top-1 across batches) — see the conflicts callout in `compare_methods.py` output. Consider deduping the input or using stable ordering to make runs deterministic.
