"""
Create new local occupations from the NEW_LOCAL working document.

This script handles the full workflow:
1. GENERATE: Read working doc, create new_local_occupations.csv with occupations.csv schema
2. ENRICH: Pass items with missing descriptions through LLM pipeline
3. MERGE: Add completed items to occupations.csv in appropriate position
4. HIERARCHY: Generate IDs and add entries to occupation_hierarchy.csv

Usage:
    python scripts/05_create_new_local.py generate   # Step 1: Create draft from working doc
    python scripts/05_create_new_local.py enrich     # Step 2: LLM enrichment for missing descriptions
    python scripts/05_create_new_local.py merge      # Step 3: Merge into occupations.csv
    python scripts/05_create_new_local.py hierarchy  # Step 4: Generate IDs and build hierarchy
    python scripts/05_create_new_local.py embed      # Step 5: Generate embeddings for O*NET matching
    python scripts/05_create_new_local.py all        # Run all steps
    python scripts/05_create_new_local.py status     # Show current status
"""

import os
import uuid
import json
import time
import secrets
import pandas as pd
from pathlib import Path
from collections import defaultdict
from tqdm import tqdm
from dotenv import load_dotenv
import google.generativeai as genai

BASE_PATH = Path(__file__).parent.parent
ROOT_PATH = BASE_PATH.parent.parent
WORKING_DOC = BASE_PATH / 'outputs' / 'new_local_working.xlsx'
NEW_LOCAL_CSV = BASE_PATH / 'outputs' / 'new_local_occupations.csv'
NEW_LOCAL_EMBEDDINGS = BASE_PATH / 'outputs' / 'new_local_embeddings.json'
OCCUPATIONS_CSV = BASE_PATH / 'outputs' / 'taxonomy' / 'occupations.csv'
HIERARCHY_CSV = BASE_PATH / 'outputs' / 'taxonomy' / 'occupation_hierarchy.csv'
ESCO_OCCUPATIONS = ROOT_PATH / 'shared_data' / 'esco_taxonomy' / 'occupations.csv'
ESCO_HIERARCHY = ROOT_PATH / 'shared_data' / 'esco_taxonomy' / 'occupation_hierarchy.csv'
OCCUPATION_GROUPS = ROOT_PATH / 'shared_data' / 'esco_taxonomy' / 'occupation_groups.csv'

# Embedding config
EMBEDDING_MODEL = 'models/gemini-embedding-001'
EMBEDDING_BATCH_SIZE = 100
EMBEDDING_TASK_TYPE = 'SEMANTIC_SIMILARITY'
EMBEDDING_DIM = 768

load_dotenv(ROOT_PATH / '.env')
genai.configure(api_key=os.environ.get('GEMINI_API_KEY'))

# Schema matching occupations.csv
COLUMNS = [
    'ID', 'ORIGINURI', 'UUIDHISTORY', 'OCCUPATIONGROUPCODE', 'CODE',
    'DEFINITION', 'SCOPENOTE', 'REGULATEDPROFESSIONNOTE', 'OCCUPATIONTYPE',
    'ISLOCALIZED', 'PREFERREDLABEL', 'ALTLABELS', 'DESCRIPTION'
]


def load_occupation_groups() -> dict[str, str]:
    """Load ISCO group code -> label mapping."""
    df = pd.read_csv(OCCUPATION_GROUPS)
    return dict(zip(df['CODE'].astype(str), df['PREFERREDLABEL']))


