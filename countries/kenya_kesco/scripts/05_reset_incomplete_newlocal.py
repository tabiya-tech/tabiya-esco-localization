"""
Reset incomplete NEW_LOCAL items to review queue in Supabase.

For NEW_LOCAL items that are missing parent_isco_code:
1. Reset their decision to NULL in Supabase
2. They'll reappear in the review queue for proper parent selection

Usage:
    python scripts/05_reset_incomplete_newlocal.py
    python scripts/05_reset_incomplete_newlocal.py --dry-run
"""

import json
import os
import pandas as pd
from pathlib import Path
from supabase import create_client
from dotenv import load_dotenv

# Paths
BASE_PATH = Path(__file__).parent.parent
ROOT_PATH = BASE_PATH.parent.parent
EXCEL_FILE = BASE_PATH / 'outputs' / 'kenya_kesco_matches_final.xlsx'
JSON_FILE = BASE_PATH / 'outputs' / 'kenya_kesco_matches_final.json'

# Load env
load_dotenv(ROOT_PATH / '.env')
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_SERVICE_KEY')


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Reset incomplete NEW_LOCAL items to review queue")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without saving")
    args = parser.parse_args()

    print("=" * 60)
    print("RESET INCOMPLETE NEW_LOCAL TO REVIEW QUEUE")
    print("=" * 60)

    # Load Excel
    print("\nLoading Excel file...")
    excel_df = pd.read_excel(EXCEL_FILE, sheet_name='Data')

    # Find NEW_LOCAL without parent codes
    new_local = excel_df[
        (excel_df['category'] == 'new_local') &
        (excel_df['review_status'] == 'completed')
    ]

    incomplete = new_local[
        new_local['parent_esco_code'].isna() |
        (new_local['parent_esco_code'].astype(str).str.strip() == '')
    ]

    print(f"  Total NEW_LOCAL with completed review: {len(new_local)}")
    print(f"  Incomplete (no parent code): {len(incomplete)}")

    if len(incomplete) == 0:
        print("\nNo incomplete NEW_LOCAL items to reset.")
        return

    # Get kesco_codes to reset
    kesco_codes = incomplete['kesco_code'].tolist()
    print(f"\nItems to reset:")
    for code in kesco_codes[:10]:
        title = incomplete[incomplete['kesco_code'] == code]['kesco_title'].values[0]
        print(f"  {code}: {title[:50]}...")
    if len(kesco_codes) > 10:
        print(f"  ... and {len(kesco_codes) - 10} more")

    if args.dry_run:
        print("\n[DRY RUN] Would reset these items in Supabase")
        return

    # Connect to Supabase
    print("\nConnecting to Supabase...")
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Get Kenya project
    project = supabase.table("review_projects").select("*").eq("country_code", "KE").single().execute()
    project_id = project.data['id']
    print(f"  Project: {project.data['name']} (ID: {project_id})")

    # Reset each item
    print("\nResetting items...")
    reset_count = 0
    not_found = []

    for kesco_code in kesco_codes:
        # Find the review item
        result = supabase.table("review_items").select("id").eq("project_id", project_id).eq("local_code", kesco_code).execute()

        if not result.data:
            not_found.append(kesco_code)
            continue

        item_id = result.data[0]['id']

        # Reset decision to NULL
        supabase.table("review_items").update({
            'decision': None,
            'selected_parent_code': None,
            'selected_parent_label': None
        }).eq('id', item_id).execute()

        reset_count += 1

    print(f"\n=== RESULTS ===")
    print(f"  Reset in Supabase: {reset_count}")
    if not_found:
        print(f"  Not found in Supabase: {len(not_found)}")
        for code in not_found[:5]:
            print(f"    {code}")

    # Also update JSON file
    print("\nUpdating JSON file...")
    with open(JSON_FILE, 'r', encoding='utf-8') as f:
        json_data = json.load(f)

    matches_by_code = {m['kesco_code']: m for m in json_data['matches']}

    for kesco_code in kesco_codes:
        if kesco_code in matches_by_code:
            match = matches_by_code[kesco_code]
            # Reset review status to pending
            match['review_status'] = 'pending'
            # Remove review decision if present
            if 'review_decision' in match:
                del match['review_decision']

    with open(JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    print(f"  Saved: {JSON_FILE.name}")

    print("\n" + "=" * 60)
    print("RESET COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
