# Tabiya ESCO Localization Framework

A framework for localizing the Tabiya ESCO taxonomy for low- and middle-income countries (LMICs). Supports two approaches: mapping existing national taxonomies to ESCO, or adapting ESCO using national occupational standards (NOS) where no national taxonomy exists.

## Overview

This framework provides repeatable pipelines for localizing ESCO to national contexts. It combines:
- **Semantic matching** using Gemini embeddings
- **LLM validation** for occupation and skill matching decisions
- **Skills vs tasks distinction** following ESCO conventions (see [Skill Definitions](docs/SKILL_DEFINITIONS_AND_CONTEXTUALIZATION.md))
- **Skill contextualisation** adding country-specific alt labels and new skills in ESCO style
- **Human review** for items needing manual decision

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Set up environment
cp .env.example .env
# Edit .env to add your GEMINI_API_KEY and Supabase credentials

# Run a country pipeline (example: Kenya - national taxonomy approach)
python countries/kenya_kesco/scripts/00_prepare_data.py
python countries/kenya_kesco/scripts/01_generate_embeddings.py
python countries/kenya_kesco/scripts/02_run_matching.py

# Run a country pipeline (example: Zambia - NOS-based approach)
python countries/zambia/scripts/01_extract_nos_skills.py
python countries/zambia/scripts/02_match_occupations.py
# ... (see countries/zambia/docs/METHODOLOGY.md for full pipeline)
```

## Project Structure

```
TabiyaESCO_Localization/
├── .env.example               # Environment template
├── countries/                 # Country implementations
│   ├── argentina_cno2017/     # Argentina CNO-2017 (national taxonomy)
│   ├── kenya_kesco/           # Kenya KESCO (national taxonomy)
│   ├── zambia/                # Zambia (NOS-based, no national taxonomy)
│   └── _template/             # Template for new countries
├── shared_data/               # Shared resources
│   ├── esco_taxonomy/         # English ESCO v2.0.1 (9-file format)
│   └── esco_taxonomy_es/      # Spanish ESCO
├── review_app/                # Human review tool (web-based)
└── docs/                      # Framework documentation
```

## Two Localization Approaches

### Approach 1: National Taxonomy Mapping (Kenya, Argentina)

For countries with an existing national occupational classification:

| Step | Description |
|------|-------------|
| Prepare data | Extract, clean, translate (if needed) |
| Generate embeddings | Gemini embeddings for national taxonomy |
| Semantic matching | ISCO-constrained + unconstrained matching |
| LLM validation | Binary validation + multi-candidate selection |
| Human review | Web-based review tool via Supabase |
| Skill assignment | Map skills to new local occupations |
| Taxonomy output | Generate Tabiya 9-file CSV format |

See [docs/LOCALIZATION_PIPELINE.md](docs/LOCALIZATION_PIPELINE.md) for details.

### Approach 2: NOS-based Adaptation (Zambia)

For countries without a national taxonomy, using National Occupational Standards:

| Step | Script | Description |
|------|--------|-------------|
| 01 | `01_extract_nos_skills.py` | Extract skill phrases from NOS PDFs |
| 02 | `02_match_occupations.py` | Embedding match occupations to ESCO |
| 03 | `03_validate_occupation_matches.py` | LLM validate occupation matches |
| 03b | `03b_finalize_new_occupations.py` | Descriptions + alt labels + ISCO codes for new occupations |
| 04 | `04_match_and_validate_tier1.py` | Knowledge matching (TK+RK) - embedding + LLM |
| 05 | `05_match_and_validate_tier2.py` | Skill matching (CS+PS) - embedding + LLM |
| 06 | `06_pc_gap_analysis.py` | Task-based skill gap analysis |
| 07 | `07_consolidate_skills.py` | Deduplicate and assemble all results |
| 08 | `08_finalize_skills.py` | Generate descriptions, place in hierarchy, map to occupations |
| 09 | `09_generate_taxonomy.py` | Generate Tabiya 9-file CSV output |

See [countries/zambia/docs/METHODOLOGY.md](countries/zambia/docs/METHODOLOGY.md) for details.

## Taxonomy Output Format

All localizations produce Tabiya 9-file CSV format:
- `occupations.csv`, `occupation_groups.csv`, `occupation_hierarchy.csv`
- `skills.csv`, `skill_groups.csv`, `skill_hierarchy.csv`
- `occupation_to_skill_relations.csv`, `skill_to_skill_relations.csv`
- `model_info.csv`

## Localizations

| Country | Source | Approach | Occupations | Skills | Status |
|---------|--------|----------|-------------|--------|--------|
| Argentina | CNO-2017 | National taxonomy | 5,690 | - | In Progress |
| Kenya | KESCO | National taxonomy | 5,917 (69 new local) | 3,964 new relations | Complete |
| Zambia | ZAQA NOS | NOS-based | 73 NOS (16 new local) | 683 new, 9,772 alt labels | Complete |

## Environment Variables

Set in `.env`:
```
GEMINI_API_KEY=your_key_here
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your_service_role_key
SUPABASE_ANON_KEY=your_anon_key
```

## Technologies

- **Python 3.11+**
- **Gemini API** for embeddings and LLM validation
- **pandas/numpy/scikit-learn** for data processing and similarity matching
- **pdfplumber** for PDF extraction (NOS-based approach)
- **Supabase** for review tool backend

## Documentation

- [docs/LOCALIZATION_PIPELINE.md](docs/LOCALIZATION_PIPELINE.md) - National taxonomy matching pipeline
- [docs/SKILL_DEFINITIONS_AND_CONTEXTUALIZATION.md](docs/SKILL_DEFINITIONS_AND_CONTEXTUALIZATION.md) - Skills vs tasks, ESCO phrasing conventions
- [docs/PROJECT_BRIEF.md](docs/PROJECT_BRIEF.md) - Vision and principles
- [docs/CODING_STANDARDS.md](docs/CODING_STANDARDS.md) - Development standards
- [docs/COUNTRY_ACTIVITY_LOG.md](docs/COUNTRY_ACTIVITY_LOG.md) - Cross-country updates

## License

Code: MIT License
Data outputs: CC BY 4.0
