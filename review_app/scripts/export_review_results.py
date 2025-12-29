"""
Export review results from Supabase back to country outputs.

Auto-discovers countries and shows review progress.
Merges human decisions into matches_final files.

Usage:
    python export_review_results.py
    python export_review_results.py --dry-run
"""

import json
import os
from datetime import datetime
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

COUNTRIES_DIR = ROOT_DIR / 'countries'


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

        # Find matches_final.json in outputs
        outputs_dir = country_dir / 'outputs'
        matches_file = None
        if outputs_dir.exists():
            for f in outputs_dir.glob('*_matches_final.json'):
                matches_file = f
                break

        countries.append({
            'folder': country_dir.name,
            'path': country_dir,
            'config': config,
            'matches_file': matches_file,
            'outputs_dir': outputs_dir
        })

    return countries


def get_supabase_projects(supabase):
    """Get all projects from Supabase with review progress."""
    # Get projects
    projects_result = supabase.table("review_projects").select("*").execute()
    projects = {p['country_code']: p for p in projects_result.data}

    # Get review progress for each project
    for country_code, project in projects.items():
        project_id = project['id']

        # Total items
        total = supabase.table("review_items").select("id", count="exact").eq("project_id", project_id).execute()
        project['total_items'] = total.count

        # Reviewed items
        reviewed = supabase.table("review_items").select("id", count="exact").eq("project_id", project_id).neq("decision", None).execute()
        project['reviewed_items'] = reviewed.count

        # By decision type
        for decision in ['MATCH', 'NEW_LOCAL', 'SKIP']:
            result = supabase.table("review_items").select("id", count="exact").eq("project_id", project_id).eq("decision", decision).execute()
            project[f'decision_{decision.lower()}'] = result.count

    return projects


