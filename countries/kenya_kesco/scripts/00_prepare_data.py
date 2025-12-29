"""
Prepare KeSCO Data

1. Joins raw KeSCO occupational titles with group labels to create
   the enriched occupation file with full hierarchy context.
2. Builds KeSCO-to-ISCO group crosswalk for constraining semantic matching.

Input:
    - data/KeSCO_occupational_titles.xlsx (raw occupations)
    - data/KeSCO_groups.xlsx (group labels)
    - shared_data/esco_taxonomy/occupation_groups.csv (ISCO groups)

Output:
    - data/KeSCO_occupations_with_context.xlsx
    - outputs/isco_kesco_group_lookup.xlsx

Usage:
    python scripts/00_prepare_data.py
"""

import pandas as pd
from pathlib import Path
from difflib import SequenceMatcher

# Paths
BASE_PATH = Path(__file__).parent.parent
ROOT_PATH = BASE_PATH.parent.parent
DATA_PATH = BASE_PATH / 'data'
OUTPUT_PATH = BASE_PATH / 'outputs'

TITLES_FILE = DATA_PATH / 'KeSCO_occupational_titles.xlsx'
GROUPS_FILE = DATA_PATH / 'KeSCO_groups.xlsx'
ISCO_GROUPS_FILE = ROOT_PATH / 'shared_data' / 'esco_taxonomy' / 'occupation_groups.csv'

CONTEXT_OUTPUT = DATA_PATH / 'KeSCO_occupations_with_context.xlsx'
CROSSWALK_REVIEW_OUTPUT = OUTPUT_PATH / 'kenya_kesco_groups_needs_review.xlsx'
CROSSWALK_FINAL_OUTPUT = OUTPUT_PATH / 'kenya_kesco_group_crosswalk.xlsx'


def load_kesco_groups() -> dict:
    """Load KeSCO groups into lookup dictionary."""
    print(f"Loading KeSCO groups from {GROUPS_FILE}...")

    df = pd.read_excel(GROUPS_FILE)
    print(f"  Loaded {len(df)} group entries")

    groups = {}
    for _, row in df.iterrows():
        code = str(row['KESCO_group_code']).replace('.0', '')
        label = str(row['KESCO_group_label']).strip()
        groups[code] = label

    return groups


def load_isco_groups() -> pd.DataFrame:
    """Load ISCO groups from ESCO taxonomy."""
    print(f"Loading ISCO groups from {ISCO_GROUPS_FILE}...")

    df = pd.read_csv(ISCO_GROUPS_FILE)
    print(f"  Loaded {len(df)} ISCO groups")

    result = df[['CODE', 'PREFERREDLABEL']].copy()
    result.columns = ['code', 'label']
    result['code'] = result['code'].astype(str)

    return result


def extract_group_codes(kesco_code: str) -> dict:
    """
    Extract group codes from KeSCO occupation code.

    KeSCO code format: XXXX-YY where XXXX is the unit group (ISCO-aligned)
    """
    if '-' in kesco_code:
        group_part = kesco_code.split('-')[0]
    else:
        group_part = kesco_code[:4]

    group_part = group_part.zfill(4)

    return {
        'unit_group_code': group_part,
        'minor_group_code': group_part[:3],
        'sub_major_group_code': group_part[:2],
        'major_group_code': group_part[:1]
    }


