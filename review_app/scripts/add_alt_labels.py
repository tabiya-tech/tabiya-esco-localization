"""
Add alt_labels to occupations in Supabase.

Reads ALTLABELS from the ESCO CSV and updates the Supabase occupations table.

Usage:
    python add_alt_labels.py
    python add_alt_labels.py --dry-run
"""

import os
from pathlib import Path
import pandas as pd
from supabase import create_client
from dotenv import load_dotenv

# Load env from project root
ROOT_DIR = Path(__file__).parent.parent.parent
load_dotenv(ROOT_DIR / '.env')

SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")

ESCO_CSV = ROOT_DIR / 'shared_data' / 'esco_taxonomy' / 'occupations.csv'


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Add alt_labels to Supabase occupations")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be updated without making changes")
    args = parser.parse_args()

    print("=" * 60)
    print("ADD ALT LABELS TO SUPABASE")
    print("=" * 60)

    # Load CSV
    print(f"\nLoading {ESCO_CSV}...")
    df = pd.read_csv(ESCO_CSV)
    print(f"  Found {len(df)} occupations in CSV")

    # Connect to Supabase
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Get existing occupations from Supabase
    print("\nFetching occupations from Supabase...")
    all_occs = []
    offset = 0
    page_size = 1000
    while True:
        result = supabase.table("occupations").select("id, code").range(offset, offset + page_size - 1).execute()
        if not result.data:
            break
        all_occs.extend(result.data)
        if len(result.data) < page_size:
            break
        offset += page_size

    print(f"  Found {len(all_occs)} occupations in Supabase")

    # Build code -> id map
    code_to_id = {o['code']: o['id'] for o in all_occs}

    # Prepare updates
    updates = []
    for _, row in df.iterrows():
        code = str(row['CODE'])
        alt_labels_raw = row.get('ALTLABELS', '')

        if pd.isna(alt_labels_raw) or not alt_labels_raw:
            continue

        if code not in code_to_id:
            continue

        # Convert newline-separated string to array
        alt_labels_list = [s.strip() for s in str(alt_labels_raw).split('\n') if s.strip()]

        updates.append({
            'id': code_to_id[code],
            'code': code,
            'alt_labels': alt_labels_list
        })

    print(f"\n{len(updates)} occupations have alt labels to add")

    if args.dry_run:
        print("\n[DRY RUN] Would update the following:")
        for u in updates[:5]:
            labels_preview = ', '.join(u['alt_labels'][:3])
            if len(u['alt_labels']) > 3:
                labels_preview += f" ... ({len(u['alt_labels'])} total)"
            print(f"  {u['code']}: [{labels_preview}]")
        if len(updates) > 5:
            print(f"  ... and {len(updates) - 5} more")
        return

    # Update in batches
    print("\nUpdating Supabase...")
    batch_size = 100
    for i in range(0, len(updates), batch_size):
        batch = updates[i:i + batch_size]
        for u in batch:
            supabase.table("occupations").update({
                'alt_labels': u['alt_labels']
            }).eq('id', u['id']).execute()
        print(f"  Updated {min(i + batch_size, len(updates))}/{len(updates)}")

    print("\nDone!")


if __name__ == "__main__":
    main()
