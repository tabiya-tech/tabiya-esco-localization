# Ethiopia ELMIS Localization

Mapping the Ethiopia ELMIS occupational title list to Tabiya ESCO.

## Status

**Stage 1 + Stage 2 complete. Stage 3 (human review) live in the review app.**

| Stage | Result |
|---|---|
| Stage 1 NEL classifier match | 4,135 / 4,135 titles matched (top-5 ESCO each) |
| Stage 2 LLM match (Gemini) | 1,613 auto-pass + 1,738 LLM picks + 783 no_match |
| Stage 3 review pile in Supabase | 1,300 items (no_match + low/medium stage-2 matches) awaiting ELMIS review |
| **ESCO-matched today** | **3,351 / 4,135 = 81.0%** |

## Source Data

- **Taxonomy**: ELMIS title list (ELMIS = Ethiopian Labour Market Information System)
- **Language**: English (Amharic translations supplied as a parallel column)
- **Occupations in this batch**: 4,135
- **Total ELMIS titles (future)**: ~23,000 — pipeline must be configurable so ELMIS can scale up
- **ISCO Crosswalk**: None in source data — codes will be generated downstream

## Stage 1 results (from MiniLM run, top-1 best confidence)

| Confidence | Count | Notes |
|------------|-------|-------|
| exact (>= 0.95) | 96 | |
| high_confidence (>= 0.85) | 1,516 | |
| low_similarity (>= 0.50) | 2,523 | Will need LLM review or new_local treatment |
| **Total matched** | **4,135 / 4,135** | |

See `docs/HANDOVER.md` for the full stage-1 write-up, including the Gemini-path blocker.

## Pipeline

```bash
# Stage 1 - NEL classifier match (DONE; re-run only if NEL config changes)
python scripts/match_titles_topk.py \
  --input data/output_with_sectors.csv \
  --label minilm \
  --nel-url https://dev.classifier.tabiya.tech
# -> outputs/matches_minilm.csv

# Stage 2 - LLM matching for stage-1 best_score < 0.85 (DONE)
python scripts/00_run_stage2.py --workers 10
# -> outputs/stage2_results.csv

# Stage 2 review packet for ELMIS (Excel)
python scripts/build_stage2_review.py
# -> outputs/ethiopia_stage2_review.xlsx

# Stage 3 - build review pile + load to Supabase (DONE)
python scripts/build_review_items_json.py
# -> outputs/ethiopia_elmis_review_items.json
python scripts/build_stage3_review_input.py
# -> outputs/ethiopia_stage3_review_input.xlsx (offline-review variant)
python ../../review_app/scripts/load_project_data.py
# -> pushes 1,300 items to Supabase

# Stage 4 - new-local promotion (TODO after review batch returns)
```

LLM provider for stage 2 is config-driven. To switch to DeepSeek:

```bash
# Option A - edit config.json:    "llm": { "provider": "deepseek", ... }
# Option B - CLI override:
python scripts/00_run_stage2.py --provider deepseek
# Requires DEEPSEEK_API_KEY in .env
```

## Folder Structure

```
data/
  output_with_sectors.csv               # 4,135 ELMIS titles + Amharic + sector

scripts/
  match_titles_topk.py                  # stage 1 NEL matcher (canonical)
  build_ethiopian_taxonomy.py           # colleague's full-pipeline reference (do not run)
  llm_provider.py                       # Gemini / DeepSeek interface (used by stage 2)
  00_run_stage2.py                      # stage 2 LLM matcher (parallel, resumable)
  01_no_match_retry_expanded_pool.py    # exploration: expand candidate pool
  retry_stage2_errors.py                # retry stage-2 rows that returned malformed JSON
  build_stage2_review.py                # builds ethiopia_stage2_review.xlsx
  build_stage3_review_input.py          # builds ethiopia_stage3_review_input.xlsx (offline)
  build_review_items_json.py            # builds the loader-compatible JSON for the review app
  update_supabase_sector.py             # one-shot backfill of sector/sub_sector on Supabase
  archive/                              # parked sub-sector filter experiment

outputs/
  matches_minilm.csv                    # stage 1 canonical (top-5 matches per title)
  matches_minilm.jsonl                  # raw NEL payloads
  stage2_results.csv                    # stage 2 canonical
  stage2_no_match_retry.csv             # exploration: expanded-pool retry results
  ethiopia_stage2_review.xlsx           # 7-sheet Excel of stage-2 outcomes
  ethiopia_stage3_review_input.xlsx     # 1,300-item Excel for offline review
  ethiopia_elmis_review_items.json      # loader payload for the review app's Supabase
  subsector_isco_map.csv                # parked experiment artefact (still useful as exploration data)
  matches_minilm_subsector_filtered.csv # parked experiment artefact
  ethiopia_subsector_filter_review.xlsx # ELMIS partner review packet for the parked experiment

docs/
  HANDOVER.md                           # full stage 1 write-up + open questions
  SESSION_CONTEXT.md                    # current state and next steps
  SUBSECTOR_FILTER_REVIEW.md            # objective writeup of the parked sub-sector filter
  EXPANDED_POOL_EXPLORATION.md          # objective writeup of the no_match retry experiment
```

## Methodology (4-stage pipeline)

1. **Stage 1 — classifier match (DONE).** 4,135 ELMIS titles -> top-5 ESCO via deployed NEL service. Locked in as MiniLM-only; Gemini NEL via deployed classifier is parked due to API-key auth blocker.
2. **Stage 2 — LLM triage** of the ~2,523 low_similarity stage-1 results using Gemini.
3. **Stage 3 — human review** via review_app, capped at ~1,000 cases, for LLM-low-confidence and new_local outputs.
4. **Stage 4 — new-local occupations:** (a) LLM-generate descriptions + alt-labels; (b) skill assignment deferred (ELMIS has no skills data yet).

See `docs/SESSION_CONTEXT.md` for the full design and open decisions.

## Notes

- **Stage 1 = MiniLM, accepted.** Gemini NEL parked. We will document this caveat in the final write-up.
- **Skills out of scope.** ELMIS confirmed no skills data; this project is occupation-matching only.
- **LLM provider divergence:** ELMIS uses DeepSeek; we use Gemini (parity with Kenya/Argentina).
- **English first, then translate:** Final taxonomy locked in English; translation pipeline (modeled on Kenya Swahili) covers Amharic + other Ethiopian languages.
- **Code generation (new_locals only):** Matched titles inherit the matched ESCO occupation's ID. Only new_locals (no ESCO equivalent) need a minted code when promoted to the taxonomy. Working scheme: `{ISCO4}_{seq}` with `9999_NNN` fallback. Extensible to the ~23k-title superset.
- **Sub-sector refinement (parked):** experiment tested then set aside. Filter dropped meaningful numbers of legitimate matches due to seniority/role-level mismatches within correct domains. Scripts under `scripts/archive/`; full writeup in `docs/SUBSECTOR_FILTER_REVIEW.md`; ELMIS-facing review packet at `outputs/ethiopia_subsector_filter_review.xlsx`.
- **Stage-2 LLM provider (swappable):** Gemini by default; DeepSeek supported via the same interface (`scripts/llm_provider.py`). One-line config switch in `config.json` (`llm.provider`).
