# Ethiopia (ELMIS) Session Context

## Session Date
2026-05-06

## Current State
- **Phase**: Stage 1 (NEL) + Stage 2 (LLM) complete. Stage 3 (human review) live in Supabase.
- **Pipeline result**: 81.0% ESCO-matched (3,351/4,135). 1,300 items (no_match + low/medium-confidence stage-2 matches) loaded into the review app for ELMIS partner review.
- **Review app**: rebranded to neutral Oxford-blue + grey palette (no Tabiya branding). Sector + sub-sector now visible in the Local Occupation card. Live at the GitHub Pages URL.
- **Status**: Awaiting ELMIS partner review of the 1,300-item pile. Stage 4 (new-local promotion) and translation pipeline pending.

## Latest Session Update (2026-05-06) - Stage 3 Push + Review App Rebrand

### Stage 3 review pile -> Supabase
Built the loader-compatible review_items.json and pushed all 1,300 items into the Tabiya review app's Supabase backend:

| Bucket | Count |
|---|---:|
| stage-2 no_match (-> potential new_local) | 784 |
| stage-2 match, medium confidence (verify) | 512 |
| stage-2 match, low confidence (verify) | 4 |
| **Total review pile** | **1,300** |

Note: this overshoots the original ~1,000-cap rule of thumb by 30%; user accepted given partner team capacity.

Synthetic codes minted: 5-digit zero-padded `elmis_code` based on row position in `output_with_sectors.csv` (`00001..04135`). Extensible to `99999` for ELMIS's full ~23k-title superset.

### Sector + sub_sector added to review schema
ELMIS reviewers needed sector/sub-sector context next to the title. Required:
- New SQL migration: `review_app/sql/06_add_sector_columns.sql` (adds `sector`, `sub_sector` TEXT columns)
- Loader (`review_app/scripts/load_project_data.py`) and JSON builder both updated to pass through
- `review_app/index.html` shows a new row in the Local Occupation card; browse-mode SELECT queries updated to fetch the columns
- One-shot `countries/ethiopia/scripts/update_supabase_sector.py` backfilled the existing 1,300 rows

### Review app de-Tabiya'd
Visible branding removed:
- `Taxonomy Review Tool` subtitle no longer mentions "Tabiya"
- README rewritten without Tabiya references
- Color palette swapped from Oxford Blue + Tabiya Green/Orange to **Oxford Blue + white + slate greys** (per partner request)
- CSS variables renamed (`--oxford-blue` -> `--primary`, `--tabiya-green*` -> `--accent*`, `--tabiya-orange` -> `--accent-warm`, `--tabiya-gray` -> `--surface-soft`)
- Button hierarchy preserved (Match = navy filled, New Local = slate-700 filled, Approve/Skip unchanged)

### Files added
- New: `countries/ethiopia/scripts/build_review_items_json.py`, `scripts/build_stage3_review_input.py`, `scripts/build_stage2_review.py`, `scripts/retry_stage2_errors.py`, `scripts/update_supabase_sector.py`
- New: `countries/ethiopia/outputs/ethiopia_elmis_review_items.json`, `outputs/ethiopia_stage3_review_input.xlsx`, `outputs/ethiopia_stage2_review.xlsx`
- New: `review_app/sql/06_add_sector_columns.sql`
- Updated: `review_app/index.html`, `review_app/README.md`, `review_app/scripts/load_project_data.py`
- Updated: `countries/ethiopia/config.json` (`local_code_field` set to `elmis_code`, `local_label_field` set to `elmis_title`)

## Previous Session Update (2026-05-05) - Stage-2 Run + Expanded-Pool Exploration

### Stage-2 LLM matching - canonical run complete
Ran `00_run_stage2.py` on all 2,522 titles with `best_score < 0.85`. Final canonical pipeline:

| Outcome | Count | % of 4,135 |
|---|---:|---:|
| Stage-1 auto-pass (>=0.85) | 1,613 | 39.0% |
| Stage-2 LLM match | 1,738 | 42.0% |
| Stage-2 no_match (-> new_local) | 783 | 18.9% |
| **ESCO-matched total** | **3,351** | **81.0%** |

Output: `outputs/stage2_results.csv`. Errors retried via `scripts/retry_stage2_errors.py` (0 remaining).
Review packet: `outputs/ethiopia_stage2_review.xlsx` (7 sheets) and `scripts/build_stage2_review.py`.

### Exploration: no_match retry with expanded candidate pool
Tested whether stage-2 no_match decisions reflect "right ESCO occupation missing from NEL top-5" rather than "no ESCO equivalent." For 285 no_match titles whose sub-sector has a `map` decision, expanded the candidate pool to NEL top-5 + every ESCO occupation in the mapped ISCO 4-digit group, re-prompted with neutral source tags.

