"""
Extract CNO 2017 structure from raw text file.

Preserves the 5-digit CNO code structure: Major(2).Submajor(1).Minor(1).Qualification(1)
Adds sub-group and occupation numbering within each CNO unit.

Output columns:
- major_code, major_title_es
- submajor_code, submajor_title_es
- minor_code, minor_title_es
- unit_code (5-digit CNO code, e.g., 05.0.0.1)
- unit_qualification (1=profesional, 2=tecnica, 3=operativa, 4=no calificada)
- subgroup_code (unit_code.XX, e.g., 05.0.0.1.01)
- subgroup_title_es
- occupation_code (subgroup_code.XXX, e.g., 05.0.0.1.01.001)
- occupation_es
"""

import re
import pandas as pd
from pathlib import Path


def preprocess_text(raw_text: str) -> list:
    """Pre-process raw PDF text to merge multi-line content and clean up artifacts."""
    lines = raw_text.split('\n')
    merged_lines = []
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        # Skip empty lines
        if not line:
            i += 1
            continue

        # Skip decorative patterns and headers
        if (line.startswith('CNOCNO') or
            'Clasificador Nacional' in line or
            'INDEC' in line or
            'Versión 2017' in line or
            re.match(r'^\d+Clasicador Nacional', line) or
            re.match(r'^\d+INDEC', line)):
            i += 1
            continue

        # Check if this is a code line (starts with XX or XX.X or * )
        is_code_line = bool(
            re.match(r'^\d{1,2}(?:\.\d+)*\s+', line) or
            line.startswith('*')
        )

        if is_code_line:
            # Merge continuation lines
            current_line = line
            j = i + 1

            # Handle hyphenated line breaks
            while current_line.endswith('-') and j < len(lines):
                next_line = lines[j].strip()
                # Skip headers/footers
                if (next_line and
                    not next_line.startswith('CNOCNO') and
                    'Clasificador Nacional' not in next_line and
                    'INDEC' not in next_line and
                    not re.match(r'^\d+Clasicador', next_line) and
                    not re.match(r'^\d+INDEC', next_line)):
                    # Check if next line is a continuation (doesn't start with code or *)
                    if not re.match(r'^\d{1,2}(?:\.\d+)*\s+', next_line) and not next_line.startswith('*'):
                        # Remove hyphen and merge
                        current_line = current_line[:-1] + next_line
                        j += 1
                        continue
                break

            # Also handle non-hyphenated continuations (lines that wrap without hyphen)
            while j < len(lines):
                next_line = lines[j].strip()
                if not next_line:
                    break
                # Skip headers/footers
                if ('Clasificador Nacional' in next_line or
                    'INDEC' in next_line or
                    'Versión 2017' in next_line or
                    re.match(r'^\d+Clasicador', next_line) or
                    re.match(r'^\d+INDEC', next_line)):
                    j += 1
                    continue
                # Check if continuation (doesn't start with code or *)
                if not re.match(r'^\d{1,2}(?:\.\d+)*\s+', next_line) and not next_line.startswith('*'):
                    current_line += ' ' + next_line
                    j += 1
                else:
                    break

            # Clean up extra spaces
            current_line = re.sub(r'\s+', ' ', current_line).strip()
            merged_lines.append(current_line)
            i = j
        else:
            i += 1

    return merged_lines


