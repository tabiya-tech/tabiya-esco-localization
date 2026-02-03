"""
Load ALL Kenya KESCO matches to Supabase for browsing/editing.

This uploads all 5,917 items (not just the 975 that needed human review),
allowing the full dataset to be searchable and editable in the review app.

Category to Decision mapping:
- exact, exact_upgraded, llm_approved -> APPROVE (auto-approved by pipeline)
- step_2b_matched -> MATCH (auto-matched by pipeline)
- human_approved -> APPROVE (human reviewed)
- human_matched -> MATCH (human reviewed)
- new_local -> NEW_LOCAL

When a user edits any item in the review app:
- decision is updated
- reviewer_name is set to the editor
- reviewed_at is updated
- This makes it "human reviewed"

Usage:
    python scripts/07_load_all_to_supabase.py
    python scripts/07_load_all_to_supabase.py --dry-run
"""

import json
import os
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client

BASE_PATH = Path(__file__).parent.parent
ROOT_PATH = BASE_PATH.parent.parent
MATCHES_FILE = BASE_PATH / 'outputs' / 'kenya_kesco_matches_final.json'

load_dotenv(ROOT_PATH / '.env')
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_SERVICE_KEY')


def category_to_decision(category: str) -> str:
    """Map pipeline category to review decision."""
    mapping = {
        'exact': 'APPROVE',
        'exact_upgraded': 'APPROVE',
        'llm_approved': 'APPROVE',
        'step_2b_matched': 'MATCH',
        'human_approved': 'APPROVE',
        'human_matched': 'MATCH',
        'new_local': 'NEW_LOCAL',
    }
    return mapping.get(category, 'APPROVE')


def is_human_reviewed(category: str) -> bool:
    """Check if category indicates human review."""
    return category in ('human_approved', 'human_matched', 'new_local')


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Load all matches to Supabase")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    args = parser.parse_args()

    print("=" * 60)
    print("LOAD ALL KENYA MATCHES TO SUPABASE")
    print("=" * 60)

    # Load matches
    print("\nLoading matches...")
    with open(MATCHES_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    matches = data['matches']
    print(f"  Total matches: {len(matches)}")

    # Connect to Supabase
    print("\nConnecting to Supabase...")
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Get Kenya project
    project = supabase.table("review_projects").select("*").eq("country_code", "KE").single().execute()
    project_id = project.data['id']
    print(f"  Project: {project.data['name']} (ID: {project_id})")

    # Get existing items
    print("\nChecking existing items...")
    existing = {}
    offset = 0
    while True:
        result = supabase.table("review_items").select("id, local_code").eq("project_id", project_id).range(offset, offset + 999).execute()
        if not result.data:
            break
        for item in result.data:
            existing[item['local_code']] = item['id']
        if len(result.data) < 1000:
            break
        offset += 1000
    print(f"  Existing items in Supabase: {len(existing)}")

    # Prepare items to insert/update
    to_insert = []
    to_update = []

    for match in matches:
        kesco_code = match['kesco_code']
        category = match.get('category', '')
        decision = category_to_decision(category)
        human_reviewed = is_human_reviewed(category)

        # Build the record
        record = {
            'project_id': project_id,
            'local_code': kesco_code,
            'local_label': match.get('kesco_title', ''),
            'isco_code': match.get('isco_code', ''),
            'suggested_esco_code': match.get('esco_code', ''),
            'suggested_esco_label': match.get('esco_label', ''),
            'decision': decision,
            'selected_esco_code': match.get('esco_code', ''),
            'selected_esco_label': match.get('esco_label', ''),
            'selected_parent_code': match.get('parent_esco_code') or match.get('parent_isco_code'),
            'selected_parent_label': match.get('parent_esco_label') or match.get('parent_isco_label'),
            'reviewer_name': match.get('reviewer', 'Pipeline') if human_reviewed else 'Pipeline',
            'reviewed_at': match.get('reviewed_at') if human_reviewed else datetime.now().isoformat(),
        }

        if kesco_code in existing:
            record['id'] = existing[kesco_code]
            to_update.append(record)
        else:
            to_insert.append(record)

    print(f"\n  To insert (new): {len(to_insert)}")
    print(f"  To update (existing): {len(to_update)}")

    if args.dry_run:
        print("\n[DRY RUN] Would insert/update items")

        # Show category breakdown
        from collections import Counter
        categories = Counter(m.get('category') for m in matches)
        print("\nCategory breakdown:")
        for cat, count in sorted(categories.items()):
            decision = category_to_decision(cat)
            print(f"  {cat}: {count} -> {decision}")
        return

    # Insert new items in batches
    if to_insert:
        print(f"\nInserting {len(to_insert)} new items...")
        batch_size = 100
        for i in range(0, len(to_insert), batch_size):
            batch = to_insert[i:i + batch_size]
            supabase.table("review_items").insert(batch).execute()
            print(f"  Inserted {min(i + batch_size, len(to_insert))}/{len(to_insert)}")

    # Update existing items in batches
    if to_update:
        print(f"\nUpdating {len(to_update)} existing items...")
        for i, record in enumerate(to_update):
            item_id = record.pop('id')
            supabase.table("review_items").update(record).eq('id', item_id).execute()
            if (i + 1) % 100 == 0:
                print(f"  Updated {i + 1}/{len(to_update)}")
        print(f"  Updated {len(to_update)}/{len(to_update)}")

    # Verify
    print("\nVerifying...")
    count = supabase.table("review_items").select("id", count="exact").eq("project_id", project_id).execute()
    print(f"  Total items in Supabase: {count.count}")

    print("\n" + "=" * 60)
    print("LOAD COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
