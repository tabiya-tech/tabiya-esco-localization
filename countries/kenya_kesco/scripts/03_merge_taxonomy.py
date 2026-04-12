"""
Merge Kenya KESCO matches into ESCO taxonomy.

Produces a localized occupations.csv by adding KESCO titles as alternative labels
to matched ESCO occupations.

Rules:
1. review_status = not_required:
   - exact, exact_upgraded: No changes (occupation exists in ESCO)
   - llm_approved, step_2b_matched: Add kesco_title as alt label

2. review_status = completed:
   - human_approved, human_matched: Add kesco_title as alt label

3. Skip (handled separately later):
   - new_local: Needs new occupation creation
   - pending: Not yet reviewed

Usage:
    python scripts/03_merge_taxonomy.py
    python scripts/03_merge_taxonomy.py --dry-run
"""

import json
import pandas as pd
from pathlib import Path
from collections import defaultdict

# Paths
BASE_PATH = Path(__file__).parent.parent
ROOT_PATH = BASE_PATH.parent.parent
ESCO_OCCUPATIONS = ROOT_PATH / 'shared_data' / 'esco_taxonomy' / 'occupations.csv'
MATCHES_FILE = BASE_PATH / 'outputs' / 'kenya_kesco_matches_final.json'
OUTPUT_DIR = BASE_PATH / 'outputs' / 'taxonomy'


def load_matches() -> list[dict]:
    """Load the final matches from JSON."""
    with open(MATCHES_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data['matches']


def get_alt_labels_to_add(matches: list[dict]) -> dict[str, list[str]]:
    """
    Determine which kesco_titles to add as alt labels for each esco_code.

    Returns dict of esco_code -> list of kesco_titles to add.
    """
    # Categories that should have alt labels added
    add_alt_label_categories = {
        'llm_approved',      # Not required review, LLM approved
        'step_2b_matched',   # Not required review, Step 2B matched
        'human_approved',    # Human approved the suggestion
        'human_matched',     # Human selected (possibly different) ESCO
    }

    # Skip categories (no alt label added)
    skip_categories = {
        'exact',           # Already exact match in ESCO
        'exact_upgraded',  # Already exact match (upgraded)
        'new_local',       # No ESCO equivalent
    }

    alt_labels_by_esco = defaultdict(list)

    stats = {
        'exact': 0,
        'exact_upgraded': 0,
        'llm_approved': 0,
        'step_2b_matched': 0,
        'human_approved': 0,
        'human_matched': 0,
        'new_local': 0,
        'pending': 0,
        'skipped_no_esco': 0,
    }

    for match in matches:
        category = match.get('category')
        review_status = match.get('review_status')
        esco_code = match.get('esco_code')
        kesco_title = match.get('kesco_title')

        # Skip pending items
        if review_status == 'pending':
            stats['pending'] += 1
            continue

        # Skip new_local
        if category == 'new_local':
            stats['new_local'] += 1
            continue

        # Skip exact matches (no alt label needed)
        if category in ('exact', 'exact_upgraded'):
            stats[category] += 1
            continue

        # Add alt label for these categories
        if category in add_alt_label_categories:
            if esco_code and str(esco_code) != 'nan' and kesco_title:
                alt_labels_by_esco[esco_code].append(kesco_title)
                stats[category] += 1
            else:
                stats['skipped_no_esco'] += 1

    print("=== ALT LABEL ASSIGNMENT STATS ===")
    print(f"  exact (no change): {stats['exact']}")
    print(f"  exact_upgraded (no change): {stats['exact_upgraded']}")
    print(f"  llm_approved (add alt label): {stats['llm_approved']}")
    print(f"  step_2b_matched (add alt label): {stats['step_2b_matched']}")
    print(f"  human_approved (add alt label): {stats['human_approved']}")
    print(f"  human_matched (add alt label): {stats['human_matched']}")
    print(f"  new_local (skip): {stats['new_local']}")
    print(f"  pending (skip): {stats['pending']}")
    if stats['skipped_no_esco'] > 0:
        print(f"  skipped (no esco_code): {stats['skipped_no_esco']}")

    total_alt_labels = sum(len(v) for v in alt_labels_by_esco.values())
    print(f"\nTotal alt labels to add: {total_alt_labels}")
    print(f"Unique ESCO codes affected: {len(alt_labels_by_esco)}")

    return dict(alt_labels_by_esco)


def merge_alt_labels(esco_df: pd.DataFrame, alt_labels_by_esco: dict[str, list[str]]) -> pd.DataFrame:
    """
    Merge new alt labels into the ESCO occupations dataframe.
    """
    df = esco_df.copy()

    updated_count = 0
    not_found = []

    for esco_code, new_labels in alt_labels_by_esco.items():
        # Find the row with this CODE
        mask = df['CODE'] == esco_code

        if not mask.any():
            not_found.append(esco_code)
            continue

        idx = df[mask].index[0]

        # Get existing alt labels
        existing = df.loc[idx, 'ALTLABELS']
        if pd.isna(existing):
            existing_set = set()
        else:
            existing_set = set(existing.split('\n'))

        # Add new labels (avoid duplicates)
        for label in new_labels:
            if label not in existing_set:
                existing_set.add(label)

        # Update the cell
        df.loc[idx, 'ALTLABELS'] = '\n'.join(sorted(existing_set))
        updated_count += 1

    print(f"\nESCO occupations updated: {updated_count}")
    if not_found:
        print(f"ESCO codes not found in base taxonomy: {len(not_found)}")
        for code in not_found[:5]:
            print(f"  {code}")
        if len(not_found) > 5:
            print(f"  ... and {len(not_found) - 5} more")

    return df


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Merge KESCO into ESCO taxonomy")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without saving")
    args = parser.parse_args()

    print("=" * 60)
    print("KENYA KESCO - TAXONOMY MERGE")
    print("=" * 60)

    # Load data
    print("\nLoading matches...")
    matches = load_matches()
    print(f"  Total matches: {len(matches)}")

    print("\nLoading ESCO occupations...")
    esco_df = pd.read_csv(ESCO_OCCUPATIONS)
    print(f"  Total ESCO occupations: {len(esco_df)}")

    # Determine alt labels to add
    print("\nAnalyzing matches...")
    alt_labels_by_esco = get_alt_labels_to_add(matches)

    # Merge
    print("\nMerging alt labels...")
    merged_df = merge_alt_labels(esco_df, alt_labels_by_esco)

    # Mark as localized only where alt labels were actually changed
    changed_codes = set(alt_labels_by_esco.keys())
    merged_df['ISLOCALIZED'] = merged_df['CODE'].isin(changed_codes)
    localized_count = merged_df['ISLOCALIZED'].sum()
    print(f"\nISLOCALIZED=True for {localized_count} occupations (out of {len(merged_df)})")

    if args.dry_run:
        print("\n[DRY RUN] Would save to:")
        print(f"  {OUTPUT_DIR / 'occupations.csv'}")
        return

    # Save
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / 'occupations.csv'
    merged_df.to_csv(output_file, index=False)
    print(f"\nSaved: {output_file}")

    print("\n" + "=" * 60)
    print("MERGE COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
