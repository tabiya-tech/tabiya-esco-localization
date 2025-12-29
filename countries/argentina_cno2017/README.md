# Argentina CNO-2017 Localization

Mapping Argentina's Clasificador Nacional de Ocupaciones (CNO-2017) to Tabiya ESCO.

## Status

**Matching Complete** - 89.6% ESCO-matched (5,101), 10.4% new_local (589)

## Source Data

- **Taxonomy**: CNO-2017 (Clasificador Nacional de Ocupaciones)
- **Source**: INDEC (Instituto Nacional de Estadistica y Censos)
- **Language**: Spanish
- **Occupations**: 5,690
- **ISCO Crosswalk**: Official PDF from INDEC

## Pipeline Scripts

Run in order:

```bash
# 1. Extract taxonomy structure from PDF text
python scripts/01_extract_taxonomy.py

# 2. Translate Spanish titles to English
python scripts/02_translate_taxonomy.py

# 3. Process ISCO crosswalk
python scripts/03_process_crosswalk.py

# 4. Generate embeddings for CNO occupations
python scripts/04_generate_embeddings.py

# 5. Run full matching pipeline
python scripts/05_run_matching.py

# 6. Generate final output files
python scripts/06_generate_output.py
```

## Data Files

```
data/
├── cno2017_extracted.xlsx         # Extracted from PDF
├── cno2017_source_translated.xlsx # With English translations
├── cno2017_complete.xlsx          # Final processed taxonomy
└── cno2017_embeddings.json        # Gemini embeddings

outputs/
├── arg_cno2017_matches_final.json   # All matches
├── arg_cno2017_matches_final.xlsx   # Excel version
├── arg_cno2017_review_items.xlsx    # Items for human review
└── arg_cno2017_group_crosswalk.csv  # ISCO group mapping
```

Note: ESCO embeddings use Spanish version from `shared_data/esco_embeddings_es_gemini.json`

## Results

| Category | Count | Percentage |
|----------|-------|------------|
| exact | 2,847 | 50.0% |
| alt_label | 301 | 5.3% |
| high_conf_unconstrained | 892 | 15.7% |
| llm_approved | 472 | 8.3% |
| phase3_matched | 589 | 10.4% |
| new_local | 589 | 10.4% |

## Notes

- Uses Spanish ESCO for better semantic matching
- ISCO crosswalk had format issues initially (fixed in 03_process_crosswalk.py)
- 589 new_local items need human review via review_app/
