# Country Activity Log

High-level updates across all localization efforts. For detailed session context, see each country's `docs/SESSION_CONTEXT.md`.

---

## Argentina (CNO-2017)

### 2024-12-17 - Argentina
- Completed Approach 5: Gemini embeddings with 95.9% high-confidence matches
- Began Phase 2 categorization (exact/alt_label/sibling/child)
- Status: In Progress

### 2025-01-22 - Argentina
- Framework documentation setup, multi-country folder structure established
- Migrated all Argentina files to countries/argentina_cno2017/
- Status: In Progress

### 2025-12-17 - Argentina
- Fixed categorization logic (replaced word-count approach with hybrid rules + LLM)
- Created categorize_matches_v2.py with deputy prefix detection, unit clustering
- Sample test: 47% rule-categorized, 53% need LLM
- Status: In Progress

### 2025-12-18 - Argentina
- Raised crosswalk fallback threshold 0.5 to 0.85, reran Phase 1 (99.7% high-confidence)
- Full Phase 2A run: 2,347 (41.1%) rule-categorized, 3,369 (58.9%) NEEDS_LLM
- Added Spanish ESCO to Supabase (3,074 occupations)
- Built Phase 2B with Gemini function calling + Supabase taxonomy search tools
- Status: In Progress - Ready to run Phase 2B sample test

### 2025-12-22 - Argentina
- Fixed crosswalk key building (8.9% -> 92.6% coverage)
- Ran full Phase 2B on 3,369 NEEDS_LLM: 71.1% matched, 28.9% new_local
- Status: Milestone Reached - Phase 2B complete, pending pipeline review

### 2025-12-25 - Argentina
- Ran full matching pipeline: Phase 1 + Phase 1B + Phase 2 + Phase 3 (hybrid candidate search)
- Phase 3 used hybrid candidates (semantic + ISCO-constrained) with LLM selection
- Final result: 89.6% ESCO-matched (5,101), 10.4% new_local (589)
- Status: Milestone Reached - Matching pipeline complete, ready for skill assignment

### 2025-12-27 - Argentina
- Completed Review Tool UI with Tabiya Design System (Oxford Blue, Tabiya Green, DM Mono/Inter)
- Added CNO hierarchy context (minor code + English title) to review items
- Implemented tree interaction: single-click toggle, double-click select, auto-close descendants
- Added auto-hide for ES labels when same as EN (multi-language support)
- Status: Milestone Reached - Review tool UI complete, ready for deployment

### 2026-04-19 - Argentina
- Added Spanish ESCO skills parent-column enrichment utility (shared_data/esco_taxonomy_es/add_parent_column.py)
- Script picks closest parent for skills with multiple parents: skill parent when chain exists through shared skillgroup, else skillgroup as categorical home
- Generated skills_with_parent.csv (130,594 rows) with PARENTID/PARENTOBJECTTYPE/PARENTLABEL columns
- Status: In Progress - Enrichment utility available for downstream use

---

## Ethiopia (ELMIS)

### 2026-04-28 - Ethiopia
- Scaffolded `countries/ethiopia/` and folded in stage-1 work from the Ethiopia working folder (`~/Dropbox/Tabiya/Taxonomy/Ethiopia`).
- Imported 4,135 ELMIS titles + Amharic + sector metadata, MiniLM NEL top-5 matches CSV/JSONL, the matcher script, and the colleague's reference taxonomy-builder script.
- Stage 1 results: 96 exact / 1,516 high_confidence / 2,523 low_similarity (best-of-top-5 per title) against Tabiya v2.0.1-rc.1.
- Wrote `config.json` capturing NEL settings, source columns, English-first translation strategy, and ~23k future-scale target.
- Status: In Progress - Stage 1 complete.