def generate_occupations():
    """Step 1: Generate new_local_occupations.csv from working doc."""
    print("\n=== STEP 1: GENERATE ===")

    # Load working doc
    working_df = pd.read_excel(WORKING_DOC, sheet_name='NEW_LOCAL')
    print(f"Loaded {len(working_df)} items from working doc")

    # Filter to items with preferred_label
    with_labels = working_df[working_df['preferred_label'].notna() &
                             (working_df['preferred_label'].str.strip() != '')]
    print(f"Items with preferred_label: {len(with_labels)}")

    if len(with_labels) == 0:
        print("No items with preferred_label found. Nothing to generate.")
        return

    # Group by preferred_label
    groups = defaultdict(list)
    for _, row in with_labels.iterrows():
        key = (row['parent_esco_code'], row['preferred_label'].strip().lower())
        groups[key].append({
            'kesco_code': row['kesco_code'],
            'kesco_title': row['kesco_title'],
            'parent_esco_code': str(row['parent_esco_code']),
            'parent_esco_label': row['parent_esco_label'],
        })

    print(f"Unique occupations to create: {len(groups)}")

    # Track codes per ISCO group to assign sequential numbers
    isco_counters = defaultdict(int)

    # Load existing new_local_occupations.csv to preserve existing codes
    existing_codes = {}
    if NEW_LOCAL_CSV.exists():
        existing_df = pd.read_csv(NEW_LOCAL_CSV)
        for _, row in existing_df.iterrows():
            existing_codes[row['PREFERREDLABEL'].lower()] = row['CODE']
            # Track highest counter per ISCO
            code = row['CODE']
            if '_' in str(code):
                isco, num = code.rsplit('_', 1)
                if num.isdigit():
                    isco_counters[isco] = max(isco_counters[isco], int(num))

    # Also check occupations.csv for existing codes
    if OCCUPATIONS_CSV.exists():
        occ_df = pd.read_csv(OCCUPATIONS_CSV)
        for _, row in occ_df.iterrows():
            code = row['CODE']
            if '_' in str(code):
                isco, num = code.rsplit('_', 1)
                if num.isdigit():
                    isco_counters[isco] = max(isco_counters[isco], int(num))

    # Build occupation rows
    rows = []
    for (parent_code, preferred_label), items in sorted(groups.items()):
        parent_code = str(parent_code).split('.')[0]  # Remove decimal if present

        # Get or assign code
        if preferred_label in existing_codes:
            code = existing_codes[preferred_label]
        else:
            isco_counters[parent_code] += 1
            code = f"{parent_code}_{isco_counters[parent_code]}"

        # Build alt labels (exclude if same as preferred_label)
        alt_labels = []
        for item in items:
            title = item['kesco_title']
            if title.lower().strip() != preferred_label:
                alt_labels.append(title)

        rows.append({
            'ID': '',  # Leave blank as requested
            'ORIGINURI': '',
            'UUIDHISTORY': str(uuid.uuid4()),
            'OCCUPATIONGROUPCODE': parent_code,
            'CODE': code,
            'DEFINITION': '',
            'SCOPENOTE': '',
            'REGULATEDPROFESSIONNOTE': '',
            'OCCUPATIONTYPE': 'localoccupation',
            'ISLOCALIZED': True,
            'PREFERREDLABEL': preferred_label,
            'ALTLABELS': '\n'.join([preferred_label] + sorted(set(alt_labels))),
            'DESCRIPTION': '',  # To be filled by LLM
        })

    # Create DataFrame with correct column order
    df = pd.DataFrame(rows, columns=COLUMNS)
    df = df.sort_values(['OCCUPATIONGROUPCODE', 'CODE'])

    # Save
    df.to_csv(NEW_LOCAL_CSV, index=False)
    print(f"\nSaved {len(df)} occupations to {NEW_LOCAL_CSV.name}")

    # Show summary
    print("\nBy parent group:")
    for code in sorted(df['OCCUPATIONGROUPCODE'].unique()):
        count = len(df[df['OCCUPATIONGROUPCODE'] == code])
        print(f"  {code}: {count} occupations")