- 156 of 285 flipped to match (54.7%); 92% of flips picked a candidate from the expanded ISCO-group pool.
- If promoted, full pipeline match rate would rise from 81.0% to 84.8%.
- 498 no_match titles in `no_map` sub-sectors are not addressed by this approach.

**Decision: kept as exploration, not promoted.** The canonical stage-2 result remains the unfiltered output of `00_run_stage2.py`. Writeup at `docs/EXPANDED_POOL_EXPLORATION.md`. Output at `outputs/stage2_no_match_retry.csv`. Script at `scripts/01_no_match_retry_expanded_pool.py`.

## Previous Session (2026-04-30) - Stage-2 Build

### Sub-sector filter experiment - parked
Tested an extra refinement on top of stage-1 (sub-sector -> ISCO 4-digit map via Gemini, then drop top-5 entries whose ESCO group does not share the first 2 ISCO digits with the sub-sector's mapped group). The experiment:

- Mapped 216 unique (sector, sub-sector) pairs: 96 map / 120 no_map.
- Filter applied to 1,540 of 4,135 stage-1 rows; 502 rows lost all 5 matches and 463 lost their original top-1.
- Captured in `docs/SUBSECTOR_FILTER_REVIEW.md` (objective writeup) and `outputs/ethiopia_subsector_filter_review.xlsx` (8-sheet review packet for ELMIS partner review).
- Decision: **do not include the filter in the active pipeline.** Scripts moved to `scripts/archive/`. Run paths in the review doc updated.

### Built Stage-2 LLM matcher
- `scripts/llm_provider.py` - common interface with `GeminiProvider` and `DeepSeekProvider` implementations, both returning parsed JSON. ELMIS team can switch providers by changing one field in `config.json` (`llm.provider = "gemini" | "deepseek"`) or `--provider` CLI override.
- `scripts/00_run_stage2.py` - reads `outputs/matches_minilm.csv`, sends rows with `best_score < 0.85` to the LLM with all 5 stage-1 candidates plus ESCO descriptions and ISCO group context. Resumable, checkpoints to `outputs/stage2_results.csv`.
- Auto-pass threshold (`stage2.auto_pass_threshold`) and provider config live in `config.json`; CLI flags override.
- Smoke test (`--dry-run`): 4,135 stage-1 rows -> 1,613 auto-pass (>=0.85) -> 2,522 sent to stage-2.

### Files added/changed
- New: `scripts/llm_provider.py`, `scripts/00_run_stage2.py`
- New: `docs/SUBSECTOR_FILTER_REVIEW.md`, `outputs/ethiopia_subsector_filter_review.xlsx`
- New: `outputs/subsector_isco_map.csv`, `outputs/matches_minilm_subsector_filtered.csv`
- Moved: `scripts/00_build_subsector_isco_map.py`, `scripts/01_apply_subsector_filter.py`, `scripts/02_build_review_packet.py` -> `scripts/archive/`
- Updated: `config.json` (added `stage2` and `llm` blocks)

## Original Session (2026-04-28) - Folder Setup

### What Was Accomplished On 2026-04-28

### Folded Ethiopia stage-1 work into TabiyaESCO_Localization
Imported the handover artifacts produced in `~/Dropbox/Tabiya/Taxonomy/Ethiopia/` (work owned by colleague + this user before this repo became the source of truth) into `countries/ethiopia/`:

- `data/output_with_sectors.csv` — 4,135 ELMIS titles + Amharic + sector metadata
- `outputs/matches_minilm.csv` — canonical stage-1 output (top-5 ESCO per title)
- `outputs/matches_minilm.jsonl` — raw NEL payloads
- `scripts/match_titles_topk.py` — NEL matcher used for stage 1
- `scripts/build_ethiopian_taxonomy.py` — colleague's full-pipeline reference (kept unmodified)
- `docs/HANDOVER.md` — stage-1 write-up

### Wrote `config.json`
Captures NEL classifier settings (`taxonomy_model_id`, URL, thresholds), source-data column names (`informal work in eng`, `Profession in Amharic`, sector columns, formality flag), expected scale (4,135 now / ~23,000 future), and the English-first translation strategy.

## Stage 1 Results (carried over from handover)

| Confidence | Count | % |
|------------|-------|---|
| exact (>= 0.95) | 96 | 2.3% |
| high_confidence (>= 0.85) | 1,516 | 36.7% |
| low_similarity (>= 0.50) | 2,523 | 61.0% |
| **Total** | **4,135 / 4,135 matched** | 100% |

NEL service: `https://dev.classifier.tabiya.tech`, model `all-MiniLM-L6-v2-occupation-fine-tuned`, taxonomy `v2.0.1-rc.1` (model id `68933862382aab4c7de13ec6`).

## Decisions Locked This Session

- **Stage 1 = MiniLM, accepted.** Gemini NEL via the deployed classifier stays parked (see `docs/HANDOVER.md` for the auth blocker). We document this caveat in the final write-up and proceed. Local Gemini NEL bypass is on the table later if we want a comparison run, but not blocking.
- **Skills are out of scope for now.** ELMIS team confirmed they have no skills database tied to these occupations. This project is occupation-matching only; skill assignment is deferred (Kenya `06c_combined_skill_assignment.py` will be the reference if/when ELMIS ships skills).

## Methodology — 4-Stage Pipeline (proposal sent to Bereket)

Capturing the methodology shared with the ELMIS team so subsequent scripts implement against this design.

### Stage 1 — Classifier-based first-pass match (DONE for MiniLM)
- 4,135 ELMIS titles -> top-5 ESCO via deployed NEL service against Tabiya v2.0.1-rc.1.
- Pass threshold: ~0.85 (high_confidence).
- **Possible refinement (TBD, may overarchitect):** sub-sector -> ISCO 4-digit map, then constrain stage 1 to the matching ISCO 2- or 3-digit domain.
  - Example: Advertising sub-sector -> ISCO 2431 -> filter classifier matches to ISCO 24 (or 243).
  - Pros: forces domain alignment; rejects high-similarity matches in unrelated domains.
  - Cons: generic sub-sectors ("Other services") don't map cleanly; for those we keep taxonomy-wide matching.
- Decision pending whether to test this refinement before moving to stage 2.

### Stage 2 — LLM triage of imperfect matches
- Input candidates: the ~2,523 low_similarity stage-1 results (best-of-top-5 < 0.85).
- LLM = Gemini (parity with Kenya/Argentina). ELMIS team uses DeepSeek but our pipeline stays on Gemini.
- Alternative input set considered: items where MiniLM and Gemini embeddings disagree (~2,716 cases per the comparison run). Less preferred — exploratory rather than principled.

### Stage 3 — Human review via the review app
- For LLM-low-confidence and new_local outputs only.
- Reviewer decision: approve / match to something else / create new occupation.
- Hard cap: ~1,000 cases. Tune stage 2 thresholds to stay within budget.

### Stage 4 — New-local occupations (titles that could not be matched)
- Sub-task 4a: LLM-generate occupation attributes (description, alt labels) for new-local titles.
- Sub-task 4b: skill assignment — **deferred**. Kenya methodology (`06c_combined_skill_assignment.py`) is the reference. Open question whether to use O*NET. Out of scope until ELMIS supplies skills data or we agree to bootstrap them.

## Open Items From Handover (unchanged)

1. **Threshold calibration.** MiniLM thresholds (0.95 / 0.85 / 0.50) are inherited; the same question applies as Kenya/Zambia — re-derive against a manually validated sample?
2. **Amharic alt-labels** were attached 1:1 to whichever ESCO occupation the English title linked to. Sanity-check pass before promoting to alt-labels in the final taxonomy.
3. **Source dedupe.** 7 ELMIS titles in `output_with_sectors.csv` are duplicates that linked to different ESCO entries on different runs. Dedupe vs stable ordering decision needed before stage 2.

## Next Steps

### IMMEDIATE
1. **Wait on ELMIS partner review** of the 1,300 items in the review app. Cap-overshoot accepted; we'll see how the team progresses.
2. **Plan stage 4 (new-local promotion)** for titles that come back as `NEW_LOCAL` from review. Need: code-generation scheme (`{ISCO4}_{seq}` with `9999_NNN` fallback), LLM-generated description + alt-labels, integration into final 9-file taxonomy.
3. **Export reviewer decisions** when ELMIS finishes a batch. Existing tool: `review_app/scripts/export_review_results.py`.

### DONE
- Stage 1 NEL match (4,135 -> top-5 ESCO each)
- Stage 2 LLM match (1,738 picked, 783 no_match)
- Stage 3 review pile loaded to Supabase (1,300 items: no_match + low/medium stage-2 matches)
- Review app rebranded (Oxford blue + grey + white) and sector/sub_sector added to schema
- Sub-sector filter exploration (parked)
- Expanded-pool no_match retry exploration (parked)

### FUTURE
- Stage 4a: LLM-generated descriptions and alt-labels for new-local titles
- Stage 4b: Skill assignment — **deferred** until ELMIS ships skills data
- Translation pipeline: language-agnostic (Amharic + Afan Oromo + Tigrinya) once English taxonomy is locked
- Re-run pipeline at scale when ELMIS ships the remaining ~19k titles (towards 23k total)

## Notes

- ELMIS team uses DeepSeek for their LLM work; we stay on Gemini for parity with Kenya/Argentina.
- Pipeline must keep the 23k-scale-up path easy: avoid hard-coded row counts, prefer config-driven batching and code-generation.
- Human review budget rule of thumb: cap at ~1,000 cases. Tune stage 2 thresholds accordingly.
- The colleague's `build_ethiopian_taxonomy.py` enriches `occupations.csv` directly, but it loses per-title scores and only keeps best-confidence-per-occupation - do not run as the production path.