### 2026-04-30 - Ethiopia
- Tested sub-sector -> ISCO 4-digit filter as a stage-1 refinement (Gemini-mapped 216 sub-sectors, then filtered ESCO matches to titles whose group shares the first 2 ISCO digits).
- Filter dropped 502 titles to "no matches at all" and 463 changed top-1; ELMIS partner review packet built (`docs/SUBSECTOR_FILTER_REVIEW.md`, `outputs/ethiopia_subsector_filter_review.xlsx`).
- Decision: filter parked as exploration; canonical pipeline reverted to unfiltered stage-1.
- Built stage-2 LLM matcher with swappable provider (Gemini default, DeepSeek supported via `scripts/llm_provider.py` and `config.json` switch).
- Status: In Progress - Stage-2 build complete, ready to run.

### 2026-05-05 - Ethiopia
- Ran stage-2 LLM matching on 2,522 titles (best_score < 0.85). Parallelized to 10 workers for ~10x speedup.
- Final canonical pipeline: 1,613 stage-1 auto-pass + 1,738 stage-2 LLM picks + 783 no_match = **81.0% ESCO-matched (3,351/4,135)**.
- 2 errors retried (LLM returned JSON list instead of object); now 0 errors.
- Built stage-2 review packet (`outputs/ethiopia_stage2_review.xlsx`, 7 sheets).
- Tested expanded-pool retry on the 285 no_match titles in mapped sub-sectors: 156 flipped to match (54.7%), 92% of flips picked a candidate the NEL classifier never surfaced. Promotion declined; kept as exploration (`docs/EXPANDED_POOL_EXPLORATION.md`).
- Status: Milestone Reached - Stage 1 + Stage 2 complete.

### 2026-05-06 - Ethiopia
- Built stage-3 review pile: 784 stage-2 no_match + 512 medium-conf + 4 low-conf matches = 1,300 items.
- Pushed to Tabiya review app's Supabase backend (project id 9, country code ET) with synthetic 5-digit `elmis_code`s.
- Added `sector` + `sub_sector` columns to `review_items` schema (SQL migration `review_app/sql/06_add_sector_columns.sql`); review app's Local Occupation card now shows them.
- Rebranded the review app: removed Tabiya branding, switched to neutral Oxford blue + white + slate grey palette per partner request.
- Status: Awaiting ELMIS Review - 1,300 items live in the review app.

---

## Kenya (KESCO)

### 2025-12-24 - Kenya
- Implemented constrained semantic matching v2 (hierarchical ISCO + multi-embedding)
- Full run on 5,917 occupations: 26.7% high confidence, 63.5% need review
- Completed LLM evaluation (constrained): 42% confirmed good, 54.5% need different match
- Started unconstrained LLM evaluation for ISCO crosswalk mismatches (needs optimization)
- Status: In Progress

### 2025-12-26 - Kenya
- Switched from sentence-transformers to Gemini embeddings (93.5% high-quality vs 26.7% before)
- Created shared English ESCO embeddings in shared_data/ for reuse
- Ran Argentina-style pipeline (Step 1A + 1B): 383 need LLM review, 884 crosswalk mismatches
- Status: Milestone Reached - Phase 1 complete, ready for Phase 2 LLM validation

### 2025-12-26 - Kenya (Session 2)
- Completed full matching pipeline: Step 1A, 1B, 2A, 2B
- Expanded Step 2B scope to include matches <90% similarity (not just rejected)
- Final result: 97.4% ESCO-matched (5,761), 2.6% new_local (156)
- Created final output and combined pipeline script for documentation
- Status: Milestone Reached - Matching pipeline complete, ready for skill assignment

### 2025-12-30 - Kenya
- Added needs_review flag to final output (821 low-similarity + 156 new_local = 977 items)
- Loaded 975 review items to Supabase review tool
- Tested simplified Step 2A prompt - kept original (better balance)
- Status: In Progress - Human review phase started

### 2026-01-21 - Kenya
- Built review export pipeline with APPROVE/MATCH/NEW_LOCAL distinction; fixed 475 items retroactively
- Created taxonomy merge script; produced first localized occupations.csv (2,547 alt labels added)
- Status: Milestone Reached - Taxonomy merge Phase 1 complete; NEW_LOCAL handling pending