def enrich_occupations():
    """Step 2: Use LLM to add descriptions and additional alt labels."""
    print("\n=== STEP 2: ENRICH ===")

    if not NEW_LOCAL_CSV.exists():
        print("new_local_occupations.csv not found. Run 'generate' first.")
        return

    df = pd.read_csv(NEW_LOCAL_CSV)
    print(f"Loaded {len(df)} occupations")

    # Find items needing enrichment (missing description)
    needs_enrichment = df[df['DESCRIPTION'].isna() | (df['DESCRIPTION'].fillna('').astype(str).str.strip() == '')]
    print(f"Items needing description: {len(needs_enrichment)}")

    if len(needs_enrichment) == 0:
        print("All items have descriptions. Nothing to enrich.")
        return

    # Load occupation groups for context
    groups = load_occupation_groups()

    # Load ESCO occupations for context (siblings under same parent)
    esco_df = pd.read_csv(ESCO_OCCUPATIONS)

    # Setup Gemini
    model = genai.GenerativeModel('gemini-2.5-flash')

    enriched_count = 0
    for idx, row in needs_enrichment.iterrows():
        parent_code = str(row['OCCUPATIONGROUPCODE'])
        parent_label = groups.get(parent_code, 'Unknown')
        preferred_label = row['PREFERREDLABEL']
        alt_labels = row['ALTLABELS'] if pd.notna(row['ALTLABELS']) else ''

        # Get sibling occupations for context
        siblings = esco_df[esco_df['OCCUPATIONGROUPCODE'] == parent_code]
        sibling_context = []
        for _, sib in siblings.head(5).iterrows():
            sibling_context.append(f"- {sib['PREFERREDLABEL']}: {sib['DESCRIPTION'][:200]}...")

        prompt = f"""You are an occupations taxonomy expert specializing in labour market classification systems, particularly ISCO-08, ESCO, and national adaptations for low- and middle-income countries.

OCCUPATION TO ENRICH:
- Preferred Label: {preferred_label}
- Existing Alt Labels: {alt_labels if alt_labels else "None"}
- Parent Group: {parent_code} - {parent_label}

SIBLING OCCUPATIONS (for context):
{chr(10).join(sibling_context) if sibling_context else "None available"}

YOUR TASKS:

1. DESCRIPTION (150-300 characters):
   - Start with "[Occupation]s [verb]..." pattern (e.g., "Senior judiciary members oversee...")
   - Describe the main responsibilities and activities
   - Be professional and neutral in tone
   - Focus on what distinguishes this from sibling occupations

2. ADDITIONAL ALTERNATIVE LABELS (0-8 labels):
   Generate terms that workers, employers, job boards, or training providers might use for this occupation.

   Consider:
   - British/American spelling variations (e.g., labour/labor, specialised/specialized)
   - Synonyms and near-synonyms for the same functional role
   - Narrower task-specific titles that fall under this occupation
   - Industry-specific jargon

   Rules:
   - Do NOT duplicate existing alternative labels
   - Do NOT suggest labels belonging to a fundamentally different occupation
   - Do NOT suggest labels so broad they apply to multiple occupations in the same group
   - Each label must be clearly attributable to THIS occupation
   - Only include labels you are highly confident are used in practice

Respond in JSON format:
{{
  "description": "...",
  "additional_alt_labels": ["label1", "label2"]
}}

Only include labels you are highly confident about."""

        try:
            response = model.generate_content(prompt)
            text = response.text.strip()

            # Parse JSON from response
            if '```json' in text:
                text = text.split('```json')[1].split('```')[0]
            elif '```' in text:
                text = text.split('```')[1].split('```')[0]

            result = json.loads(text)

            # Update description
            df.loc[idx, 'DESCRIPTION'] = result.get('description', '')

            # Add new alt labels
            existing_alts = set(alt_labels.split('\n')) if alt_labels else set()
            new_alts = set(str(item) for item in result.get('additional_alt_labels', []))
            all_alts = existing_alts | new_alts
            all_alts.discard('')
            all_alts.discard(preferred_label)
            all_alts.discard(preferred_label.lower())
            df.loc[idx, 'ALTLABELS'] = '\n'.join([preferred_label] + sorted(all_alts))

            enriched_count += 1
            print(f"  Enriched: {row['CODE']} - {preferred_label}")

        except Exception as e:
            print(f"  Error enriching {row['CODE']}: {e}")

    # Save
    df.to_csv(NEW_LOCAL_CSV, index=False)
    print(f"\nEnriched {enriched_count} occupations")
    print(f"Saved to {NEW_LOCAL_CSV.name}")