def export_country(supabase, country: dict, supabase_project: dict, dry_run: bool = False):
    """Export reviewed items back to country outputs."""
    config = country['config']
    matches_file = country['matches_file']
    outputs_dir = country['outputs_dir']

    print(f"\nExporting: {config['name']}")

    if not matches_file or not matches_file.exists():
        print(f"  ERROR: No matches_final.json found")
        return

    # Load existing matches
    with open(matches_file, 'r', encoding='utf-8') as f:
        matches_data = json.load(f)

    matches = matches_data.get('matches', [])
    code_field = config['local_code_field']

    # Build lookup by local code
    matches_by_code = {m.get(code_field): m for m in matches}

    # Get reviewed items from Supabase
    project_id = supabase_project['id']
    result = supabase.table("review_items").select("*").eq("project_id", project_id).not_.is_("decision", "null").execute()
    reviewed_items = result.data

    print(f"  Found {len(reviewed_items)} reviewed items in Supabase")

    # Track changes
    stats = {
        'matched': 0,
        'new_local': 0,
        'skipped': 0,
        'not_found': 0,
        'esco_changed': 0
    }

    # Apply decisions
    for item in reviewed_items:
        local_code = item['local_code']
        decision = item['decision']

        if local_code not in matches_by_code:
            stats['not_found'] += 1
            continue

        match = matches_by_code[local_code]
        original_esco = match.get('esco_code')

        if decision == 'MATCH':
            # Update to selected ESCO
            if item.get('selected_esco_code'):
                match['esco_code'] = item['selected_esco_code']
                match['esco_label'] = item.get('selected_esco_label', '')
                if item['selected_esco_code'] != original_esco:
                    stats['esco_changed'] += 1
            match['category'] = 'human_matched'
            match['review_decision'] = 'MATCH'
            stats['matched'] += 1

        elif decision == 'NEW_LOCAL':
            # Confirm as new local, optionally with parent
            match['category'] = 'new_local'
            match['review_decision'] = 'NEW_LOCAL'
            if item.get('selected_parent_code'):
                match['parent_esco_code'] = item['selected_parent_code']
                match['parent_esco_label'] = item.get('selected_parent_label', '')
            stats['new_local'] += 1

        elif decision == 'SKIP':
            match['category'] = 'skipped'
            match['review_decision'] = 'SKIP'
            stats['skipped'] += 1

        # Add review metadata
        match['reviewer'] = item.get('reviewer_name')
        match['reviewed_at'] = item.get('reviewed_at')
        if item.get('notes'):
            match['review_notes'] = item['notes']

    print(f"  Changes:")
    print(f"    MATCH: {stats['matched']} ({stats['esco_changed']} ESCO changed)")
    print(f"    NEW_LOCAL: {stats['new_local']}")
    print(f"    SKIP: {stats['skipped']}")
    if stats['not_found'] > 0:
        print(f"    Not found in matches: {stats['not_found']}")

    if dry_run:
        print("  [DRY RUN] Would save to files")
        return

    # Update metadata
    matches_data['metadata']['review_exported_at'] = datetime.now().isoformat()
    matches_data['metadata']['review_stats'] = stats

    # Save JSON
    with open(matches_file, 'w', encoding='utf-8') as f:
        json.dump(matches_data, f, ensure_ascii=False, indent=2)
    print(f"  Saved: {matches_file.name}")

    # Regenerate Excel
    excel_file = matches_file.with_suffix('.xlsx')
    excel_data = []
    for m in matches:
        row = {
            code_field: m.get(code_field),
            'esco_code': m.get('esco_code', ''),
            'esco_label': m.get('esco_label', ''),
            'similarity': m.get('similarity', 0),
            'category': m.get('category', ''),
            'review_decision': m.get('review_decision', '')
        }
        # Add local label field
        label_field = config['local_label_field']
        row[label_field] = m.get(label_field, '')
        excel_data.append(row)

    df = pd.DataFrame(excel_data)
    df.to_excel(excel_file, index=False)
    print(f"  Saved: {excel_file.name}")

    print("  Done!")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Export review results from Supabase")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be exported without saving")
    args = parser.parse_args()

    print("=" * 60)
    print("REVIEW APP - EXPORT RESULTS")
    print("=" * 60)

    # Discover countries
    print("\nDiscovering countries...")
    countries = discover_countries()
    countries_by_code = {c['config']['country_code']: c for c in countries}

    # Connect to Supabase
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    supabase_projects = get_supabase_projects(supabase)

    if not supabase_projects:
        print("No projects found in Supabase")
        return

    # Show status
    print(f"\nProjects in Supabase:\n")
    print(f"{'Name':<25} {'Total':<8} {'Reviewed':<10} {'Progress':<10} {'MATCH':<8} {'NEW':<8} {'SKIP'}")
    print("-" * 85)

    exportable = []
    for country_code, project in supabase_projects.items():
        total = project['total_items']
        reviewed = project['reviewed_items']
        progress = f"{100*reviewed/total:.0f}%" if total > 0 else "0%"

        print(f"{project['name']:<25} {total:<8} {reviewed:<10} {progress:<10} "
              f"{project['decision_match']:<8} {project['decision_new_local']:<8} {project['decision_skip']}")

        if reviewed > 0 and country_code in countries_by_code:
            exportable.append({
                'country': countries_by_code[country_code],
                'project': project
            })

    print()

    if not exportable:
        print("No projects with reviewed items to export.")
        return

    # Prompt for selection
    print(f"\n{len(exportable)} project(s) with reviewed items:")
    for i, e in enumerate(exportable, 1):
        proj = e['project']
        print(f"  {i}. {proj['name']} ({proj['reviewed_items']}/{proj['total_items']} reviewed)")

    print(f"\nOptions:")
    print(f"  Enter numbers (e.g., '1' or '1,2') to export specific projects")
    print(f"  Enter 'all' to export all")
    print(f"  Enter 'q' to quit")

    response = input("\nYour choice: ").strip().lower()

    if response == 'q':
        print("Cancelled")
        return

    if response == 'all':
        to_export = exportable
    else:
        try:
            indices = [int(x.strip()) - 1 for x in response.split(',')]
            to_export = [exportable[i] for i in indices if 0 <= i < len(exportable)]
        except (ValueError, IndexError):
            print("Invalid selection")
            return

    if not to_export:
        print("Nothing selected")
        return

    # Export selected
    for e in to_export:
        export_country(supabase, e['country'], e['project'], args.dry_run)

    print("\n" + "=" * 60)
    print("EXPORT COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