def build_occupations_with_context(kesco_groups: dict) -> None:
    """Build occupation file with full group context."""
    print(f"\n{'='*70}")
    print("STEP 1: BUILD OCCUPATIONS WITH CONTEXT")
    print('='*70)

    print(f"\nLoading occupational titles from {TITLES_FILE}...")
    df = pd.read_excel(TITLES_FILE)
    print(f"  Loaded {len(df)} occupations")

    df = df.rename(columns={
        'KeSCO CODE': 'kesco_code',
        'Occupational titles': 'occupational_title'
    })

    print("Building context for each occupation...")
    results = []
    for _, row in df.iterrows():
        kesco_code = str(row['kesco_code']).strip()
        title = str(row['occupational_title']).strip()
        codes = extract_group_codes(kesco_code)

        results.append({
            'kesco_code': kesco_code,
            'occupational_title': title,
            'unit_group_code': codes['unit_group_code'],
            'unit_group_label': kesco_groups.get(codes['unit_group_code'], ''),
            'minor_group_code': codes['minor_group_code'],
            'minor_group_label': kesco_groups.get(codes['minor_group_code'], ''),
            'sub_major_group_code': codes['sub_major_group_code'],
            'sub_major_group_label': kesco_groups.get(codes['sub_major_group_code'], ''),
            'major_group_code': codes['major_group_code'],
            'major_group_label': kesco_groups.get(codes['major_group_code'], '')
        })

    output_df = pd.DataFrame(results)

    missing_unit = output_df[output_df['unit_group_label'] == '']
    if len(missing_unit) > 0:
        print(f"  Warning: {len(missing_unit)} occupations missing unit group labels")

    print(f"\nSaving to {CONTEXT_OUTPUT}...")
    output_df.to_excel(CONTEXT_OUTPUT, index=False)
    print(f"  Saved {len(output_df)} occupations with context")


def label_similarity(label1: str, label2: str) -> float:
    """Calculate similarity between two labels."""
    if not label1 or not label2:
        return 0.0
    return SequenceMatcher(None, label1.lower(), label2.lower()).ratio()


def build_group_crosswalk(kesco_groups: dict, isco_groups: pd.DataFrame) -> None:
    """
    Build crosswalk between KeSCO and ISCO groups.

    Matching logic:
      Step 1: Code AND label must match at unit level (4-digit) -> code_exact
      Step 2: Labels match completely at unit level -> label_exact
      Step 3: Labels nearly match (>=75% similarity) -> label_similar
      Step 4: Everything else -> needs_review
    """
    print(f"\n{'='*70}")
    print("STEP 2: BUILD GROUP CROSSWALK")
    print('='*70)

    # Get unit groups only (4-digit codes)
    unit_groups = [(code, label) for code, label in kesco_groups.items() if len(code) == 4]
    print(f"\nProcessing {len(unit_groups)} KeSCO unit groups...")

    # Build ISCO lookups (unit level = 4-digit only)
    isco_unit_groups = isco_groups[isco_groups['code'].str.len() == 4].copy()
    isco_by_code = {row['code']: row['label'] for _, row in isco_unit_groups.iterrows()}
    isco_by_label = {row['label'].lower(): (row['code'], row['label']) for _, row in isco_unit_groups.iterrows()}
    isco_labels_list = [(row['code'], row['label']) for _, row in isco_unit_groups.iterrows()]

    print(f"  ISCO unit groups available: {len(isco_by_code)}")

    results = []
    for kesco_code, kesco_label in unit_groups:
        match_result = {
            'kesco_code': kesco_code,
            'kesco_label': kesco_label,
            'isco_code': None,
            'isco_label': None,
            'isco_level': None,
            'match_type': None,
            'confidence': 0.0,
            'human_reviewed': False
        }

        # Step 1: Code AND label must match at unit level
        if kesco_code in isco_by_code:
            isco_label = isco_by_code[kesco_code]
            if kesco_label.lower() == isco_label.lower():
                match_result['isco_code'] = kesco_code
                match_result['isco_label'] = isco_label
                match_result['isco_level'] = 4
                match_result['match_type'] = 'code_exact'
                match_result['confidence'] = 1.0
                results.append(match_result)
                continue

        # Step 2: Labels match completely at unit level
        if kesco_label.lower() in isco_by_label:
            isco_code, isco_label = isco_by_label[kesco_label.lower()]
            match_result['isco_code'] = isco_code
            match_result['isco_label'] = isco_label
            match_result['isco_level'] = 4
            match_result['match_type'] = 'label_exact'
            match_result['confidence'] = 1.0
            results.append(match_result)
            continue

        # Step 3: Labels nearly match (fuzzy matching >= 75%)
        best_match = None
        best_sim = 0.0
        for isco_code, isco_label in isco_labels_list:
            sim = label_similarity(kesco_label, isco_label)
            if sim > best_sim:
                best_sim = sim
                best_match = (isco_code, isco_label)

        if best_match and best_sim >= 0.75:
            match_result['isco_code'] = best_match[0]
            match_result['isco_label'] = best_match[1]
            match_result['isco_level'] = 4
            match_result['match_type'] = 'label_similar'
            match_result['confidence'] = round(best_sim, 3)
            results.append(match_result)
            continue

        # Step 4: Everything else needs human review
        match_result['match_type'] = 'needs_review'
        match_result['confidence'] = 0.0
        results.append(match_result)

    df = pd.DataFrame(results)

    print(f"\nCrosswalk results:")
    for match_type in df['match_type'].unique():
        count = len(df[df['match_type'] == match_type])
        print(f"  {match_type}: {count}")

    OUTPUT_PATH.mkdir(parents=True, exist_ok=True)
    print(f"\nSaving to {CROSSWALK_REVIEW_OUTPUT}...")
    df.to_excel(CROSSWALK_REVIEW_OUTPUT, index=False)
    print(f"  Saved {len(df)} group mappings")

    needs_review = df[df['match_type'] == 'needs_review']
    print(f"\n  {len(needs_review)} groups need human review")
    print(f"  Review the 'needs_review' items in {CROSSWALK_REVIEW_OUTPUT}")
    print(f"  Then run generate_final_crosswalk() to produce the final output")