def merge_occupations():
    """Step 3: Merge completed occupations into occupations.csv."""
    print("\n=== STEP 3: MERGE ===")

    if not NEW_LOCAL_CSV.exists():
        print("new_local_occupations.csv not found. Run 'generate' first.")
        return

    new_local_df = pd.read_csv(NEW_LOCAL_CSV)
    print(f"Loaded {len(new_local_df)} new local occupations")

    # Filter to items with descriptions (completed enrichment)
    completed = new_local_df[new_local_df['DESCRIPTION'].notna() &
                             (new_local_df['DESCRIPTION'].str.strip() != '')]
    print(f"Completed (with descriptions): {len(completed)}")

    if len(completed) == 0:
        print("No completed items to merge. Run 'enrich' first.")
        return

    # Load current occupations.csv
    if not OCCUPATIONS_CSV.exists():
        print(f"occupations.csv not found at {OCCUPATIONS_CSV}")
        return

    occ_df = pd.read_csv(OCCUPATIONS_CSV)
    print(f"Current occupations.csv: {len(occ_df)} rows")

    # Find existing codes to avoid duplicates
    existing_codes = set(occ_df['CODE'].values)

    # Filter to items not already in occupations.csv
    to_add = completed[~completed['CODE'].isin(existing_codes)]
    already_exists = completed[completed['CODE'].isin(existing_codes)]

    if len(already_exists) > 0:
        print(f"Already in occupations.csv (skipping): {len(already_exists)}")
        for _, row in already_exists.iterrows():
            print(f"  {row['CODE']} - {row['PREFERREDLABEL']}")

    if len(to_add) == 0:
        print("No new items to add.")
        return

    print(f"Adding {len(to_add)} new occupations")

    # Append and sort
    merged_df = pd.concat([occ_df, to_add], ignore_index=True)
    merged_df = merged_df.sort_values(['OCCUPATIONGROUPCODE', 'CODE'])

    # Save
    merged_df.to_csv(OCCUPATIONS_CSV, index=False)
    print(f"\nSaved {len(merged_df)} occupations to {OCCUPATIONS_CSV.name}")
    print(f"Added: {len(to_add)} new local occupations")