def extract_cno_hierarchy(raw_text: str) -> pd.DataFrame:
    """Extract CNO hierarchy preserving 5-digit structure."""

    # Pre-process to merge multi-line content
    lines = preprocess_text(raw_text)
    print(f"Pre-processed {len(lines)} content lines")

    # Current hierarchy context
    current_major = {'code': '', 'title': ''}
    current_submajor = {'code': '', 'title': ''}
    current_minor = {'code': '', 'title': ''}
    current_unit = {'code': '', 'qualification': '', 'title': ''}
    current_subgroup = {'code': '', 'title': ''}

    # Counters for sub-groups and occupations
    subgroup_counter = 0
    occupation_counter = 0

    # Results
    data = []

    # Track known major codes to avoid false positives from page headers
    # These are legitimate 2-digit CNO major codes (00-92)
    known_major_codes = set()

    for i, line in enumerate(lines):
        # MAJOR CATEGORY: "92 OCUPACIONES DE LA..." (all caps)
        # Only match if truly all caps (page headers often have mixed case)
        major_match = re.match(r'^(\d{1,2})\s+([A-Z\s,/()]+)$', line)
        if major_match and '.' not in major_match.group(1):
            code = major_match.group(1).zfill(2)
            title = major_match.group(2).strip()

            # Verify this looks like a real major category
            # - Title should be all caps
            # - Title should be substantial (not just a page header fragment)
            if title.isupper() and len(title) > 20:
                # Avoid false positives: check if code matches expected pattern
                # Real major codes go: 00-07 (directors), 10-11, 20, 30-36, 40-44, 50-54, 60-62, 70-74, 80-83, 90-92
                valid_ranges = [(0, 7), (10, 11), (20, 20), (30, 36), (40, 44), (50, 54), (60, 62), (70, 74), (80, 83), (90, 92)]
                code_int = int(code)
                is_valid_major = any(start <= code_int <= end for start, end in valid_ranges)

                if is_valid_major:
                    current_major = {'code': code, 'title': title}
                    current_submajor = {'code': '', 'title': ''}
                    current_minor = {'code': '', 'title': ''}
                    current_unit = {'code': '', 'qualification': '', 'title': ''}
                    current_subgroup = {'code': '', 'title': ''}
                    known_major_codes.add(code)
                    print(f"Major: {code} - {title[:60]}...")
                    continue

        # SUB-MAJOR CATEGORY: "92.0 Trabajadores de..."
        submajor_match = re.match(r'^(\d{1,2}\.\d)\s+(.+)$', line)
        if submajor_match and not line.startswith('*'):
            code = submajor_match.group(1)
            title = submajor_match.group(2).strip()

            # Normalize major code
            parts = code.split('.')
            normalized_code = f"{parts[0].zfill(2)}.{parts[1]}"
            major_code = parts[0].zfill(2)

            # If major is not set or different, infer from submajor
            if not current_major['code'] or current_major['code'] != major_code:
                current_major = {'code': major_code, 'title': f'[Inferred from {normalized_code}]'}

            current_submajor = {'code': normalized_code, 'title': title}
            current_minor = {'code': '', 'title': ''}
            current_unit = {'code': '', 'qualification': '', 'title': ''}
            current_subgroup = {'code': '', 'title': ''}
            print(f"  Submajor: {normalized_code} - {title[:50]}...")
            continue

        # MINOR CATEGORY: "92.0.0 Trabajadores de..."
        minor_match = re.match(r'^(\d{1,2}\.\d\.\d)\s+(.+)$', line)
        if minor_match and not line.startswith('*'):
            code = minor_match.group(1)
            title = minor_match.group(2).strip()

            # Normalize
            parts = code.split('.')
            normalized_code = f"{parts[0].zfill(2)}.{parts[1]}.{parts[2]}"
            major_code = parts[0].zfill(2)
            submajor_code = f"{major_code}.{parts[1]}"

            # Infer major if not set or different
            if not current_major['code'] or current_major['code'] != major_code:
                current_major = {'code': major_code, 'title': f'[Inferred from {normalized_code}]'}

            # Infer submajor if not set or different
            if not current_submajor['code'] or current_submajor['code'] != submajor_code:
                current_submajor = {'code': submajor_code, 'title': f'[Inferred from {normalized_code}]'}

            current_minor = {'code': normalized_code, 'title': title}
            current_unit = {'code': '', 'qualification': '', 'title': ''}
            current_subgroup = {'code': '', 'title': ''}
            print(f"    Minor: {normalized_code} - {title[:50]}...")
            continue

        # UNIT GROUP: "92.0.0.1 Calificación..." or "92.0.0.1 Trabajadores de..."
        unit_match = re.match(r'^(\d{1,2}\.\d\.\d\.\d)\s+(.+)$', line)
        if unit_match and not line.startswith('*'):
            code = unit_match.group(1)
            title = unit_match.group(2).strip()

            # Normalize
            parts = code.split('.')
            normalized_code = f"{parts[0].zfill(2)}.{parts[1]}.{parts[2]}.{parts[3]}"
            qualification = parts[3]
            major_code = parts[0].zfill(2)
            submajor_code = f"{major_code}.{parts[1]}"
            minor_code = f"{submajor_code}.{parts[2]}"

            # Infer hierarchy if not set or different
            if not current_major['code'] or current_major['code'] != major_code:
                current_major = {'code': major_code, 'title': f'[Inferred from {normalized_code}]'}
            if not current_submajor['code'] or current_submajor['code'] != submajor_code:
                current_submajor = {'code': submajor_code, 'title': f'[Inferred from {normalized_code}]'}
            if not current_minor['code'] or current_minor['code'] != minor_code:
                current_minor = {'code': minor_code, 'title': f'[Inferred from {normalized_code}]'}

            # Check if this is a "Calificación" header or a sub-group title
            is_qualification_header = title.lower().startswith('calificaci')

            if is_qualification_header:
                # This is just a skill level header, not a sub-group
                current_unit = {'code': normalized_code, 'qualification': qualification, 'title': title}
                current_subgroup = {'code': '', 'title': ''}
                subgroup_counter = 0
                occupation_counter = 0
                print(f"      Unit: {normalized_code} ({title})")
            else:
                # This is a sub-group under the current unit
                # If unit code changed, reset counter
                if normalized_code != current_unit['code']:
                    current_unit = {'code': normalized_code, 'qualification': qualification, 'title': ''}
                    subgroup_counter = 0

                subgroup_counter += 1
                subgroup_code = f"{normalized_code}.{subgroup_counter:02d}"
                current_subgroup = {'code': subgroup_code, 'title': title}
                occupation_counter = 0
                print(f"        Subgroup: {subgroup_code} - {title[:40]}...")

            continue

        # OCCUPATION: "* administrador de sistemas"
        if line.startswith('*'):
            occupation = line.lstrip('* ').strip()

            if not occupation:
                continue

            # If we have a subgroup, use it
            if current_subgroup['code']:
                occupation_counter += 1
                occupation_code = f"{current_subgroup['code']}.{occupation_counter:03d}"

                data.append({
                    'major_code': current_major['code'],
                    'major_title_es': current_major['title'],
                    'submajor_code': current_submajor['code'],
                    'submajor_title_es': current_submajor['title'],
                    'minor_code': current_minor['code'],
                    'minor_title_es': current_minor['title'],
                    'unit_code': current_unit['code'],
                    'unit_qualification': current_unit['qualification'],
                    'subgroup_code': current_subgroup['code'],
                    'subgroup_title_es': current_subgroup['title'],
                    'occupation_code': occupation_code,
                    'occupation_es': occupation
                })
            elif current_unit['code']:
                # Occupation directly under unit (no subgroup)
                # Create implicit subgroup
                if subgroup_counter == 0:
                    subgroup_counter = 1
                    current_subgroup = {
                        'code': f"{current_unit['code']}.{subgroup_counter:02d}",
                        'title': current_unit['title']
                    }
                    occupation_counter = 0

                occupation_counter += 1
                occupation_code = f"{current_subgroup['code']}.{occupation_counter:03d}"

                data.append({
                    'major_code': current_major['code'],
                    'major_title_es': current_major['title'],
                    'submajor_code': current_submajor['code'],
                    'submajor_title_es': current_submajor['title'],
                    'minor_code': current_minor['code'],
                    'minor_title_es': current_minor['title'],
                    'unit_code': current_unit['code'],
                    'unit_qualification': current_unit['qualification'],
                    'subgroup_code': current_subgroup['code'],
                    'subgroup_title_es': current_subgroup['title'],
                    'occupation_code': occupation_code,
                    'occupation_es': occupation
                })

    return pd.DataFrame(data)


