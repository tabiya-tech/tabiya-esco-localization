"""
Sync incremental edits from Supabase to local files.

This script:
1. Pulls current state from Supabase
2. Compares with local matches_final.json
3. Updates only changed items (preserves unchanged)
4. Regenerates matches_final.xlsx
5. Updates new_local_working.xlsx (adds/removes items, preserves preferred_labels)
6. Runs taxonomy merge (03_merge_taxonomy.py)

Usage:
    python scripts/04_sync_from_supabase.py
    python scripts/04_sync_from_supabase.py --dry-run
"""

import os
import json
import pandas as pd
from pathlib import Path
from datetime import datetime
from collections import Counter
from dotenv import load_dotenv
from supabase import create_client

BASE_PATH = Path(__file__).parent.parent
ROOT_PATH = BASE_PATH.parent.parent
MATCHES_JSON = BASE_PATH / 'outputs' / 'kenya_kesco_matches_final.json'
MATCHES_XLSX = BASE_PATH / 'outputs' / 'kenya_kesco_matches_final.xlsx'
NEW_LOCAL_XLSX = BASE_PATH / 'outputs' / 'new_local_working.xlsx'

load_dotenv(ROOT_PATH / '.env')
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_SERVICE_KEY')


def fetch_supabase_items() -> dict[str, dict]:
    """Fetch all items from Supabase, return as dict by local_code."""
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    project = supabase.table("review_projects").select("*").eq("country_code", "KE").single().execute()
    project_id = project.data['id']

    all_items = []
    offset = 0
    while True:
        result = supabase.table("review_items").select("*").eq("project_id", project_id).range(offset, offset + 999).execute()
        if not result.data:
            break
        all_items.extend(result.data)
        if len(result.data) < 1000:
            break
        offset += 1000

    return {item['local_code']: item for item in all_items}


def decision_to_category(decision: str) -> str:
    """Map Supabase decision to match category."""
    if decision == 'NEW_LOCAL':
        return 'new_local'
    elif decision == 'MATCH':
        return 'human_matched'
    else:
        return 'human_approved'


