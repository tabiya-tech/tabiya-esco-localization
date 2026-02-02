"""
Export review results from Supabase back to country outputs.

Auto-discovers countries and shows review progress.
Merges human decisions into matches_final files.

Usage:
    python export_review_results.py              # Interactive mode
    python export_review_results.py --country KE # Export specific country (non-interactive)
    python export_review_results.py --dry-run    # Show what would be exported
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
        for decision in ['APPROVE', 'MATCH', 'NEW_LOCAL', 'SKIP']:
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

    # Get ALL review items from Supabase (to know what was sent to review)
    project_id = supabase_project['id']
    all_review_items = supabase.table("review_items").select("*").eq("project_id", project_id).execute()
    all_review_data = all_review_items.data

    # Build set of codes sent to review
    sent_to_review = {item['local_code'] for item in all_review_data}

    # Filter to only reviewed items (have a decision)
    reviewed_items = [item for item in all_review_data if item.get('decision')]

    print(f"  Found {len(sent_to_review)} items sent to review, {len(reviewed_items)} with decisions")

    # Track changes
    stats = {
        'approved': 0,
        'matched': 0,
        'new_local': 0,
        'skipped': 0,
        'not_found': 0,
        'esco_changed': 0
    }

    # Apply decisions (SKIP items are excluded - they stay in review queue)
    for item in reviewed_items:
        local_code = item['local_code']
        decision = item['decision']

        # Skip items marked SKIP - they remain pending in review queue
        if decision == 'SKIP':
            stats['skipped'] += 1
            continue

        if local_code not in matches_by_code:
            stats['not_found'] += 1
            continue

        match = matches_by_code[local_code]
        original_esco = match.get('esco_code')

        if decision == 'APPROVE':
            # Approve pipeline's suggestion as-is
            if item.get('selected_esco_code'):
                match['esco_code'] = item['selected_esco_code']
                match['esco_label'] = item.get('selected_esco_label', '')
            match['category'] = 'human_approved'
            match['review_decision'] = 'APPROVE'
            stats['approved'] += 1

        elif decision == 'MATCH':
            # Human selected different ESCO
            if item.get('selected_esco_code'):
                match['esco_code'] = item['selected_esco_code']
                match['esco_label'] = item.get('selected_esco_label', '')
                if item['selected_esco_code'] != original_esco:
                    stats['esco_changed'] += 1
            match['category'] = 'human_matched'
            match['review_decision'] = 'MATCH'
            stats['matched'] += 1

        elif decision == 'NEW_LOCAL':
            # Confirm as new local with parent for skill inheritance
            match['category'] = 'new_local'
            match['review_decision'] = 'NEW_LOCAL'
            if item.get('selected_parent_code'):
                match['parent_esco_code'] = item['selected_parent_code']
                match['parent_esco_label'] = item.get('selected_parent_label', '')
            stats['new_local'] += 1

        # Add review metadata
        match['reviewer'] = item.get('reviewer_name')
        match['reviewed_at'] = item.get('reviewed_at')
        if item.get('notes'):
            match['review_notes'] = item['notes']

    # Add review_status to all matches
    status_counts = {'not_required': 0, 'pending': 0, 'completed': 0}
    for match in matches:
        local_code = match.get(code_field)
        if local_code in sent_to_review:
            if match.get('review_decision'):
                match['review_status'] = 'completed'
                status_counts['completed'] += 1
            else:
                match['review_status'] = 'pending'
                status_counts['pending'] += 1
        else:
            match['review_status'] = 'not_required'
            status_counts['not_required'] += 1

    print(f"  Changes:")
    print(f"    APPROVE: {stats['approved']}")
    print(f"    MATCH: {stats['matched']} ({stats['esco_changed']} ESCO changed)")
    print(f"    NEW_LOCAL: {stats['new_local']}")
    print(f"    SKIP: {stats['skipped']} (excluded from export)")
    if stats['not_found'] > 0:
        print(f"    Not found in matches: {stats['not_found']}")
    print(f"  Review status:")
    print(f"    not_required: {status_counts['not_required']}")
    print(f"    pending: {status_counts['pending']}")
    print(f"    completed: {status_counts['completed']}")

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

    # Regenerate Excel (exclude internal pipeline fields)
    excel_file = matches_file.with_suffix('.xlsx')
    df = pd.DataFrame(matches)

    # Remove internal pipeline fields from Excel output
    columns_to_remove = [
        'similarity', 'search_strategy', 'upgraded',
        'crosswalk_mismatch', 'original_esco_code', 'original_esco_label',
        'original_similarity'
    ]
    df = df.drop(columns=[c for c in columns_to_remove if c in df.columns], errors='ignore')

    # Ensure parent columns exist for manual editing of NEW_LOCAL items
    if 'parent_esco_code' not in df.columns:
        df['parent_esco_code'] = None
    if 'parent_esco_label' not in df.columns:
        df['parent_esco_label'] = None
    if 'review_notes' not in df.columns:
        df['review_notes'] = None

    # Create README sheet with column descriptions
    readme_data = [
        {'Column': 'kesco_code', 'Description': 'Local occupation code'},
        {'Column': 'kesco_title', 'Description': 'Local occupation title'},
        {'Column': 'isco_code', 'Description': 'ISCO-08 code from source taxonomy'},
        {'Column': 'unit_group', 'Description': 'ISCO unit group used for matching'},
        {'Column': 'esco_code', 'Description': 'Matched ESCO occupation code'},
        {'Column': 'esco_label', 'Description': 'ESCO occupation label'},
        {'Column': 'matched_label', 'Description': 'ESCO alt-label that matched'},
        {'Column': 'category', 'Description': 'Match category: exact, llm_approved, exact_upgraded, step_2b_matched, human_approved, human_matched, new_local'},
        {'Column': 'llm_decision', 'Description': 'Step 2A LLM result: AUTO_APPROVED (>95%), APPROVE, REJECT'},
        {'Column': 'step_2b_reason', 'Description': 'Why sent to Step 2B: rejected (by 2A) or low_similarity (<90%)'},
        {'Column': 'step_2b_decision', 'Description': 'Step 2B LLM result: SELECT (picked ESCO) or NONE (new_local)'},
        {'Column': 'review_status', 'Description': 'Review status: not_required (auto-approved), pending (awaiting review), completed (reviewed)'},
        {'Column': 'review_decision', 'Description': 'Human review: APPROVE (accept suggestion), MATCH (different ESCO), NEW_LOCAL'},
        {'Column': 'reviewer', 'Description': 'Name of human reviewer'},
        {'Column': 'reviewed_at', 'Description': 'Timestamp of human review'},
        {'Column': 'parent_esco_code', 'Description': 'For NEW_LOCAL: parent ESCO code for skill inheritance'},
        {'Column': 'parent_esco_label', 'Description': 'For NEW_LOCAL: parent ESCO label'},
        {'Column': 'review_notes', 'Description': 'Optional notes from reviewer'},
    ]
    readme_df = pd.DataFrame(readme_data)

    # Write both sheets
    with pd.ExcelWriter(excel_file, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Data', index=False)
        readme_df.to_excel(writer, sheet_name='README', index=False)

    print(f"  Saved: {excel_file.name} ({len(df.columns)} columns, 2 sheets)")

    print("  Done!")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Export review results from Supabase")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be exported without saving")
    parser.add_argument("--country", type=str, help="Country code to export (e.g., KE, AR). Skips interactive prompt.")
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
    print(f"{'Name':<25} {'Total':<8} {'Reviewed':<10} {'Progress':<10} {'APPRV':<7} {'MATCH':<7} {'NEW':<7} {'SKIP'}")
    print("-" * 90)

    exportable = []
    for country_code, project in supabase_projects.items():
        total = project['total_items']
        reviewed = project['reviewed_items']
        progress = f"{100*reviewed/total:.0f}%" if total > 0 else "0%"

        print(f"{project['name']:<25} {total:<8} {reviewed:<10} {progress:<10} "
              f"{project.get('decision_approve', 0):<7} {project.get('decision_match', 0):<7} "
              f"{project.get('decision_new_local', 0):<7} {project.get('decision_skip', 0)}")

        if reviewed > 0 and country_code in countries_by_code:
            exportable.append({
                'country': countries_by_code[country_code],
                'project': project
            })

    print()

    if not exportable:
        print("No projects with reviewed items to export.")
        return

    # Non-interactive mode: export specific country
    if args.country:
        country_code = args.country.upper()
        to_export = [e for e in exportable if e['project']['country_code'] == country_code]
        if not to_export:
            print(f"ERROR: Country '{country_code}' not found or has no reviewed items.")
            print(f"Available: {', '.join(e['project']['country_code'] for e in exportable)}")
            return
    else:
        # Interactive mode: prompt for selection
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
