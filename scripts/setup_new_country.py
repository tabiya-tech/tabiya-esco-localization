"""
Set up a new country localization project.

Creates the folder structure, config.json, and template scripts
for a new country taxonomy mapping.

Usage:
    python scripts/setup_new_country.py
"""

import json
import os
import shutil
from pathlib import Path


ROOT_DIR = Path(__file__).parent.parent
COUNTRIES_DIR = ROOT_DIR / 'countries'
TEMPLATE_DIR = COUNTRIES_DIR / '_template'


def get_input(prompt: str, default: str = None) -> str:
    """Get user input with optional default."""
    if default:
        result = input(f"{prompt} [{default}]: ").strip()
        return result if result else default
    else:
        while True:
            result = input(f"{prompt}: ").strip()
            if result:
                return result
            print("  This field is required.")


def create_folder_structure(folder_path: Path) -> None:
    """Create the standard country folder structure."""
    folders = [
        folder_path / 'data',
        folder_path / 'scripts',
        folder_path / 'outputs',
        folder_path / 'docs'
    ]

    for folder in folders:
        folder.mkdir(parents=True, exist_ok=True)
        print(f"  Created: {folder.relative_to(ROOT_DIR)}")


def create_config(folder_path: Path, config: dict) -> None:
    """Create config.json file."""
    config_file = folder_path / 'config.json'

    with open(config_file, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    print(f"  Created: {config_file.relative_to(ROOT_DIR)}")


def create_readme(folder_path: Path, config: dict) -> None:
    """Create README.md from template."""
    readme_content = f"""# {config['name']} Localization

Mapping {config['description']} to Tabiya ESCO.

## Status

**In Progress** - Data preparation

## Source Data

- **Taxonomy**: {config['source_taxonomy']}
- **Language**: {config.get('language', 'TBD')}
- **Occupations**: TBD
- **ISCO Crosswalk**: TBD

## Prerequisites

1. Install dependencies: `pip install -r ../../requirements.txt`
2. Set up `.env` at project root with `GEMINI_API_KEY`
3. Ensure ESCO reference data is in `shared_data/`

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

## Data Files

```
data/
├── [source_files]           # Add your source taxonomy files here
└── {config['source_taxonomy'].lower()}_embeddings.json  # Generated embeddings

outputs/
├── *_matches_final.json     # All matches
├── *_matches_final.xlsx     # Excel version
├── *_review_items.json      # Items for human review
└── *_group_crosswalk.xlsx   # ISCO group mapping
```

## Results

| Category | Count | Percentage |
|----------|-------|------------|
| exact | - | -% |
| high_conf_unconstrained | - | -% |
| llm_approved | - | -% |
| new_local | - | -% |

## Notes

- [Add country-specific notes here]
"""

    readme_file = folder_path / 'README.md'
    with open(readme_file, 'w', encoding='utf-8') as f:
        f.write(readme_content)

    print(f"  Created: {readme_file.relative_to(ROOT_DIR)}")


def create_session_context(folder_path: Path, config: dict) -> None:
    """Create initial session context document."""
    content = f"""# Session Context: {config['name']}

## Current Status
- **Phase**: Data preparation
- **Last Updated**: [Date]

## What's Working
- Folder structure created
- Config.json set up

## What's Not Working / Blocked
- [Add blockers here]

## Next Steps
1. Add source taxonomy data to `data/`
2. Adapt pipeline scripts for this taxonomy's structure
3. Run the matching pipeline

## Key Decisions Made
- See DECISIONS_LOG.md for documented decisions

## Notes
- [Add any session notes here]
"""

    docs_dir = folder_path / 'docs'
    docs_dir.mkdir(exist_ok=True)

    with open(docs_dir / 'SESSION_CONTEXT.md', 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"  Created: docs/SESSION_CONTEXT.md")


def create_decisions_log(folder_path: Path, config: dict) -> None:
    """Create decisions log document."""
    content = f"""# Decisions Log: {config['name']}

Document key decisions made during the localization process.

---

## Decision #1: Initial Setup

**Date**: [Today's date]

**Context**: Starting {config['name']} localization project.

**Decision**: Using standard pipeline structure with Gemini embeddings.

**Rationale**: Consistent with Argentina and Kenya implementations.

**Impact**: Standard 3-step pipeline (prepare, embed, match).

---

[Add new decisions above this line]
"""

    docs_dir = folder_path / 'docs'

    with open(docs_dir / 'DECISIONS_LOG.md', 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"  Created: docs/DECISIONS_LOG.md")


def create_template_scripts(folder_path: Path, config: dict) -> None:
    """Create template pipeline scripts."""
    scripts_dir = folder_path / 'scripts'

    taxonomy = config['source_taxonomy'].lower().replace('-', '_').replace(' ', '_')
    code_field = config['local_code_field']
    label_field = config['local_label_field']

    # 00_prepare_data.py
    prepare_script = f'''"""
Prepare {config['source_taxonomy']} data for the matching pipeline.

This script should:
1. Load and clean source taxonomy data
2. Build group hierarchy context
3. Create ISCO crosswalk (if applicable)

Input: data/[source_files]
Output: data/{taxonomy}_prepared.xlsx

Customize this script for your taxonomy's specific format.
"""

import pandas as pd
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / 'data'
OUTPUT_DIR = BASE_DIR / 'outputs'


def main():
    print("=" * 60)
    print("PREPARE {config['source_taxonomy'].upper()} DATA")
    print("=" * 60)

    # TODO: Implement data preparation
    # 1. Load source files
    # 2. Clean and normalize data
    # 3. Build group hierarchy (if applicable)
    # 4. Create ISCO crosswalk (if applicable)
    # 5. Save prepared data

    print("\\nNot implemented yet. Customize this script for your taxonomy.")


if __name__ == "__main__":
    main()
'''

    # 01_generate_embeddings.py
    embeddings_script = f'''"""
Generate {config['source_taxonomy']} embeddings using Gemini.

Creates embeddings for all occupation titles using Google's Gemini embedding model.
These will be used for semantic matching against ESCO embeddings.

Input: data/{taxonomy}_prepared.xlsx
Output: data/{taxonomy}_embeddings.json

Usage:
    python scripts/01_generate_embeddings.py
"""

import pandas as pd
import json
import os
import time
from pathlib import Path
from tqdm import tqdm
import google.generativeai as genai
from dotenv import load_dotenv

# Paths
BASE_DIR = Path(__file__).parent.parent
ROOT_DIR = BASE_DIR.parent.parent
load_dotenv(ROOT_DIR / '.env')

INPUT_FILE = BASE_DIR / 'data' / '{taxonomy}_prepared.xlsx'
OUTPUT_FILE = BASE_DIR / 'data' / '{taxonomy}_embeddings.json'

# Model configuration
MODEL_NAME = 'models/gemini-embedding-001'
BATCH_SIZE = 100
TASK_TYPE = 'SEMANTIC_SIMILARITY'
OUTPUT_DIMENSIONALITY = 768


def configure_gemini():
    """Configure Gemini API."""
    api_key = os.environ.get('GOOGLE_API_KEY') or os.environ.get('GEMINI_API_KEY')
    if not api_key:
        raise ValueError("GOOGLE_API_KEY or GEMINI_API_KEY not set in .env")
    genai.configure(api_key=api_key)
    print("  Gemini API configured")


def load_data() -> pd.DataFrame:
    """Load prepared taxonomy data."""
    print(f"\\n[1/3] Loading data from {{INPUT_FILE}}...")

    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"Input file not found: {{INPUT_FILE}}")

    df = pd.read_excel(INPUT_FILE)
    print(f"  Loaded {{len(df)}} occupations")
    return df


def generate_embeddings(df: pd.DataFrame) -> list:
    """Generate embeddings for all occupations."""
    print(f"\\n[2/3] Generating embeddings...")

    # TODO: Customize for your taxonomy's fields
    texts = df['{label_field}'].tolist()
    codes = df['{code_field}'].tolist()

    all_embeddings = []
    num_batches = (len(texts) + BATCH_SIZE - 1) // BATCH_SIZE

    for i in tqdm(range(0, len(texts), BATCH_SIZE), total=num_batches, desc="  Embedding"):
        batch_texts = texts[i:i + BATCH_SIZE]

        max_retries = 5
        for attempt in range(max_retries):
            try:
                result = genai.embed_content(
                    model=MODEL_NAME,
                    content=batch_texts,
                    task_type=TASK_TYPE,
                    output_dimensionality=OUTPUT_DIMENSIONALITY
                )
                all_embeddings.extend(result['embedding'])
                break
            except Exception as e:
                if '429' in str(e) or 'quota' in str(e).lower():
                    wait_time = 45 * (attempt + 1)
                    print(f"\\n  Rate limit, waiting {{wait_time}}s...")
                    time.sleep(wait_time)
                else:
                    raise

        time.sleep(1.5)  # Rate limit delay

    # Build output structure
    items = []
    for i, (code, label, emb) in enumerate(zip(codes, texts, all_embeddings)):
        items.append({{
            '{code_field}': str(code),
            '{label_field}': str(label),
            'embedding': emb
        }})

    return items


def save_embeddings(items: list) -> None:
    """Save embeddings to JSON file."""
    print(f"\\n[3/3] Saving to {{OUTPUT_FILE}}...")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    data = {{
        'metadata': {{
            'model': MODEL_NAME,
            'source': '{config["source_taxonomy"]}',
            'num_occupations': len(items),
            'embedding_dim': len(items[0]['embedding']),
            'date_generated': pd.Timestamp.now().isoformat()
        }},
        'occupations': items
    }}

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    file_size_mb = OUTPUT_FILE.stat().st_size / (1024 * 1024)
    print(f"  Saved {{len(items)}} embeddings ({{file_size_mb:.1f}} MB)")


def main():
    print("=" * 60)
    print("GENERATE {config['source_taxonomy'].upper()} EMBEDDINGS")
    print("=" * 60)

    configure_gemini()
    df = load_data()
    items = generate_embeddings(df)
    save_embeddings(items)

    print("\\n" + "=" * 60)
    print("EMBEDDINGS COMPLETE")
    print("=" * 60)


if __name__ == '__main__':
    main()
'''

    # 02_run_matching.py
    matching_script = f'''"""
Run the matching pipeline for {config['source_taxonomy']}.

Matches local taxonomy to ESCO using:
1. ISCO-constrained semantic matching
2. LLM validation for uncertain matches

Input:
  - data/{taxonomy}_embeddings.json
  - shared_data/esco_embeddings_en_gemini.json (or es for Spanish)

Output:
  - outputs/*_matches_final.json
  - outputs/*_matches_final.xlsx
  - outputs/*_review_items.json
  - outputs/*_review_items.xlsx

Usage:
    python scripts/02_run_matching.py
"""

import pandas as pd
import json
import numpy as np
from pathlib import Path
from tqdm import tqdm
from datetime import datetime

# Paths
BASE_DIR = Path(__file__).parent.parent
ROOT_DIR = BASE_DIR.parent.parent

# Input files
LOCAL_EMBEDDINGS = BASE_DIR / 'data' / '{taxonomy}_embeddings.json'
# Change to esco_embeddings_es_gemini.json for Spanish taxonomies
ESCO_EMBEDDINGS = ROOT_DIR / 'shared_data' / 'esco_embeddings_en_gemini.json'

# Output files
OUTPUT_DIR = BASE_DIR / 'outputs'
PREFIX = '{config["country_code"].lower()}_{taxonomy}'
OUTPUT_MATCHES_JSON = OUTPUT_DIR / f'{{PREFIX}}_matches_final.json'
OUTPUT_MATCHES_EXCEL = OUTPUT_DIR / f'{{PREFIX}}_matches_final.xlsx'
OUTPUT_REVIEW_JSON = OUTPUT_DIR / f'{{PREFIX}}_review_items.json'
OUTPUT_REVIEW_EXCEL = OUTPUT_DIR / f'{{PREFIX}}_review_items.xlsx'

# Matching thresholds
HIGH_CONFIDENCE_THRESHOLD = 0.85
REVIEW_THRESHOLD = 0.70


def load_embeddings():
    """Load local and ESCO embeddings."""
    print("\\n[1/4] Loading embeddings...")

    with open(LOCAL_EMBEDDINGS, 'r', encoding='utf-8') as f:
        local_data = json.load(f)
    print(f"  Local: {{len(local_data['occupations'])}} occupations")

    with open(ESCO_EMBEDDINGS, 'r', encoding='utf-8') as f:
        esco_data = json.load(f)
    print(f"  ESCO: {{len(esco_data['embeddings'])}} occupations")

    return local_data, esco_data


def cosine_similarity(a, b):
    """Compute cosine similarity between two vectors."""
    a = np.array(a)
    b = np.array(b)
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))


def run_matching(local_data, esco_data):
    """Run semantic matching."""
    print("\\n[2/4] Running matching...")

    matches = []
    review_items = []

    # Build ESCO lookup
    esco_codes = list(esco_data['embeddings'].keys())
    esco_embeddings = [esco_data['embeddings'][c] for c in esco_codes]

    # TODO: Load ESCO labels from taxonomy files
    # esco_labels = {{}}  # Load from shared_data/esco_taxonomy/occupations.csv

    for occ in tqdm(local_data['occupations'], desc="  Matching"):
        local_code = occ['{code_field}']
        local_label = occ['{label_field}']
        local_emb = occ['embedding']

        # Find best ESCO match
        best_sim = 0
        best_esco = None

        for esco_code, esco_emb in zip(esco_codes, esco_embeddings):
            sim = cosine_similarity(local_emb, esco_emb)
            if sim > best_sim:
                best_sim = sim
                best_esco = esco_code

        # Categorize
        if best_sim >= HIGH_CONFIDENCE_THRESHOLD:
            category = 'high_confidence'
        elif best_sim >= REVIEW_THRESHOLD:
            category = 'needs_review'
            review_items.append({{
                '{code_field}': local_code,
                '{label_field}': local_label,
                'esco_code': best_esco,
                'similarity': round(best_sim, 4)
            }})
        else:
            category = 'new_local'
            review_items.append({{
                '{code_field}': local_code,
                '{label_field}': local_label,
                'esco_code': None,
                'similarity': round(best_sim, 4)
            }})

        matches.append({{
            '{code_field}': local_code,
            '{label_field}': local_label,
            'esco_code': best_esco,
            'similarity': round(best_sim, 4),
            'category': category
        }})

    return matches, review_items


def save_outputs(matches, review_items):
    """Save match results and review items."""
    print("\\n[3/4] Saving outputs...")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Save matches
    matches_data = {{
        'metadata': {{
            'generated_at': datetime.now().isoformat(),
            'total_matches': len(matches)
        }},
        'matches': matches
    }}

    with open(OUTPUT_MATCHES_JSON, 'w', encoding='utf-8') as f:
        json.dump(matches_data, f, ensure_ascii=False, indent=2)
    print(f"  Saved: {{OUTPUT_MATCHES_JSON.name}}")

    pd.DataFrame(matches).to_excel(OUTPUT_MATCHES_EXCEL, index=False)
    print(f"  Saved: {{OUTPUT_MATCHES_EXCEL.name}}")

    # Save review items
    review_data = {{
        'metadata': {{
            'generated_at': datetime.now().isoformat(),
            'total_items': len(review_items)
        }},
        'items': review_items
    }}

    with open(OUTPUT_REVIEW_JSON, 'w', encoding='utf-8') as f:
        json.dump(review_data, f, ensure_ascii=False, indent=2)
    print(f"  Saved: {{OUTPUT_REVIEW_JSON.name}}")

    pd.DataFrame(review_items).to_excel(OUTPUT_REVIEW_EXCEL, index=False)
    print(f"  Saved: {{OUTPUT_REVIEW_EXCEL.name}}")


def print_summary(matches, review_items):
    """Print matching summary."""
    print("\\n[4/4] Summary")
    print("=" * 40)

    categories = {{}}
    for m in matches:
        cat = m['category']
        categories[cat] = categories.get(cat, 0) + 1

    for cat, count in sorted(categories.items()):
        pct = 100 * count / len(matches)
        print(f"  {{cat}}: {{count}} ({{pct:.1f}}%)")

    print(f"\\n  Review items: {{len(review_items)}}")
    print("=" * 40)


def main():
    print("=" * 60)
    print("RUN {config['source_taxonomy'].upper()} MATCHING")
    print("=" * 60)

    local_data, esco_data = load_embeddings()
    matches, review_items = run_matching(local_data, esco_data)
    save_outputs(matches, review_items)
    print_summary(matches, review_items)

    print("\\n" + "=" * 60)
    print("MATCHING COMPLETE")
    print("=" * 60)


if __name__ == '__main__':
    main()
'''

    # Write scripts
    with open(scripts_dir / '00_prepare_data.py', 'w', encoding='utf-8') as f:
        f.write(prepare_script)
    print(f"  Created: scripts/00_prepare_data.py")

    with open(scripts_dir / '01_generate_embeddings.py', 'w', encoding='utf-8') as f:
        f.write(embeddings_script)
    print(f"  Created: scripts/01_generate_embeddings.py")

    with open(scripts_dir / '02_run_matching.py', 'w', encoding='utf-8') as f:
        f.write(matching_script)
    print(f"  Created: scripts/02_run_matching.py")


def main():
    print("=" * 60)
    print("NEW COUNTRY SETUP")
    print("=" * 60)
    print("\nThis script creates the folder structure and template files")
    print("for a new country localization project.\n")

    # Gather information
    print("-" * 40)
    print("COUNTRY INFORMATION")
    print("-" * 40)

    country_name = get_input("Country name (e.g., 'Kenya')")
    country_code = get_input("Country code (e.g., 'KE')")
    taxonomy_name = get_input("Taxonomy name (e.g., 'KESCO')")
    taxonomy_desc = get_input(
        "Full taxonomy description",
        f"{country_name} Standard Classification of Occupations"
    )
    language = get_input("Primary language", "English")

    print("\n" + "-" * 40)
    print("DATA FIELDS")
    print("-" * 40)
    print("These are the column names in your source data:\n")

    code_field = get_input("Code field name (e.g., 'kesco_code')")
    label_field = get_input("Label field name (e.g., 'occupation_title')")
    label_en_field = get_input("English label field", label_field)

    # Build config
    config = {
        "name": f"{country_name} {taxonomy_name}",
        "country_code": country_code.upper(),
        "source_taxonomy": taxonomy_name,
        "description": taxonomy_desc,
        "language": language,
        "local_code_field": code_field,
        "local_label_field": label_field,
        "local_label_en_field": label_en_field
    }

    # Generate folder name
    folder_name = f"{country_name.lower()}_{taxonomy_name.lower()}"
    folder_name = folder_name.replace(' ', '_').replace('-', '_')
    folder_path = COUNTRIES_DIR / folder_name

    print("\n" + "-" * 40)
    print("CONFIRMATION")
    print("-" * 40)
    print(f"\nWill create: countries/{folder_name}/")
    print(f"\nConfig:")
    print(json.dumps(config, indent=2))

    confirm = input("\nProceed? (y/N): ").strip().lower()
    if confirm != 'y':
        print("Cancelled.")
        return

    # Check if folder exists
    if folder_path.exists():
        print(f"\nERROR: Folder already exists: {folder_path}")
        overwrite = input("Overwrite? (y/N): ").strip().lower()
        if overwrite != 'y':
            print("Cancelled.")
            return
        shutil.rmtree(folder_path)

    # Create everything
    print("\n" + "-" * 40)
    print("CREATING PROJECT")
    print("-" * 40)

    create_folder_structure(folder_path)
    create_config(folder_path, config)
    create_readme(folder_path, config)
    create_session_context(folder_path, config)
    create_decisions_log(folder_path, config)
    create_template_scripts(folder_path, config)

    # Summary
    print("\n" + "=" * 60)
    print("SETUP COMPLETE")
    print("=" * 60)
    print(f"\nCreated: countries/{folder_name}/")
    print("\nNext steps:")
    print("  1. Add source taxonomy files to data/")
    print("  2. Customize 00_prepare_data.py for your data format")
    print("  3. Run the pipeline scripts in order")
    print("  4. Load review items: python review_app/scripts/load_project_data.py")
    print("\nSee the README.md in the new folder for details.")
    print("=" * 60)


if __name__ == "__main__":
    main()
