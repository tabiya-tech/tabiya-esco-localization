# Kenya (KeSCO) Session Context

## Session Date
2026-04-21

## Current State
- **Phase**: Swahili translation outputs produced (pending review)
- **Status**: All 69 new local occupations have skills assigned; Swahili translation pipeline run with multi-model comparison and back-translation QA

## Latest Session (2026-04-19 to 2026-04-21) - Swahili Translation Pipeline

### Accomplished
- Built Swahili translation pipeline with multi-model comparison across 4 models
- Ran back-translation QA for quality assurance (back_translation_qa_sw_20260123_103324.csv)
- Iterated through retry cycles on error records (5 retry rounds for failing items)
- Produced final flagged output: `outputs/translations/sw/occupations_translated_sw_FINAL_with_flags.csv`
- Ran small-scale test batches (translations_test, translations_test_50) for validation
- Committed shared O*NET embedding generator script to `shared_data/generate_onet_embeddings.py` with bundled source file

### Output Files (Swahili)
```
outputs/translations/sw/
├── model_comparison_sw_20260123_{104557,111446,115834}.{csv,xlsx}
├── model_comparison_sw_4models.{csv,xlsx}
├── back_translation_qa_sw_20260123_103324.{csv,xlsx}
├── occupations_translated_sw_20260122_191458.csv                      # initial run
├── occupations_translated_sw_20260122_191458_retried{,_retried...}.csv # 5 retry rounds
├── occupations_translated_sw_FINAL_with_flags.csv                     # final with QA flags
├── occupations_review_sw_20260122_191458.xlsx
└── error_records_for_retry.csv
```

## Previous Session (2026-03-12) - Skill Assignment

## What Was Accomplished This Session

### Ran Full O*NET Skill Assignment Pipeline
- Upgraded LLM from Gemini 2.0 Flash to Gemini 3 Flash (much tighter distribution: 39-54 vs 9-101)
- Ran on all 69 occupations: 3,357 skill relations exported
- Added "Selected" filter column to onet_skill_comparison.xlsx

### Developed ISCO Group Pooling Approach
- Alternative to O*NET: LLM selects relevant ISCO 4-digit groups, pools ESCO skills from those groups
- Advantage: stays entirely within ESCO, no external crosswalk dependency
- Tested on 4 occupations; qualitative analysis showed more practical, contextually relevant skills for Kenya

### Combined ISCO + O*NET Approach (Final)
- Merges candidate pools from both ISCO group pooling and O*NET task crosswalk
- Deduplicated candidates; skills in both pools get stronger signal (~65% of selected skills came from both)
- Refined LLM prompt with:
  - Home ISCO group awareness (seniority level: leadership vs practitioner skills)
  - Professional values inclusion (ethics, impartiality, confidentiality)
  - Domain knowledge at strategic level (not hands-on practitioner skills for senior roles)
  - Redundancy avoidance guidance
- Final run: 3,964 skill relations for 69 occupations (avg 57, range 46-63)

### Archived Deprecated Scripts
- Moved `06_assign_skills.py` (skill-group approach) to archive
- Renumbered: `07_onet_skill_assignment.py` -> `06_onet_skill_assignment.py`, `08` -> `07`

### Generated Documentation
- Word document: `docs/Kenya_KESCO_Localization_v2.docx` for website

## Current File Structure

### Scripts (Active)
```
scripts/
├── 00_prepare_data.py
├── 01_generate_embeddings.py
├── 02_run_matching.py
├── 03_merge_taxonomy.py
├── 04_sync_from_supabase.py
├── 05_create_new_local.py
├── 06_onet_skill_assignment.py       # O*NET-only approach (superseded by 06c)
├── 06b_isco_skill_assignment.py      # ISCO-only approach (experimental)
├── 06c_combined_skill_assignment.py  # FINAL: Combined ISCO + O*NET
├── 07_skill_relevance_scoring.py
└── archive/
```

### Output Files
```
outputs/
├── kenya_kesco_matches_final.json
├── kenya_kesco_matches_final.xlsx
├── new_local_working.xlsx
├── new_local_occupations.csv          # 69 occupations
├── new_local_embeddings.json
├── new_local_skill_relations.csv      # 3,964 relations (combined approach)
├── onet_skill_comparison.xlsx         # O*NET-only results (for reference)
├── isco_skill_comparison.xlsx         # ISCO-only results (for reference)
├── combined_skill_comparison.xlsx     # Combined results (final)
└── taxonomy/
    ├── occupations.csv                # 3,143 total (69 new local)
    ├── occupation_hierarchy.csv       # 3,777 entries
    └── occupation_to_skill_relations.csv  # 134,786 total
```

## Current Taxonomy Stats
| Metric | Count |
|--------|-------|
| Total occupations | 3,143 |
| ESCO occupations | 3,007 |
| Local occupations | 136 |
| - Pre-existing (Tabiya) | 67 |
| - New (Kenya) | 69 |
| Hierarchy entries | 3,777 |
| Total skill relations | 134,786 |
| New local skill relations | 3,964 |
| Avg skills per new local | 57 |

## Next Steps

### IMMEDIATE
1. Review Swahili translation flags and resolve remaining error records
2. Update model_info.csv with Kenya localization metadata
3. Clean up experimental scripts (06b could be removed or kept for reference)

### FUTURE
- Kenya-specific alt labels (Sheng terms)
- Skills translation to Swahili (localized_strings.csv)
- Final validation and export to complete 9-file Tabiya format
- Commit and push to deploy review app to GitHub Pages

## Notes
- Combined approach (06c) is the definitive skill assignment method
- Gemini 3 Flash used for both ISCO group selection and skill filtering
- O*NET crosswalk uses different skill IDs than ESCO taxonomy; mapping done via label matching
- The home ISCO group prompt refinement is critical for senior/leadership roles
- Review app runs locally via `python -m http.server`