def main():
    """Main extraction function."""
    # Paths
    base_dir = Path(__file__).parent.parent  # argentina_cno2017/
    input_file = base_dir / 'data' / 'pdfs' / 'ARG_CNO_2017.txt'  # Raw text extract from PDF
    output_file = base_dir / 'data' / 'cno2017_extracted.xlsx'

    print(f"Reading from: {input_file}")

    with open(input_file, 'r', encoding='utf-8') as f:
        raw_text = f.read()

    print(f"\nExtracting CNO hierarchy...")
    df = extract_cno_hierarchy(raw_text)

    print(f"\n{'='*60}")
    print("EXTRACTION SUMMARY")
    print(f"{'='*60}")
    print(f"Total occupations: {len(df)}")
    print(f"Major categories: {df['major_code'].nunique()}")
    print(f"Submajor categories: {df['submajor_code'].nunique()}")
    print(f"Minor categories: {df['minor_code'].nunique()}")
    print(f"Unit groups (5-digit): {df['unit_code'].nunique()}")
    print(f"Subgroups: {df['subgroup_code'].nunique()}")

    # Qualification distribution
    print(f"\nQualification levels:")
    qual_counts = df['unit_qualification'].value_counts().sort_index()
    qual_names = {'1': 'Profesional', '2': 'Tecnica', '3': 'Operativa', '4': 'No calificada'}
    for q, count in qual_counts.items():
        print(f"  {q} ({qual_names.get(q, 'Unknown')}): {count}")

    # Save
    print(f"\nSaving to: {output_file}")
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='CNO_2017', index=False)

        # Adjust column widths
        worksheet = writer.sheets['CNO_2017']
        for idx, col in enumerate(df.columns):
            max_length = max(df[col].astype(str).apply(len).max(), len(col))
            width = min(max_length + 2, 60)
            col_letter = chr(65 + idx) if idx < 26 else chr(65 + idx // 26 - 1) + chr(65 + idx % 26)
            worksheet.column_dimensions[col_letter].width = width

        worksheet.freeze_panes = 'A2'

    print("Done!")

    return df


if __name__ == '__main__':
    main()