def sync_matches(supabase_lookup: dict, dry_run: bool = False) -> tuple[list, list, list]:
    """
    Sync Supabase changes to matches_final.json.
    Returns (changed_items, new_to_newlocal, removed_from_newlocal).
    """
    with open(MATCHES_JSON, 'r', encoding='utf-8') as f:
        data = json.load(f)
    matches = data['matches']

    changed = []
    new_to_newlocal = []
    removed_from_newlocal = []

    for match in matches:
        kesco_code = match['kesco_code']
        if kesco_code not in supabase_lookup:
            continue

        sb = supabase_lookup[kesco_code]
        sb_reviewer = sb.get('reviewer_name', 'Pipeline')

        # Skip Pipeline items - no human edits
        if sb_reviewer == 'Pipeline':
            continue

        sb_decision = sb.get('decision')
        current_cat = match.get('category')
        new_cat = decision_to_category(sb_decision)

        current_is_newlocal = current_cat == 'new_local'
        new_is_newlocal = new_cat == 'new_local'

        # Check if changed
        if current_cat != new_cat:
            changed.append({
                'kesco_code': kesco_code,
                'kesco_title': match.get('kesco_title'),
                'old_cat': current_cat,
                'new_cat': new_cat,
                'reviewer': sb_reviewer
            })

            if not dry_run:
                # Update match
                match['category'] = new_cat
                match['reviewer'] = sb_reviewer
                match['reviewed_at'] = sb.get('reviewed_at')
                match['review_status'] = 'completed'

                if not new_is_newlocal:
                    match['esco_code'] = sb.get('selected_esco_code', match.get('esco_code'))
                    match['esco_label'] = sb.get('selected_esco_label', match.get('esco_label'))

                if new_is_newlocal:
                    match['parent_esco_code'] = sb.get('selected_parent_code')
                    match['parent_esco_label'] = sb.get('selected_parent_label')

            if new_is_newlocal and not current_is_newlocal:
                new_to_newlocal.append(kesco_code)
            elif current_is_newlocal and not new_is_newlocal:
                removed_from_newlocal.append(kesco_code)

    if not dry_run and changed:
        data['metadata']['last_updated'] = datetime.now().isoformat()
        data['metadata']['supabase_sync'] = datetime.now().isoformat()
        with open(MATCHES_JSON, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    return changed, new_to_newlocal, removed_from_newlocal


def regenerate_matches_xlsx():
    """Regenerate the matches Excel file from JSON."""
    with open(MATCHES_JSON, 'r', encoding='utf-8') as f:
        data = json.load(f)
    matches = data['matches']

    df = pd.DataFrame(matches)
    cols_order = [
        'kesco_code', 'kesco_title', 'isco_code', 'unit_group',
        'category', 'review_status', 'reviewer', 'reviewed_at',
        'esco_code', 'esco_label', 'matched_label', 'similarity',
        'parent_esco_code', 'parent_esco_label',
        'search_strategy', 'upgraded', 'crosswalk_mismatch',
        'original_esco_code', 'original_esco_label', 'original_similarity',
        'llm_decision'
    ]
    cols = [c for c in cols_order if c in df.columns]
    df = df[cols]

    try:
        with pd.ExcelWriter(MATCHES_XLSX, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Matches', index=False)
            readme = pd.DataFrame({
                'Field': cols,
                'Description': [
                    'KESCO occupation code', 'KESCO occupation title', 'ISCO-08 code',
                    'ISCO-08 unit group', 'Match category', 'Review status',
                    'Reviewer name', 'Review timestamp', 'Matched ESCO code',
                    'Matched ESCO label', 'Label matched', 'Similarity score',
                    'Parent ESCO code (NEW_LOCAL)', 'Parent ESCO label (NEW_LOCAL)',
                    'Search strategy', 'Upgraded flag', 'Crosswalk mismatch',
                    'Original ESCO code', 'Original ESCO label', 'Original similarity',
                    'LLM decision'
                ][:len(cols)]
            })
            readme.to_excel(writer, sheet_name='README', index=False)
        return len(df), None
    except PermissionError:
        return len(df), 'File is open - close kenya_kesco_matches_final.xlsx and re-run'


def update_new_local_working(new_to_newlocal: list, removed_from_newlocal: list, dry_run: bool = False) -> dict:
    """
    Update new_local_working.xlsx:
    - Add items newly tagged as NEW_LOCAL
    - Remove items no longer NEW_LOCAL
    - Preserve preferred_labels on unchanged items
    """
    # Load current matches for NEW_LOCAL data
    with open(MATCHES_JSON, 'r', encoding='utf-8') as f:
        data = json.load(f)
    matches = data['matches']
    new_locals = [m for m in matches if m.get('category') == 'new_local']
    new_local_codes = set(m['kesco_code'] for m in new_locals)
    matches_by_code = {m['kesco_code']: m for m in matches}

    # Load existing working doc if it exists
    existing_work = {}
    existing_codes = set()
    if NEW_LOCAL_XLSX.exists():
        try:
            existing_df = pd.read_excel(NEW_LOCAL_XLSX, sheet_name='NEW_LOCAL')
            existing_codes = set(existing_df['kesco_code'])
            for _, row in existing_df.iterrows():
                if pd.notna(row.get('preferred_label')) and str(row['preferred_label']).strip():
                    existing_work[row['kesco_code']] = str(row['preferred_label']).strip()
        except Exception:
            pass

    # Build new dataframe
    rows = []
    for m in new_locals:
        kesco_code = m['kesco_code']
        rows.append({
            'kesco_code': kesco_code,
            'kesco_title': m.get('kesco_title'),
            'parent_esco_code': m.get('parent_esco_code') or m.get('parent_isco_code'),
            'parent_esco_label': m.get('parent_esco_label') or m.get('parent_isco_label'),
            'preferred_label': existing_work.get(kesco_code, ''),
        })

    df = pd.DataFrame(rows)
    df = df.sort_values(['parent_esco_code', 'kesco_title'])

    stats = {
        'total': len(df),
        'preserved_labels': len(existing_work),
        'added': list(new_local_codes - existing_codes),
        'removed': list(existing_codes - new_local_codes),
        'with_labels': int(df['preferred_label'].astype(bool).sum()) if len(df) > 0 else 0
    }

    if not dry_run:
        try:
            with pd.ExcelWriter(NEW_LOCAL_XLSX, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='NEW_LOCAL', index=False)
                instructions = pd.DataFrame({'Instructions': [
                    'Fill in preferred_label for each item.',
                    '',
                    'CONSOLIDATION RULES:',
                    '- Items with the SAME preferred_label become one occupation',
                    '- The preferred_label becomes the PREFERREDLABEL',
                    '- All kesco_titles with that label become ALTLABELS',
                    '',
                    'Items left blank will each become their own occupation.',
                ]})
                instructions.to_excel(writer, sheet_name='Instructions', index=False)
        except PermissionError:
            stats['error'] = 'File is open - close new_local_working.xlsx and re-run'

    return stats


def run_merge_taxonomy():
    """Run the taxonomy merge script."""
    import subprocess
    script_path = BASE_PATH / 'scripts' / '03_merge_taxonomy.py'
    result = subprocess.run(['python', str(script_path)], capture_output=True, text=True)
    return result.returncode == 0, result.stdout, result.stderr


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Sync edits from Supabase")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without applying")
    args = parser.parse_args()

    print("=" * 60)
    print("SYNC FROM SUPABASE")
    print("=" * 60)

    # Fetch from Supabase
    print("\n[1/5] Fetching from Supabase...")
    supabase_lookup = fetch_supabase_items()
    print(f"  Fetched {len(supabase_lookup)} items")

    # Sync matches
    print("\n[2/5] Syncing matches...")
    changed, new_to_newlocal, removed_from_newlocal = sync_matches(supabase_lookup, args.dry_run)

    if not changed:
        print("  No changes detected")
    else:
        print(f"  Changed: {len(changed)} items")
        for c in changed:
            print(f"    {c['kesco_code']}: {c['old_cat']} -> {c['new_cat']} ({c['reviewer']})")
        if new_to_newlocal:
            print(f"  Newly NEW_LOCAL: {new_to_newlocal}")
        if removed_from_newlocal:
            print(f"  No longer NEW_LOCAL: {removed_from_newlocal}")

    if args.dry_run:
        print("\n[DRY RUN] Would update files")
        return

    # Regenerate Excel
    print("\n[3/5] Regenerating matches Excel...")
    rows, xlsx_error = regenerate_matches_xlsx()
    if xlsx_error:
        print(f"  WARNING: {xlsx_error}")
    else:
        print(f"  Saved {MATCHES_XLSX.name} ({rows} rows)")

    # Update NEW_LOCAL working doc
    print("\n[4/5] Updating NEW_LOCAL working doc...")
    stats = update_new_local_working(new_to_newlocal, removed_from_newlocal, args.dry_run)
    if stats.get('error'):
        print(f"  WARNING: {stats['error']}")
    else:
        print(f"  Total: {stats['total']} items")
        print(f"  With preferred_label: {stats['with_labels']}")
        if stats['added']:
            print(f"  Added: {stats['added']}")
        if stats['removed']:
            print(f"  Removed: {stats['removed']}")

    # Run taxonomy merge
    print("\n[5/5] Running taxonomy merge...")
    success, stdout, stderr = run_merge_taxonomy()
    if success:
        # Extract key stats from output
        for line in stdout.split('\n'):
            if 'alt labels to add' in line.lower() or 'esco occupations updated' in line.lower():
                print(f"  {line.strip()}")
        print("  Merge complete")
    else:
        print(f"  ERROR: {stderr}")

    # Summary
    print("\n" + "=" * 60)
    print("SYNC COMPLETE")
    print("=" * 60)

    # Show category breakdown
    with open(MATCHES_JSON, 'r', encoding='utf-8') as f:
        data = json.load(f)
    categories = Counter(m.get('category') for m in data['matches'])
    print("\nCategory breakdown:")
    for cat, count in sorted(categories.items()):
        print(f"  {cat}: {count}")


if __name__ == "__main__":
    main()
