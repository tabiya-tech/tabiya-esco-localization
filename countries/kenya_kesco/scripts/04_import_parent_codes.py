"""
Import parent ISCO unit group codes from Excel back to JSON.

For NEW_LOCAL items where parent_esco_code was manually added in Excel:
1. Read the parent codes from Excel (these are ISCO unit group codes like 1114, 1112)
2. Look up the ISCO group label from the occupation_groups taxonomy
3. Update the JSON file

Usage:
    python scripts/04_import_parent_codes.py
    python scripts/04_import_parent_codes.py --dry-run
"""

import json
import pandas as pd
from pathlib import Path

# Paths
BASE_PATH = Path(__file__).parent.parent
ROOT_PATH = BASE_PATH.parent.parent
ISCO_GROUPS = ROOT_PATH / 'shared_data' / 'esco_taxonomy' / 'occupation_groups.csv'
EXCEL_FILE = BASE_PATH / 'outputs' / 'kenya_kesco_matches_final.xlsx'
JSON_FILE = BASE_PATH / 'outputs' / 'kenya_kesco_matches_final.json'


def load_isco_group_labels() -> dict[str, str]:
    """Load ISCO group code -> label mapping."""
    df = pd.read_csv(ISCO_GROUPS)
    # CODE is string like "1114", PREFERREDLABEL is the English label
    return dict(zip(df['CODE'].astype(str), df['PREFERREDLABEL']))


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Import parent codes from Excel to JSON")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without saving")
    args = parser.parse_args()

    print("=" * 60)
    print("IMPORT PARENT ISCO CODES FROM EXCEL")
    print("=" * 60)

    # Load ISCO group labels
    print("\nLoading ISCO groups...")
    isco_labels = load_isco_group_labels()
    print(f"  Loaded {len(isco_labels)} ISCO groups")

    # Load Excel
    print("\nLoading Excel file...")
    excel_df = pd.read_excel(EXCEL_FILE, sheet_name='Data')
    print(f"  Total rows: {len(excel_df)}")

    # Filter to NEW_LOCAL with parent codes
    new_local = excel_df[
        (excel_df['category'] == 'new_local') &
        (excel_df['review_status'] == 'completed') &
        (excel_df['parent_esco_code'].notna()) &
        (excel_df['parent_esco_code'].astype(str).str.strip() != '')
    ]
    print(f"  NEW_LOCAL with parent codes: {len(new_local)}")

    # Load JSON
    print("\nLoading JSON file...")
    with open(JSON_FILE, 'r', encoding='utf-8') as f:
        json_data = json.load(f)
    matches = json_data['matches']
    matches_by_code = {m['kesco_code']: m for m in matches}

    # Track updates
    updated = 0
    not_found_in_json = []
    not_found_in_isco = []

    print("\nProcessing parent codes...")
    for _, row in new_local.iterrows():
        kesco_code = row['kesco_code']
        parent_code = str(row['parent_esco_code']).strip()

        # Handle float codes (e.g., 1114.0 -> 1114)
        if '.' in parent_code:
            parent_code = parent_code.split('.')[0]

        if kesco_code not in matches_by_code:
            not_found_in_json.append(kesco_code)
            continue

        # Look up parent label from ISCO groups
        parent_label = isco_labels.get(parent_code)
        if not parent_label:
            not_found_in_isco.append((kesco_code, parent_code))
            continue

        # Update match - rename fields to be clearer about ISCO vs ESCO
        match = matches_by_code[kesco_code]
        match['parent_isco_code'] = parent_code
        match['parent_isco_label'] = parent_label
        updated += 1

    print(f"\n=== RESULTS ===")
    print(f"  Updated: {updated}")
    if not_found_in_json:
        print(f"  Not found in JSON: {len(not_found_in_json)}")
        for code in not_found_in_json[:5]:
            print(f"    {code}")
    if not_found_in_isco:
        print(f"  Parent code not in ISCO groups: {len(not_found_in_isco)}")
        for kesco, parent in not_found_in_isco[:5]:
            print(f"    {kesco} -> {parent}")

    if args.dry_run:
        print("\n[DRY RUN] Would save to JSON file")
        return

    # Save JSON
    with open(JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {JSON_FILE.name}")

    print("\n" + "=" * 60)
    print("IMPORT COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
