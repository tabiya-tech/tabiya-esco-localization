# Country Localizations

Each country folder contains the complete pipeline for mapping a national occupational taxonomy to Tabiya ESCO.

## Completed Countries

| Country | Taxonomy | Occupations | ESCO Match Rate | Status |
|---------|----------|-------------|-----------------|--------|
| [Argentina](argentina_cno2017/) | CNO-2017 | 5,690 | 89.6% | Complete |
| [Kenya](kenya_kesco/) | KESCO | 5,917 | 97.4% | Complete |
| [Ethiopia](ethiopia/) | ELMIS | 4,135 | 81.0% | Stage 1 + 2 complete; Stage 3 (1,300 items) live in review app |

## Adding a New Country

Use the setup script:

```bash
python scripts/setup_new_country.py
```

This creates the folder structure, config.json, and template scripts.

See [LOCALIZATION_PIPELINE.md](../docs/LOCALIZATION_PIPELINE.md) for matching details.

## Folder Structure

```
{country}_{taxonomy}/
├── config.json              # Required: country metadata
├── README.md                # Status, results, notes
├── data/
│   ├── {source_files}       # Raw input files
│   └── {taxonomy}_embeddings.json  # Generated embeddings
├── scripts/
│   ├── 00_prepare_data.py   # Data preparation
│   ├── 01_generate_embeddings.py
│   └── 02_run_matching.py   # Matching pipeline
├── outputs/
│   ├── {prefix}_matches_final.json   # All matches
│   ├── {prefix}_matches_final.xlsx   # Excel version
│   ├── {prefix}_review_items.json    # For human review
│   ├── {prefix}_review_items.xlsx    # Excel version
│   └── {prefix}_group_crosswalk.xlsx # ISCO group mapping
└── docs/                    # Optional: methodology, session context
```

## config.json

Each country must have a `config.json` file:

```json
{
  "name": "Country Taxonomy Name",
  "country_code": "XX",
  "source_taxonomy": "Taxonomy",
  "description": "Full taxonomy description",
  "local_code_field": "code_field_in_data",
  "local_label_field": "label_field_in_data",
  "local_label_en_field": "english_label_field"
}
```

This file is used by the review app to auto-discover projects.

## Prerequisites

1. Install dependencies: `pip install -r requirements.txt`
2. Set up `.env` at project root with `GEMINI_API_KEY`
3. Ensure ESCO data is in `shared_data/`

## Pipeline Scripts

Run in order:

```bash
# 0. Prepare data (if needed)
python scripts/00_prepare_data.py

# 1. Generate embeddings
python scripts/01_generate_embeddings.py

# 2. Run matching pipeline
python scripts/02_run_matching.py
```

## Expected Results

| Category | Description |
|----------|-------------|
| exact | Exact label match |
| high_conf_unconstrained | High similarity (>0.85) |
| llm_approved | LLM validated match |
| new_local | No ESCO equivalent |

## Human Review Workflow

After running the pipeline:

1. Load to review app: `python review_app/scripts/load_project_data.py`
2. Review items in the web interface (MATCH, NEW_LOCAL, SKIP)
3. Export results: `python review_app/scripts/export_review_results.py`