def build_hierarchy():
    """Step 4: Generate IDs and build occupation_hierarchy.csv."""
    print("\n=== STEP 4: BUILD HIERARCHY ===")

    if not OCCUPATIONS_CSV.exists():
        print(f"occupations.csv not found at {OCCUPATIONS_CSV}")
        return

    # Load occupation groups to get parent IDs
    groups_df = pd.read_csv(OCCUPATION_GROUPS)
    group_code_to_id = dict(zip(groups_df['CODE'].astype(str), groups_df['ID']))
    print(f"Loaded {len(group_code_to_id)} occupation groups")

    # Load occupations
    occ_df = pd.read_csv(OCCUPATIONS_CSV)
    print(f"Loaded {len(occ_df)} occupations")

    # Find occupations missing IDs
    missing_ids = occ_df[occ_df['ID'].isna() | (occ_df['ID'] == '')]
    print(f"Occupations missing IDs: {len(missing_ids)}")

    if len(missing_ids) > 0:
        # Generate IDs for missing
        for idx in missing_ids.index:
            new_id = secrets.token_hex(12)  # 24-char hex like existing IDs
            occ_df.loc[idx, 'ID'] = new_id
        print(f"Generated {len(missing_ids)} new IDs")

        # Save updated occupations
        occ_df.to_csv(OCCUPATIONS_CSV, index=False)
        print(f"Updated {OCCUPATIONS_CSV.name} with new IDs")

    # Load or create hierarchy
    if HIERARCHY_CSV.exists():
        hier_df = pd.read_csv(HIERARCHY_CSV)
        print(f"Loaded existing hierarchy: {len(hier_df)} entries")
    elif ESCO_HIERARCHY.exists():
        hier_df = pd.read_csv(ESCO_HIERARCHY)
        print(f"Loaded base ESCO hierarchy: {len(hier_df)} entries")
    else:
        hier_df = pd.DataFrame(columns=['PARENTOBJECTTYPE', 'PARENTID', 'CHILDID', 'CHILDOBJECTTYPE'])
        print("Created new hierarchy")

    # Find occupations not in hierarchy
    existing_child_ids = set(hier_df['CHILDID'].values)
    occ_ids = set(occ_df['ID'].values)
    missing_from_hier = occ_ids - existing_child_ids

    # Filter to just our new local occupations
    new_local = occ_df[(occ_df['OCCUPATIONTYPE'] == 'localoccupation') &
                       (occ_df['ID'].isin(missing_from_hier))]
    print(f"New local occupations to add to hierarchy: {len(new_local)}")

    if len(new_local) == 0:
        print("All occupations already in hierarchy.")
        return

    # Build hierarchy entries
    new_entries = []
    missing_parents = []
    for _, row in new_local.iterrows():
        parent_code = str(row['OCCUPATIONGROUPCODE'])
        parent_id = group_code_to_id.get(parent_code)

        if not parent_id:
            missing_parents.append((row['CODE'], parent_code))
            continue

        new_entries.append({
            'PARENTOBJECTTYPE': 'iscogroup',
            'PARENTID': parent_id,
            'CHILDID': row['ID'],
            'CHILDOBJECTTYPE': 'localoccupation'
        })

    if missing_parents:
        print(f"WARNING: {len(missing_parents)} occupations have unknown parent groups:")
        for code, parent in missing_parents[:5]:
            print(f"  {code} -> {parent}")

    if new_entries:
        new_hier_df = pd.DataFrame(new_entries)
        hier_df = pd.concat([hier_df, new_hier_df], ignore_index=True)
        print(f"Added {len(new_entries)} hierarchy entries")

    # Save hierarchy
    HIERARCHY_CSV.parent.mkdir(parents=True, exist_ok=True)
    hier_df.to_csv(HIERARCHY_CSV, index=False)
    print(f"Saved {len(hier_df)} entries to {HIERARCHY_CSV.name}")


