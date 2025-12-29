# Tabiya ESCO Localization Framework

A framework for mapping national occupational taxonomies to the Tabiya ESCO taxonomy in low- and middle-income countries (LMICs).

## Overview

This framework provides a repeatable pipeline for localizing ESCO to national contexts. It combines:
- **Semantic matching** using Gemini embeddings
- **ISCO crosswalk constraints** to improve accuracy
- **LLM validation** for uncertain matches
- **Human review** for items needing manual decision

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Set up environment
cp .env.example .env
# Edit .env to add your GEMINI_API_KEY and Supabase credentials

# Run a country pipeline (example: Kenya)
python countries/kenya_kesco/scripts/00_prepare_data.py
python countries/kenya_kesco/scripts/01_generate_embeddings.py
python countries/kenya_kesco/scripts/02_run_matching.py

# Load review items to Supabase (auto-discovers countries)
python review_app/scripts/load_project_data.py

# After human review, export results back
python review_app/scripts/export_review_results.py
```

## Project Structure

```
TabiyaESCO_Localization/
├── .env.example               # Environment template
├── countries/                 # Country implementations
│   ├── argentina_cno2017/     # Argentina CNO-2017
│   │   ├── config.json        # Country metadata
│   │   ├── data/              # Source data + embeddings
│   │   ├── outputs/           # Pipeline outputs
│   │   └── scripts/           # Pipeline scripts
│   ├── kenya_kesco/           # Kenya KESCO
│   └── _template/             # Template for new countries
├── shared_data/               # Shared resources
│   ├── esco_taxonomy/         # English ESCO files
│   ├── esco_taxonomy_es/      # Spanish ESCO files
│   ├── esco_embeddings_en_gemini.json
│   └── esco_embeddings_es_gemini.json
├── review_app/                # Human review tool
│   ├── scripts/               # Load/export scripts
│   ├── sql/                   # Database schema
│   └── index.html             # Web interface
└── docs/                      # Framework documentation
```

## Country Pipeline

Each country follows this pipeline:

| Step | Script | Description |
|------|--------|-------------|
| 0 | `00_prepare_data.py` | Prepare source data, build group crosswalk |
| 1 | `01_generate_embeddings.py` | Generate Gemini embeddings for local taxonomy |
| 2 | `02_run_matching.py` | Run matching pipeline, produce outputs |

### Outputs

Each country produces:
- `{prefix}_matches_final.json/xlsx` - All matches
- `{prefix}_review_items.json/xlsx` - Items for human review
- `{prefix}_group_crosswalk.csv/xlsx` - ISCO group mapping

## Review Workflow

```
Pipeline outputs → Supabase → Human Review → Export back to country
```

1. **Load**: `python review_app/scripts/load_project_data.py`
   - Auto-discovers countries with `config.json`
   - Shows status, prompts for selection

2. **Review**: Use web app to make decisions (MATCH, NEW_LOCAL, SKIP)

3. **Export**: `python review_app/scripts/export_review_results.py`
   - Pulls decisions from Supabase
   - Merges into `matches_final.json/xlsx`

## Adding a New Country

Use the setup script to create a new country project:

```bash
python scripts/setup_new_country.py
```

This will prompt for country details and create:
- Folder structure (`data/`, `scripts/`, `outputs/`, `docs/`)
- `config.json` with country metadata
- Template pipeline scripts
- Session context documents

Then:
1. Add source taxonomy data to `data/`
2. Customize the pipeline scripts for your data format
3. Run the pipeline
4. Load to review app: `python review_app/scripts/load_project_data.py`

## Environment Variables

Set in `.env`:
```
GEMINI_API_KEY=your_key_here
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your_service_role_key
SUPABASE_ANON_KEY=your_anon_key
```

## Completed Localizations

| Country | Taxonomy | Occupations | Status |
|---------|----------|-------------|--------|
| Argentina | CNO-2017 | 5,690 | Complete |
| Kenya | KESCO | 5,917 | Complete |

## Technologies

- **Python 3.11+**
- **Gemini API** for embeddings and LLM validation
- **pandas/numpy** for data processing
- **Supabase** for review tool backend

## Documentation

- [docs/LOCALIZATION_PIPELINE.md](docs/LOCALIZATION_PIPELINE.md) - Matching process details
- [docs/PROJECT_BRIEF.md](docs/PROJECT_BRIEF.md) - Vision and principles
- [docs/CODING_STANDARDS.md](docs/CODING_STANDARDS.md) - Development standards

## License

Code: MIT License
Data outputs: CC BY 4.0
