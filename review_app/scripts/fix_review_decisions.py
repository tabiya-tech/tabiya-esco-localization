"""
Fix review decisions in Supabase:
1. MATCH -> APPROVE where selected_esco_code == suggested_esco_code
2. Report NEW_LOCAL items missing parent codes

Usage:
    python fix_review_decisions.py --dry-run    # Preview changes
    python fix_review_decisions.py              # Apply changes
"""

import os
from supabase import create_client
from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent.parent
load_dotenv(ROOT_DIR / '.env')

SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")


def fix_decisions(dry_run: bool = False):
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Get all projects
    projects = supabase.table('review_projects').select('*').execute()

    for project in projects.data:
        project_id = project['id']
        print(f"\n{'='*60}")
        print(f"Project: {project['name']} ({project['country_code']})")
        print('='*60)

        # Get all reviewed items
        result = supabase.table('review_items').select('*').eq('project_id', project_id).not_.is_('decision', 'null').execute()
        items = result.data

        print(f"Total reviewed items: {len(items)}")

        # === FIX 1: MATCH -> APPROVE ===
        match_items = [i for i in items if i['decision'] == 'MATCH']

        # Items where selected ESCO == suggested ESCO (should be APPROVE)
        should_be_approve = []
        for item in match_items:
            if item.get('selected_esco_code') and item.get('suggested_esco_code'):
                if item['selected_esco_code'] == item['suggested_esco_code']:
                    should_be_approve.append(item)

        print(f"\n--- MATCH -> APPROVE Fix ---")
        print(f"Total MATCH decisions: {len(match_items)}")
        print(f"Should be APPROVE (selected == suggested): {len(should_be_approve)}")
        print(f"True MATCH (selected != suggested): {len(match_items) - len(should_be_approve)}")

        if should_be_approve:
            if dry_run:
                print(f"[DRY RUN] Would update {len(should_be_approve)} items to APPROVE")
            else:
                # Update in batches
                for item in should_be_approve:
                    supabase.table('review_items').update({
                        'decision': 'APPROVE'
                    }).eq('id', item['id']).execute()
                print(f"Updated {len(should_be_approve)} items to APPROVE")

        # === FIX 2: NEW_LOCAL without parent ===
        new_local_items = [i for i in items if i['decision'] == 'NEW_LOCAL']
        missing_parent = [i for i in new_local_items if not i.get('selected_parent_code')]
        has_parent = [i for i in new_local_items if i.get('selected_parent_code')]

        print(f"\n--- NEW_LOCAL Parent Check ---")
        print(f"Total NEW_LOCAL decisions: {len(new_local_items)}")
        print(f"With parent code: {len(has_parent)}")
        print(f"Missing parent code: {len(missing_parent)}")

        if missing_parent:
            print(f"\nNEW_LOCAL items missing parent (need re-review):")
            for item in missing_parent[:10]:  # Show first 10
                print(f"  {item['local_code']}: {item['local_label'][:50]}...")
            if len(missing_parent) > 10:
                print(f"  ... and {len(missing_parent) - 10} more")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Fix review decisions in Supabase")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without applying")
    args = parser.parse_args()

    print("="*60)
    print("FIX REVIEW DECISIONS")
    print("="*60)

    fix_decisions(dry_run=args.dry_run)

    print("\n" + "="*60)
    print("COMPLETE")
    print("="*60)


if __name__ == "__main__":
    main()