### 2026-02-02 - Kenya
- Human review 100% complete: 975/975 items reviewed (470 APPROVE, 291 MATCH, 154 NEW_LOCAL, 60 SKIP)
- Exported review decisions to matches_final files
- Ran taxonomy merge: 2,760 alt labels added to 955 ESCO occupations
- Fixed review app bug: NEW_LOCAL parent selection was not saving (all 154 items affected)
- Status: Milestone Reached - Taxonomy merge complete; NEW_LOCAL items need re-review for parent codes

### 2026-02-04 - Kenya
- Built skill assignment UI in review tool with full ESCO skill group hierarchy (S, T, K categories)
- Created Supabase table for skill_group_selections; UI persists selections per occupation
- 69 new local occupations ready for skill group assignment via UI
- Status: Milestone Reached - Skill assignment UI complete, ready for manual skill group selection

### 2026-02-18 - Kenya
- Replaced LLM-based O*NET matching with semantic embedding similarity (cosine over Gemini embeddings)
- Created shared O*NET embedding generation script and new local embedding step in 05_create_new_local.py
- Refined LLM skill selection prompt to prioritise closest O*NET match over transferable skills
- Test run: skill counts improved from 305/334/29/16 to 109/59/76/41 (target 25-50)
- Status: In Progress - Pipeline ready for full run on 69 occupations

### 2026-04-19 - Kenya
- Built Swahili translation pipeline: multi-model comparison (4 models), back-translation QA, retry iterations
- Generated final Swahili output with quality flags (occupations_translated_sw_FINAL_with_flags.csv)
- Produced small test runs (translations_test, translations_test_50) for validation
- Committed shared O*NET embedding generator script (shared_data/generate_onet_embeddings.py) with bundled source
- Status: Milestone Reached - Swahili translation outputs produced, pending review

---

## Zambia

### 2026-04-09 to 2026-04-11 - Zambia
- Set up project, imported 73 NOS PDFs from Zambia Qualifications Authority (8 sectors)
- Extracted 19,872 skill phrases; built 10-script pipeline for full localization
- Occupation matching: 56 MATCH, 16 NEW_LOCAL (with descriptions, alt labels)
- Skill matching: 683 new skills, 9,772 alt labels added to 1,456 ESCO skills, 416 PC-derived gaps
- Generated Tabiya 9-file taxonomy output (3,090 occupations, 14,579 skills, 135,433 relations)
- Created shared reference: docs/SKILL_DEFINITIONS_AND_CONTEXTUALIZATION.md
- Status: Milestone Reached - Taxonomy output generated, pending human review and ISCO code assignment

### 2026-04-19 - Zambia
- Switched new local occupation code format from `{ISCO}.ZM.{suffix}` to Kenya-style sequential `{ISCO}_{seq}`
- Placed new local occupations in occupation hierarchy under their ISCO unit group (was previously skipped, leaving locals top-level)
- Regenerated 9-file taxonomy output with updated codes and hierarchy entries
- Status: In Progress - Code format aligned with Kenya; pending human review of finalised outputs

---

## Ukraine

*No activity yet.*

---

## Bosnia & Herzegovina

*No activity yet.*

---

## Framework

### 2025-12-17 - Framework
- Set up session continuity commands (start_session, close_session)
- Reorganized docs structure for multi-country support
- Status: In Progress

### 2025-12-28 - Framework
- Documented actual 4-step pipeline (1A, 1B, 2A, 2B) in new LOCALIZATION_PIPELINE.md
- Removed outdated docs: ARCHITECTURE.md, PIPELINE_SPECIFICATION.md, DECISIONS_LOG.md
- Updated all references across CLAUDE.md, README.md, session commands
- Status: Milestone Reached - Framework docs reflect actual implementation

### 2026-01-06 - Framework
- Set up GitHub repo (tabiya-tech/tabiya-esco-localization) and deployed review app to GitHub Pages
- Major review app improvements: Approve button, keyword search, Google search icon, help modal, recently reviewed list
- Created setup_new_country.py script and GitHub Actions workflow for review app deployment
- Status: Milestone Reached - Framework and review app production-ready (pending push of latest changes)

---

## Entry Template

```markdown
### [YYYY-MM-DD] - [Country/Framework]
- [Brief summary of work done]
- Status: [In Progress / Milestone Reached / Blocked / Complete]
```
