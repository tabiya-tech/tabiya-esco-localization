"""
Add immediate parent mapping column to skills.csv based on skill_hierarchy.csv

Logic for selecting closest parent when multiple parents exist:
- If skill has both skill and skillgroup parents:
    - If skill_parent belongs to same skillgroup as child -> pick SKILL (it's closer)
    - Else -> pick SKILLGROUP (parallel branches, skillgroup is categorical home)
- If only skillgroup parents -> pick first skillgroup
- If only skill parents -> pick first skill
"""
import csv
from collections import defaultdict


def build_hierarchy(filepath: str) -> dict:
    """Build child -> parents mapping from hierarchy file."""
    hierarchy = defaultdict(list)
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            hierarchy[row['CHILDID']].append({
                'parent_id': row['PARENTID'],
                'parent_type': row['PARENTOBJECTTYPE'],
                'child_type': row['CHILDOBJECTTYPE']
            })
    return hierarchy


def get_skillgroup_parents(hierarchy: dict, item_id: str) -> set:
    """Get all skillgroup parent IDs for an item."""
    return {p['parent_id'] for p in hierarchy.get(item_id, [])
            if p['parent_type'] == 'skillgroup'}


def select_closest_parent(parents: list, hierarchy: dict) -> dict:
    """
    Select the closest/most immediate parent based on hierarchy structure.

    Returns dict with 'parent_id' and 'parent_type'.
    """
    if len(parents) == 1:
        return parents[0]

    types = set(p['parent_type'] for p in parents)

    # Case: Only skillgroup parents
    if types == {'skillgroup'}:
        return parents[0]

    # Case: Only skill parents
    if types == {'skill'}:
        return parents[0]

    # Case: Both skill and skillgroup parents
    sg_parents = [p for p in parents if p['parent_type'] == 'skillgroup']
    sk_parents = [p for p in parents if p['parent_type'] == 'skill']

    child_skillgroups = {p['parent_id'] for p in sg_parents}

    # Check if any skill parent belongs to the same skillgroup as child
    for sk_p in sk_parents:
        sk_parent_skillgroups = get_skillgroup_parents(hierarchy, sk_p['parent_id'])
        if child_skillgroups & sk_parent_skillgroups:
            # Chain exists: skillgroup -> skill_parent -> child
            # Skill parent is closer
            return sk_p

    # No chain: parallel branches, prefer skillgroup as categorical home
    return sg_parents[0]


def load_labels(skills_file: str, skillgroups_file: str) -> dict:
    """Load preferred labels for skills and skillgroups."""
    labels = {}

    with open(skills_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            labels[row['ID']] = row.get('PREFERREDLABEL', '')

    with open(skillgroups_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            labels[row['ID']] = row.get('PREFERREDLABEL', '')

    return labels


def main():
    print("Loading hierarchy...")
    hierarchy = build_hierarchy('skill_hierarchy.csv')

    print("Loading labels...")
    labels = load_labels('skills.csv', 'skill_groups.csv')

    # Filter to skill children only
    skill_parents = {k: v for k, v in hierarchy.items()
                     if v and v[0]['child_type'] == 'skill'}

    print(f"Found {len(skill_parents)} skills with parents in hierarchy")

    # Count multi-parent skills
    multi_parent = {k: v for k, v in skill_parents.items() if len(v) > 1}
    print(f"Skills with multiple parents: {len(multi_parent)}")

    # Track selection stats
    stats = {
        'chain_skill_selected': 0,
        'parallel_skillgroup_selected': 0,
        'single_parent': 0,
        'only_skillgroups': 0,
        'only_skills': 0
    }

    # Read skills.csv and add parent column
    skills = []
    unmapped = []

    print("Processing skills...")
    with open('skills.csv', 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames

        for row in reader:
            skill_id = row['ID']

            if skill_id in skill_parents:
                parents = skill_parents[skill_id]

                if len(parents) == 1:
                    stats['single_parent'] += 1
                    selected = parents[0]
                else:
                    types = set(p['parent_type'] for p in parents)
                    selected = select_closest_parent(parents, hierarchy)

                    if types == {'skillgroup'}:
                        stats['only_skillgroups'] += 1
                    elif types == {'skill'}:
                        stats['only_skills'] += 1
                    elif selected['parent_type'] == 'skill':
                        stats['chain_skill_selected'] += 1
                    else:
                        stats['parallel_skillgroup_selected'] += 1

                row['PARENTID'] = selected['parent_id']
                row['PARENTOBJECTTYPE'] = selected['parent_type']
                row['PARENTLABEL'] = labels.get(selected['parent_id'], '')
            else:
                row['PARENTID'] = ''
                row['PARENTOBJECTTYPE'] = ''
                row['PARENTLABEL'] = ''
                unmapped.append({
                    'id': skill_id,
                    'label': row.get('PREFERREDLABEL', 'N/A')
                })

            skills.append(row)

    print(f"\nTotal skills processed: {len(skills)}")
    print(f"Skills without parent mapping: {len(unmapped)}")

    print(f"\nSelection statistics:")
    print(f"  Single parent (no choice needed): {stats['single_parent']}")
    print(f"  Multi-parent - chain detected, skill selected: {stats['chain_skill_selected']}")
    print(f"  Multi-parent - parallel, skillgroup selected: {stats['parallel_skillgroup_selected']}")
    print(f"  Multi-parent - only skillgroups: {stats['only_skillgroups']}")
    print(f"  Multi-parent - only skills: {stats['only_skills']}")

    # Write updated skills.csv
    new_fieldnames = list(fieldnames) + ['PARENTID', 'PARENTOBJECTTYPE', 'PARENTLABEL']

    with open('skills_with_parent.csv', 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=new_fieldnames)
        writer.writeheader()
        writer.writerows(skills)

    print(f"\nOutput written to: skills_with_parent.csv")

    if unmapped:
        print(f"\n--- UNMAPPED SKILLS ({len(unmapped)}) ---")
        for item in unmapped[:20]:
            print(f"  ID: {item['id']}, Label: {item['label'][:60]}")
        if len(unmapped) > 20:
            print(f"  ... and {len(unmapped) - 20} more")

        with open('unmapped_skills.csv', 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['id', 'label'])
            writer.writeheader()
            writer.writerows(unmapped)
        print(f"Full unmapped list written to: unmapped_skills.csv")


if __name__ == '__main__':
    main()