def embed_occupations():
    """Step 5: Generate embeddings for new local occupations (title + description)."""
    print("\n=== STEP 5: EMBED ===")

    if not NEW_LOCAL_CSV.exists():
        print("new_local_occupations.csv not found. Run 'generate' first.")
        return

    df = pd.read_csv(NEW_LOCAL_CSV)
    print(f"Loaded {len(df)} new local occupations")

    # Only embed items with descriptions
    with_desc = df[df['DESCRIPTION'].notna() & (df['DESCRIPTION'].str.strip() != '')]
    print(f"Items with descriptions: {len(with_desc)}")

    if len(with_desc) == 0:
        print("No items with descriptions. Run 'enrich' first.")
        return

    # Build embedding texts: title + description (same format as O*NET embeddings)
    embedding_items = []
    texts = []
    for _, row in with_desc.iterrows():
        label = str(row['PREFERREDLABEL']).strip()
        description = str(row['DESCRIPTION']).strip()
        embedding_text = f"{label}: {description}" if description else label

        embedding_items.append({
            'code': str(row['CODE']),
            'label': label,
            'description': description[:300],
            'group_code': str(row['OCCUPATIONGROUPCODE']),
        })
        texts.append(embedding_text)

    # Generate embeddings in batches
    print(f"Generating embeddings with {EMBEDDING_MODEL}...")
    all_embeddings = []
    num_batches = (len(texts) + EMBEDDING_BATCH_SIZE - 1) // EMBEDDING_BATCH_SIZE

    for i in tqdm(range(0, len(texts), EMBEDDING_BATCH_SIZE), total=num_batches, desc="  Embedding"):
        batch_texts = texts[i:i + EMBEDDING_BATCH_SIZE]

        max_retries = 5
        for attempt in range(max_retries):
            try:
                result = genai.embed_content(
                    model=EMBEDDING_MODEL,
                    content=batch_texts,
                    task_type=EMBEDDING_TASK_TYPE,
                    output_dimensionality=EMBEDDING_DIM,
                )
                all_embeddings.extend(result['embedding'])
                break
            except Exception as e:
                if '429' in str(e) or 'quota' in str(e).lower():
                    wait_time = 45 * (attempt + 1)
                    print(f"\n  Rate limit, waiting {wait_time}s (attempt {attempt+1}/{max_retries})...")
                    time.sleep(wait_time)
                else:
                    print(f"\n  Error: {e}")
                    time.sleep(5)
                if attempt == max_retries - 1:
                    raise

        time.sleep(1.5)

    # Attach embeddings to items
    for i, item in enumerate(embedding_items):
        item['embedding'] = all_embeddings[i]

    # Save
    data = {
        'metadata': {
            'model': EMBEDDING_MODEL,
            'source': str(NEW_LOCAL_CSV),
            'num_occupations': len(embedding_items),
            'embedding_dim': len(all_embeddings[0]),
            'format': 'title + description - Gemini gemini-embedding-001',
            'task_type': EMBEDDING_TASK_TYPE,
            'date_generated': pd.Timestamp.now().isoformat(),
        },
        'occupations': embedding_items,
    }

    with open(NEW_LOCAL_EMBEDDINGS, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    file_size_mb = NEW_LOCAL_EMBEDDINGS.stat().st_size / (1024 * 1024)
    print(f"  Saved {len(embedding_items)} embeddings ({file_size_mb:.1f} MB)")
    print(f"  Output: {NEW_LOCAL_EMBEDDINGS}")


def show_status():
    """Show current status of the pipeline."""
    print("\n=== STATUS ===")

    # Working doc
    if WORKING_DOC.exists():
        working_df = pd.read_excel(WORKING_DOC, sheet_name='NEW_LOCAL')
        with_labels = working_df[working_df['preferred_label'].notna() &
                                 (working_df['preferred_label'].str.strip() != '')]
        unique_labels = with_labels['preferred_label'].str.strip().str.lower().nunique()
        print(f"Working doc: {len(working_df)} items, {len(with_labels)} with labels, {unique_labels} unique")
    else:
        print("Working doc: NOT FOUND")

    # New local occupations
    if NEW_LOCAL_CSV.exists():
        df = pd.read_csv(NEW_LOCAL_CSV)
        with_desc = df[df['DESCRIPTION'].notna() & (df['DESCRIPTION'].str.strip() != '')]
        print(f"new_local_occupations.csv: {len(df)} occupations, {len(with_desc)} with descriptions")
    else:
        print("new_local_occupations.csv: NOT CREATED")

    # Occupations.csv
    if OCCUPATIONS_CSV.exists():
        occ_df = pd.read_csv(OCCUPATIONS_CSV)
        local = occ_df[occ_df['OCCUPATIONTYPE'] == 'localoccupation']
        print(f"occupations.csv: {len(occ_df)} total, {len(local)} local occupations")
    else:
        print("occupations.csv: NOT FOUND")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Create new local occupations")
    parser.add_argument("command", choices=['generate', 'enrich', 'merge', 'hierarchy', 'embed', 'all', 'status'],
                        help="Command to run")
    args = parser.parse_args()

    print("=" * 60)
    print("CREATE NEW LOCAL OCCUPATIONS")
    print("=" * 60)

    if args.command == 'status':
        show_status()
    elif args.command == 'generate':
        generate_occupations()
    elif args.command == 'enrich':
        enrich_occupations()
    elif args.command == 'merge':
        merge_occupations()
    elif args.command == 'hierarchy':
        build_hierarchy()
    elif args.command == 'embed':
        embed_occupations()
    elif args.command == 'all':
        generate_occupations()
        enrich_occupations()
        merge_occupations()
        build_hierarchy()
        embed_occupations()

    print("\n" + "=" * 60)
    print("DONE")
    print("=" * 60)


if __name__ == "__main__":
    main()