# =============================================================================
# STEP 3: GENERATE FINAL CROSSWALK (after human review)
# =============================================================================
# Uncomment and run this function after completing human review of needs_review items.
# Update the isco_code and isco_label columns for needs_review items, then change
# their match_type to 'human_revised'.
#
# def generate_final_crosswalk():
#     """
#     Generate final crosswalk after human review is complete.
#
#     Prerequisites:
#       - Review isco_kesco_needs_review.xlsx
#       - For 'needs_review' items, fill in isco_code and isco_label
#       - Change match_type from 'needs_review' to 'human_revised'
#     """
#     print("Generating final crosswalk...")
#
#     df = pd.read_excel(CROSSWALK_REVIEW_OUTPUT)
#
#     # Verify no items still need review
#     still_needs_review = df[df['match_type'] == 'needs_review']
#     if len(still_needs_review) > 0:
#         print(f"  ERROR: {len(still_needs_review)} items still need review")
#         print(f"  Complete human review before generating final output")
#         return
#
#     # Save final output
#     df.to_excel(CROSSWALK_FINAL_OUTPUT, index=False)
#     print(f"  Saved final crosswalk to {CROSSWALK_FINAL_OUTPUT}")
#     print(f"  Total: {len(df)} group mappings")
#
# if __name__ == '__main__':
#     generate_final_crosswalk()
# =============================================================================


def main():
    print("=" * 70)
    print("PREPARE KESCO DATA")
    print("=" * 70)

    # Load source data
    kesco_groups = load_kesco_groups()
    isco_groups = load_isco_groups()

    # Step 1: Build occupations with context
    build_occupations_with_context(kesco_groups)

    # Step 2: Build group crosswalk
    build_group_crosswalk(kesco_groups, isco_groups)

    print("\n" + "=" * 70)
    print("DATA PREPARATION COMPLETE")
    print("=" * 70)
    print(f"Outputs:")
    print(f"  - {CONTEXT_OUTPUT}")
    print(f"  - {CROSSWALK_REVIEW_OUTPUT}")
    print(f"\nNext step: Review 'needs_review' items, then uncomment generate_final_crosswalk()")


if __name__ == '__main__':
    main()
