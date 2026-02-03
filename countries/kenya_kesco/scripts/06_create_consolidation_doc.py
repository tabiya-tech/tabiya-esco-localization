"""
Create working document for NEW_LOCAL consolidation.

Groups the 171 NEW_LOCAL items into proposed new occupation codes,
allowing for review and refinement before creating actual codes.

Usage:
    python scripts/06_create_consolidation_doc.py
"""

import json
import pandas as pd
from collections import defaultdict
from pathlib import Path

BASE_PATH = Path(__file__).parent.parent
ROOT_PATH = BASE_PATH.parent.parent

def main():
    # Load NEW_LOCAL items
    with open(BASE_PATH / 'outputs' / 'kenya_kesco_matches_final.json', 'r', encoding='utf-8') as f:
        data = json.load(f)

    new_locals = [m for m in data['matches'] if m.get('category') == 'new_local']
    print(f'Total NEW_LOCAL items: {len(new_locals)}')

    # Group by parent
    by_parent = defaultdict(list)
    for m in new_locals:
        parent = m.get('parent_esco_code') or m.get('parent_isco_code') or 'NO_PARENT'
        by_parent[parent].append(m)

    print(f'Grouped into {len(by_parent)} parent codes')

    rows = []

    def propose_consolidation(parent_code, items, group_name, preferred_label, filter_fn=None):
        """Create a consolidation proposal row."""
        filtered = [i for i in items if filter_fn(i)] if filter_fn else items
        if not filtered:
            return None

        alt_labels = [i['kesco_title'] for i in filtered]
        kesco_codes = [i['kesco_code'] for i in filtered]
        parent_label = filtered[0].get('parent_esco_label') or filtered[0].get('parent_isco_label', '')

        return {
            'proposed_code': '',
            'preferred_label': preferred_label,
            'alt_labels': '\n'.join(sorted(set(alt_labels))),
            'alt_labels_count': len(alt_labels),
            'parent_esco_code': parent_code,
            'parent_esco_label': parent_label,
            'description': '',
            'kesco_codes': ', '.join(kesco_codes),
            'consolidation_group': group_name,
            'status': 'PROPOSED'
        }

    def add_individual(item, parent_code, group_name, status='REVIEW_NEEDED'):
        """Add an individual item as its own proposed code."""
        parent_label = item.get('parent_esco_label') or item.get('parent_isco_label', '')
        return {
            'proposed_code': '',
            'preferred_label': item['kesco_title'].lower(),
            'alt_labels': item['kesco_title'],
            'alt_labels_count': 1,
            'parent_esco_code': parent_code,
            'parent_esco_label': parent_label,
            'description': '',
            'kesco_codes': item['kesco_code'],
            'consolidation_group': group_name,
            'status': status
        }

    # === 6111: Field crop farmers (29 items) ===
    items = by_parent.get('6111', [])
    if items:
        row = propose_consolidation('6111', items, '6111-farmers', 'field crop farmer',
            lambda i: i['kesco_title'].lower().startswith('farmer'))
        if row: rows.append(row)

        row = propose_consolidation('6111', items, '6111-growers', 'field crop grower',
            lambda i: i['kesco_title'].lower().startswith('grower'))
        if row: rows.append(row)

        row = propose_consolidation('6111', items, '6111-planters', 'field crop planter',
            lambda i: i['kesco_title'].lower().startswith('planter'))
        if row: rows.append(row)

        row = propose_consolidation('6111', items, '6111-workers', 'skilled field crop farm worker',
            lambda i: i['kesco_title'].lower().startswith('worker'))
        if row: rows.append(row)

    # === 6112: Tree/shrub crop (26 items) ===
    items = by_parent.get('6112', [])
    if items:
        row = propose_consolidation('6112', items, '6112-farmers', 'tree and shrub crop farmer',
            lambda i: i['kesco_title'].lower().startswith('farmer'))
        if row: rows.append(row)

        row = propose_consolidation('6112', items, '6112-workers', 'skilled tree and shrub crop farm worker',
            lambda i: i['kesco_title'].lower().startswith('worker'))
        if row: rows.append(row)

        row = propose_consolidation('6112', items, '6112-tappers', 'tree tapper',
            lambda i: 'tapper' in i['kesco_title'].lower())
        if row: rows.append(row)

        row = propose_consolidation('6112', items, '6112-grafters', 'tree and shrub grafter',
            lambda i: 'grafter' in i['kesco_title'].lower() or 'budder' in i['kesco_title'].lower())
        if row: rows.append(row)

        row = propose_consolidation('6112', items, '6112-growers', 'tree and shrub crop grower',
            lambda i: i['kesco_title'].lower().startswith('grower'))
        if row: rows.append(row)

        row = propose_consolidation('6112', items, '6112-planters', 'tree and shrub crop planter',
            lambda i: i['kesco_title'].lower().startswith('planter'))
        if row: rows.append(row)

        row = propose_consolidation('6112', items, '6112-pruners', 'tree and shrub pruner',
            lambda i: 'pruner' in i['kesco_title'].lower())
        if row: rows.append(row)

    # === 6210: Forestry (16 items) ===
    items = by_parent.get('6210', [])
    if items:
        row = propose_consolidation('6210', items, '6210-cutters', 'timber cutter',
            lambda i: 'cutter' in i['kesco_title'].lower())
        if row: rows.append(row)

        row = propose_consolidation('6210', items, '6210-markers', 'timber marker',
            lambda i: 'marker' in i['kesco_title'].lower())
        if row: rows.append(row)

        # Remaining as individual
        covered_titles = {'cutter', 'marker'}
        for item in items:
            t = item['kesco_title'].lower()
            if not any(c in t for c in covered_titles):
                rows.append(add_individual(item, '6210', '6210-individual'))

    # === 6113: Horticultural growers (11 items) ===
    items = by_parent.get('6113', [])
    if items:
        row = propose_consolidation('6113', items, '6113-growers', 'horticultural crop grower',
            lambda i: 'grower' in i['kesco_title'].lower() or 'cultivator' in i['kesco_title'].lower())
        if row: rows.append(row)

        for item in items:
            t = item['kesco_title'].lower()
            if 'grower' not in t and 'cultivator' not in t:
                rows.append(add_individual(item, '6113', '6113-individual'))

    # === 6310: Subsistence farmers (9 items) ===
    items = by_parent.get('6310', [])
    if items:
        row = propose_consolidation('6310', items, '6310-all', 'subsistence crop farmer', lambda i: True)
        if row: rows.append(row)

    # === 6129: Exotic animal breeders (7 items) ===
    items = by_parent.get('6129', [])
    if items:
        row = propose_consolidation('6129', items, '6129-all', 'exotic animal breeder', lambda i: True)
        if row: rows.append(row)

    # === 6123: Sericulturists (6 items) ===
    items = by_parent.get('6123', [])
    if items:
        row = propose_consolidation('6123', items, '6123-all', 'sericulturist', lambda i: True)
        if row: rows.append(row)

    # === 1112: Senior government officials (5 items) - Kenya-specific ===
    items = by_parent.get('1112', [])
    for item in items:
        rows.append(add_individual(item, '1112', '1112-govt-officials', 'KENYA_SPECIFIC'))

    # === 1113: Village leaders (2 items) ===
    items = by_parent.get('1113', [])
    if items:
        row = propose_consolidation('1113', items, '1113-all', 'village leader', lambda i: True)
        if row: rows.append(row)

    # === 1114: Senior officials special-interest (2 items) ===
    items = by_parent.get('1114', [])
    if items:
        row = propose_consolidation('1114', items, '1114-all', 'legislative leader', lambda i: True)
        if row: rows.append(row)

    # === 5242: Party plan sales (4 items) ===
    items = by_parent.get('5242', [])
    if items:
        row = propose_consolidation('5242', items, '5242-all', 'party plan sales representative', lambda i: True)
        if row: rows.append(row)

    # === 6340: Subsistence gatherers (4 items) ===
    items = by_parent.get('6340', [])
    if items:
        row = propose_consolidation('6340', items, '6340-all', 'subsistence gatherer', lambda i: True)
        if row: rows.append(row)

    # === 8321: Motorized tricycle drivers (3 items) ===
    items = by_parent.get('8321', [])
    if items:
        row = propose_consolidation('8321', items, '8321-all', 'motorized tricycle driver', lambda i: True)
        if row: rows.append(row)

    # === 8160: Food machine operators (3 items) ===
    items = by_parent.get('8160', [])
    if items:
        row = propose_consolidation('8160', items, '8160-all', 'food processing machine operator', lambda i: True)
        if row: rows.append(row)

    # === 8343: Lock/sluice operators (4 items) ===
    items = by_parent.get('8343', [])
    if items:
        row = propose_consolidation('8343', items, '8343-all', 'lock and sluice operator', lambda i: True)
        if row: rows.append(row)

    # === Remaining groups ===
    processed_parents = {'6111', '6112', '6210', '6113', '6310', '6129', '6123',
                         '1112', '1113', '1114', '5242', '6340', '8321', '8160', '8343'}

    for parent in sorted(set(by_parent.keys()) - processed_parents):
        items = by_parent[parent]
        parent_label = items[0].get('parent_esco_label') or items[0].get('parent_isco_label', '')

        if len(items) >= 3:
            row = propose_consolidation(parent, items, f'{parent}-all',
                f'{parent_label.lower()}' if parent_label else f'worker under {parent}',
                lambda i: True)
            if row:
                row['status'] = 'REVIEW_CONSOLIDATION'
                rows.append(row)
        else:
            for item in items:
                rows.append(add_individual(item, parent, f'{parent}-individual'))

    # Create DataFrame
    df = pd.DataFrame(rows)
    df = df.sort_values(['parent_esco_code', 'consolidation_group', 'alt_labels_count'],
                        ascending=[True, True, False])

    # Save to Excel
    output_path = BASE_PATH / 'outputs' / 'new_local_consolidation_working.xlsx'
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Consolidation', index=False)

        # Summary sheet
        summary_data = []
        for status in df['status'].unique():
            subset = df[df['status'] == status]
            summary_data.append({
                'status': status,
                'proposed_codes': len(subset),
                'kesco_items': subset['alt_labels_count'].sum()
            })
        summary_df = pd.DataFrame(summary_data)
        summary_df.to_excel(writer, sheet_name='Summary', index=False)

    print(f'\nCreated: {output_path}')
    print(f'\nSummary:')
    print(f'  Total proposed codes: {len(df)}')
    print(f'  Total KESCO items covered: {df["alt_labels_count"].sum()}')
    print(f'\nBy status:')
    for status in df['status'].unique():
        subset = df[df['status'] == status]
        print(f'  {status}: {len(subset)} codes, {subset["alt_labels_count"].sum()} items')


if __name__ == '__main__':
    main()
