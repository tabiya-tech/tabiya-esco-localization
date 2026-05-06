"""
Load review items into Supabase for country projects.

Auto-discovers countries from countries/*/config.json files.
Checks which projects already exist in Supabase and prompts for selection.

Usage:
    python load_project_data.py
    python load_project_data.py --dry-run
"""

import json
import os
import math
from pathlib import Path
from supabase import create_client
from dotenv import load_dotenv

# Load env from project root
ROOT_DIR = Path(__file__).parent.parent.parent
load_dotenv(ROOT_DIR / '.env')

SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")

COUNTRIES_DIR = ROOT_DIR / 'countries'


def sanitize_value(v):
    """Convert NaN/inf floats to None, handle string 'nan'."""
    if v is None:
        return None
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
    if isinstance(v, str) and v.lower() == "nan":
        return None
    return v


def discover_countries():
    """Find all countries with config.json files."""
    countries = []

    for country_dir in COUNTRIES_DIR.iterdir():
        if not country_dir.is_dir():
            continue

        config_file = country_dir / 'config.json'
        if not config_file.exists():
            continue

        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)

        # Find review_items.json in outputs
        outputs_dir = country_dir / 'outputs'
        review_file = None
        if outputs_dir.exists():
            for f in outputs_dir.glob('*_review_items.json'):
                review_file = f
                break

        countries.append({
            'folder': country_dir.name,
            'config': config,
            'review_file': review_file,
            'has_review_items': review_file is not None and review_file.exists()
        })

    return countries


def get_existing_projects(supabase):
    """Get list of country codes already in Supabase."""
    result = supabase.table("review_projects").select("country_code, name, id").execute()
    return {p['country_code']: p for p in result.data}


def load_review_items(review_file: Path, config: dict):
    """Load review items from JSON file."""
    with open(review_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    code_field = config['local_code_field']
    label_field = config['local_label_field']
    label_en_field = config.get('local_label_en_field', label_field)

    items = []
    for m in data.get('items', []):
        items.append({
            'local_code': m.get(code_field),
            'local_label': m.get(label_field),
            'local_label_en': sanitize_value(m.get(label_en_field)),
            'isco_code': sanitize_value(m.get('isco_code')),
            'suggested_esco_code': sanitize_value(m.get('esco_code')),
            'suggested_esco_label': sanitize_value(m.get('esco_label')),
            'similarity': sanitize_value(m.get('similarity')),
            'sector': sanitize_value(m.get('sector')),
            'sub_sector': sanitize_value(m.get('sub_sector')),
        })

    return items


def load_country_to_supabase(supabase, country: dict, dry_run: bool = False):
    """Load a country's review items into Supabase."""
    config = country['config']
    review_file = country['review_file']

    print(f"\nLoading: {config['name']}")

    # Load items
    items = load_review_items(review_file, config)
    print(f"  Found {len(items)} review items")

    if dry_run:
        print("  [DRY RUN] Would upload to Supabase")
        return

    # Check if project exists
    existing = supabase.table("review_projects").select("id").eq("country_code", config['country_code']).execute()

    if existing.data:
        project_id = existing.data[0]['id']
        print(f"  Project exists (id={project_id})")

        # Check for existing items
        existing_items = supabase.table("review_items").select("id", count="exact").eq("project_id", project_id).execute()
        if existing_items.count > 0:
            print(f"  WARNING: Project already has {existing_items.count} items")
            response = input("  Overwrite? (y/N): ").strip().lower()
            if response != 'y':
                print("  Skipped")
                return
            # Delete existing items
            supabase.table("review_items").delete().eq("project_id", project_id).execute()
            print(f"  Deleted existing items")
    else:
        # Create project
        result = supabase.table("review_projects").insert({
            "name": config['name'],
            "country_code": config['country_code'],
            "source_taxonomy": config['source_taxonomy'],
            "description": config.get('description', '')
        }).execute()
        project_id = result.data[0]['id']
        print(f"  Created project (id={project_id})")

    # Add project_id to items
    for item in items:
        item['project_id'] = project_id

    # Insert in batches
    batch_size = 100
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        supabase.table("review_items").insert(batch).execute()
        print(f"  Uploaded {min(i + batch_size, len(items))}/{len(items)}")

    print(f"  Done!")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Load review items into Supabase")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be loaded without uploading")
    args = parser.parse_args()

    print("=" * 60)
    print("REVIEW APP - LOAD PROJECT DATA")
    print("=" * 60)

    # Discover countries
    print("\nDiscovering countries...")
    countries = discover_countries()

    if not countries:
        print("No countries found with config.json")
        return

    # Connect to Supabase
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    existing_projects = get_existing_projects(supabase)

    # Categorize countries
    ready = []      # Has review_items.json
    no_items = []   # No review_items.json yet

    print(f"\nFound {len(countries)} countries:\n")
    print(f"{'Folder':<25} {'Name':<25} {'Status':<20} {'Items'}")
    print("-" * 80)

    for c in countries:
        config = c['config']
        country_code = config['country_code']

        if country_code in existing_projects:
            status = "In Supabase"
        elif c['has_review_items']:
            status = "Ready to load"
            ready.append(c)
        else:
            status = "No review items"
            no_items.append(c)

        item_count = ""
        if c['has_review_items']:
            with open(c['review_file'], 'r', encoding='utf-8') as f:
                data = json.load(f)
                item_count = str(len(data.get('items', [])))

        print(f"{c['folder']:<25} {config['name']:<25} {status:<20} {item_count}")

    print()

    if not ready:
        if existing_projects:
            print("All countries with review items are already in Supabase.")
        else:
            print("No countries ready to load (run matching pipelines first).")
        return

    # Prompt for selection
    print(f"\n{len(ready)} country/countries ready to load:")
    for i, c in enumerate(ready, 1):
        print(f"  {i}. {c['config']['name']} ({c['folder']})")

    print(f"\nOptions:")
    print(f"  Enter numbers (e.g., '1' or '1,2') to load specific countries")
    print(f"  Enter 'all' to load all ready countries")
    print(f"  Enter 'q' to quit")

    response = input("\nYour choice: ").strip().lower()

    if response == 'q':
        print("Cancelled")
        return

    if response == 'all':
        to_load = ready
    else:
        try:
            indices = [int(x.strip()) - 1 for x in response.split(',')]
            to_load = [ready[i] for i in indices if 0 <= i < len(ready)]
        except (ValueError, IndexError):
            print("Invalid selection")
            return

    if not to_load:
        print("Nothing selected")
        return

    # Load selected countries
    for country in to_load:
        load_country_to_supabase(supabase, country, args.dry_run)

    print("\n" + "=" * 60)
    print("COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
