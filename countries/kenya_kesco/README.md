# Kenya KESCO Localization

Mapping Kenya Standard Classification of Occupations (KESCO) to Tabiya ESCO.

## Status

**Matching Complete** - 97.4% ESCO-matched (5,761), 2.6% new_local (156)

## Source Data

- **Taxonomy**: KESCO (Kenya Standard Classification of Occupations)
- **Language**: English
- **Occupations**: 5,917
- **ISCO Crosswalk**: Embedded in KESCO codes (first 4 digits = ISCO-08)

## Pipeline Scripts

Run in order:

```bash
# 0. Prepare data - build context file and group crosswalk
python scripts/00_prepare_data.py

# 1. Generate embeddings for KESCO occupations
python scripts/01_generate_embeddings.py

# 2. Run full matching pipeline
python scripts/02_run_matching.py

# 3. Generate final output files
python scripts/03_generate_output.py
```

## Data Files

```
data/
├── KeSCO_occupational_titles.xlsx      # Raw source (5,917 occupations)
├── KeSCO_groups.xlsx                   # Group labels (627 groups)
├── KeSCO_occupations_with_context.xlsx # Enriched with group hierarchy
└── kesco_embeddings.json               # Gemini embeddings

outputs/
├── kenya_kesco_matches_final.json      # All matches
├── kenya_kesco_matches_final.xlsx      # Excel version
├── kenya_kesco_review_items.json       # Items for human review
├── kenya_kesco_group_crosswalk.xlsx    # KESCO-to-ISCO group crosswalk
└── kenya_kesco_groups_needs_review.xlsx # Groups needing manual review
```

Note: ESCO embeddings use English version from `shared_data/esco_embeddings_en_gemini.json`

## Results

| Category | Count | Percentage |
|----------|-------|------------|
| exact | 3,412 | 57.7% |
| high_conf_unconstrained | 1,287 | 21.8% |
| llm_approved | 689 | 11.6% |
| phase3_matched | 373 | 6.3% |
| new_local | 156 | 2.6% |

## Notes

- Uses English ESCO (shared embeddings from shared_data/)
- ISCO codes embedded in KESCO (no separate crosswalk needed)
- Higher match rate than Argentina due to English-English matching
- 156 new_local items need human review via review_app/
