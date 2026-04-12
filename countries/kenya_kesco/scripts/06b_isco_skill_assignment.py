"""
Alternative skill assignment using ISCO group pooling (no O*NET dependency).

Approach:
1. LLM selects relevant ISCO 4-digit groups for each new local occupation
2. Pool all ESCO skills from occupations in those groups
3. LLM filters candidates to the most relevant skills

Usage:
    python scripts/06b_isco_skill_assignment.py --occupations 1112_1 2352_1 5249_1 6111_1
    python scripts/06b_isco_skill_assignment.py --all
    python scripts/06b_isco_skill_assignment.py --occupations 1112_1 --dry-run
"""

import os
import json
import argparse
import pandas as pd
from pathlib import Path
from collections import defaultdict
from dotenv import load_dotenv
import google.generativeai as genai

BASE_PATH = Path(__file__).parent.parent
ROOT_PATH = BASE_PATH.parent.parent
SHARED_DATA = ROOT_PATH / "shared_data" / "esco_taxonomy"
OUTPUT_PATH = BASE_PATH / "outputs"

load_dotenv(ROOT_PATH / ".env")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-3-flash-preview")


def load_data() -> dict:
    """Load all required data sources."""
    print("Loading data...")

    # ISCO 4-digit groups
    groups_df = pd.read_csv(SHARED_DATA / "occupation_groups.csv")
    groups_4d = groups_df[groups_df["CODE"].str.len() == 4].copy()
    isco_groups = {}
    for _, row in groups_4d.iterrows():
        isco_groups[row["CODE"]] = {
            "code": row["CODE"],
            "label": row["PREFERREDLABEL"],
            "description": row.get("DESCRIPTION", ""),
        }
    print(f"  ISCO 4-digit groups: {len(isco_groups)}")

    # ESCO occupations
    esco_df = pd.read_csv(SHARED_DATA / "occupations.csv", low_memory=False)
    print(f"  ESCO occupations: {len(esco_df)}")

    # ESCO skill relations
    rels_df = pd.read_csv(SHARED_DATA / "occupation_to_skill_relations.csv", low_memory=False)
    occ_to_skills = defaultdict(set)
    for _, row in rels_df.iterrows():
        occ_to_skills[row["OCCUPATIONID"]].add(row["SKILLID"])
    print(f"  ESCO skill relations: {len(rels_df)}")

    # Build ISCO group -> occupation IDs
    group_to_occ_ids = defaultdict(list)
    for _, row in esco_df.iterrows():
        group_to_occ_ids[str(row["OCCUPATIONGROUPCODE"])].append(row["ID"])

    # Build ISCO group -> pooled skills
    group_to_skills = {}
    for code in isco_groups:
        skills = set()
        for oid in group_to_occ_ids.get(code, []):
            skills |= occ_to_skills.get(oid, set())
        group_to_skills[code] = skills

    # ESCO skills lookup
    skills_df = pd.read_csv(SHARED_DATA / "skills.csv")
    label_to_id = dict(zip(skills_df["PREFERREDLABEL"], skills_df["ID"]))
    id_to_label = dict(zip(skills_df["ID"], skills_df["PREFERREDLABEL"]))
    id_to_info = {}
    for _, row in skills_df.iterrows():
        id_to_info[row["ID"]] = {
            "id": row["ID"],
            "label": row["PREFERREDLABEL"],
            "skill_type": row.get("SKILLTYPE", ""),
        }
    print(f"  ESCO skills: {len(skills_df)}")

    # New local occupations
    local_df = pd.read_csv(OUTPUT_PATH / "new_local_occupations.csv")
    local_occs = {}
    for _, row in local_df.iterrows():
        local_occs[str(row["CODE"])] = {
            "code": str(row["CODE"]),
            "label": row["PREFERREDLABEL"],
            "alt_labels": row.get("ALTLABELS", ""),
            "description": row.get("DESCRIPTION", ""),
            "group_code": str(row["OCCUPATIONGROUPCODE"]),
        }
    print(f"  New local occupations: {len(local_occs)}")

    return {
        "isco_groups": isco_groups,
        "group_to_skills": group_to_skills,
        "group_to_occ_ids": group_to_occ_ids,
        "label_to_id": label_to_id,
        "id_to_label": id_to_label,
        "id_to_info": id_to_info,
        "local_occs": local_occs,
    }


def select_isco_groups(occupation: dict, data: dict) -> list[str]:
    """Use LLM to select relevant ISCO 4-digit groups for an occupation."""

    isco_groups = data["isco_groups"]
    group_to_skills = data["group_to_skills"]

    # Build numbered list of all ISCO groups (only those with skills)
    group_lines = []
    group_codes_ordered = []
    for i, (code, info) in enumerate(sorted(isco_groups.items())):
        if len(group_to_skills.get(code, set())) == 0:
            continue
        # Truncate description for prompt size
        desc = info["description"][:200].split("\n")[0] if info["description"] else ""
        group_lines.append(f"{code} - {info['label']}: {desc}")
        group_codes_ordered.append(code)

    group_list = "\n".join(group_lines)

    prompt = f"""You are selecting ISCO-08 4-digit occupation groups that are relevant to a local occupation in Kenya.

OCCUPATION:
- Label: {occupation['label']}
- Description: {occupation['description']}
- Alt labels: {occupation.get('alt_labels', 'None')}
- Assigned ISCO group: {occupation['group_code']}

TASK: Select ALL ISCO 4-digit groups whose occupations would share relevant skills with this occupation. Include:
- The occupation's own ISCO group (if it has ESCO occupations)
- Other groups where the core work overlaps (e.g. an auditor general also does financial auditing work from group 2411)
- Groups covering secondary duties or required knowledge domains

Do NOT include groups that are only tangentially related.
Target 2-6 groups.

ISCO 4-DIGIT GROUPS:
{group_list}

Return ONLY the 4-digit codes as a comma-separated list.
Example: 1112, 2411, 2413

SELECTED GROUPS:"""

    response = model.generate_content(prompt)
    text = response.text.strip()

    # Parse codes
    selected = []
    for part in text.replace("\n", ",").split(","):
        code = part.strip()
        if code in isco_groups and len(group_to_skills.get(code, set())) > 0:
            selected.append(code)

    return selected


def select_skills_with_llm(
    occupation: dict,
    candidates: list[dict],
    isco_codes: list[str],
    data: dict,
) -> list[int]:
    """Use LLM to select the most relevant skills from candidates."""

    isco_groups = data["isco_groups"]
    isco_context = "\n".join([
        f"  - {code}: {isco_groups[code]['label']}"
        for code in isco_codes if code in isco_groups
    ])

    # Build numbered candidate list with source group
    skill_lines = []
    for i, c in enumerate(candidates):
        source_labels = [isco_groups.get(s, {}).get("label", s) for s in list(c["sources"])[:2]]
        source_str = ", ".join(source_labels)
        skill_lines.append(f"{i+1}. {c['label']} [from: {source_str}]")
    skill_list = "\n".join(skill_lines)

    home_group = occupation.get("group_code", "")
    home_label = isco_groups.get(home_group, {}).get("label", home_group)

    prompt = f"""You are selecting ESCO skills for a local occupation in the Kenya national taxonomy.

OCCUPATION:
- Label: {occupation['label']}
- Description: {occupation['description']}
- Alt labels: {occupation.get('alt_labels', 'None')}
- Home ISCO group: {home_group} - {home_label}

RELEVANT ISCO GROUPS:
{isco_context}

CANDIDATE SKILLS ({len(candidates)} total, pooled from ESCO occupations in the groups above):
{skill_list}

Select ONLY the skills that are directly relevant to the duties of this specific occupation. Guidelines:
- Target 25-50 skills
- The home ISCO group ({home_group} - {home_label}) defines the seniority level and nature of the role. Skills from this group reflect what this person actually does day-to-day.
- The other groups provide domain expertise that this person leads, oversees, or needs knowledge of. Select domain skills at a strategic/oversight level, not at a hands-on practitioner level.
- For example, an auditor general (ISCO 1112) should get leadership and governance skills from their home group, plus financial audit *knowledge* from group 2411 - but not the hands-on audit execution skills that their staff would perform.
- When in doubt, leave it out

Return ONLY the numbers of selected skills as a comma-separated list.
Example: 1, 3, 5, 8, 12, 15

SELECTED SKILLS:"""

    response = model.generate_content(prompt)
    text = response.text.strip()

    selected = []
    for part in text.replace("\n", ",").split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(candidates):
                selected.append(idx)

    return selected


def main():
    parser = argparse.ArgumentParser(description="ISCO-based skill assignment")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--occupations", nargs="+", help="Occupation codes to process")
    group.add_argument("--all", action="store_true", help="Process all new local occupations")
    parser.add_argument("--dry-run", action="store_true", help="Skip LLM skill selection")
    args = parser.parse_args()

    print("=" * 70)
    print("ISCO GROUP-BASED SKILL ASSIGNMENT")
    print("=" * 70)

    data = load_data()

    if args.all:
        occ_codes = sorted(data["local_occs"].keys())
        print(f"\nProcessing all {len(occ_codes)} local occupations")
    else:
        occ_codes = args.occupations

    results = []

    for occ_code in occ_codes:
        if occ_code not in data["local_occs"]:
            print(f"\nSKIP: {occ_code} not found")
            continue

        occupation = data["local_occs"][occ_code]
        print(f"\n{'='*70}")
        print(f"OCCUPATION: {occ_code} - {occupation['label']}")
        print(f"{'='*70}")

        # Step 1: LLM selects relevant ISCO groups
        print("\nStep 1: Selecting relevant ISCO groups...")
        isco_codes = select_isco_groups(occupation, data)
        for code in isco_codes:
            g = data["isco_groups"].get(code, {})
            n_skills = len(data["group_to_skills"].get(code, set()))
            print(f"  -> {code}: {g.get('label', '?')} ({n_skills} skills)")

        if not isco_codes:
            print("  WARNING: No ISCO groups selected")
            continue

        # Step 2: Pool skills from all occupations in selected groups
        print("\nStep 2: Pooling skills from selected ISCO groups...")
        skill_sources = defaultdict(set)  # skill_id -> set of source ISCO codes
        for code in isco_codes:
            for skill_id in data["group_to_skills"].get(code, set()):
                skill_sources[skill_id].add(code)

        # Build candidate list
        candidates = []
        for skill_id, sources in skill_sources.items():
            info = data["id_to_info"].get(skill_id, {})
            if not info:
                continue
            candidates.append({
                "skill_id": skill_id,
                "label": info["label"],
                "skill_type": info.get("skill_type", ""),
                "sources": sources,
                "n_sources": len(sources),
            })

        # Sort by number of source groups (more evidence = better)
        candidates.sort(key=lambda x: (-x["n_sources"], x["label"]))
        print(f"  Candidate skills: {len(candidates)}")

        if not candidates:
            print("  WARNING: No candidate skills found")
            continue

        # Step 3: LLM selection
        if args.dry_run:
            print(f"\n[DRY RUN] Would select from {len(candidates)} candidates")
            results.append({
                "occupation": occupation,
                "isco_codes": isco_codes,
                "candidates": candidates,
                "selected_indices": [],
            })
            continue

        print(f"\nStep 3: LLM selecting from {len(candidates)} candidates...")
        selected_indices = select_skills_with_llm(occupation, candidates, isco_codes, data)
        selected = [candidates[i] for i in selected_indices]
        print(f"  Selected: {len(selected)} skills")

        results.append({
            "occupation": occupation,
            "isco_codes": isco_codes,
            "candidates": candidates,
            "selected_indices": selected_indices,
        })

    # Generate comparison report
    if results:
        generate_report(results, data, args.dry_run)


def generate_report(results: list[dict], data: dict, dry_run: bool) -> None:
    """Generate Excel comparison report."""

    output_file = OUTPUT_PATH / "isco_skill_comparison.xlsx"

    # Load O*NET pipeline results for comparison
    onet_rels_file = OUTPUT_PATH / "new_local_skill_relations.csv"
    onet_skills_by_occ = defaultdict(set)
    if onet_rels_file.exists():
        onet_df = pd.read_csv(onet_rels_file)
        occ_df = pd.read_csv(OUTPUT_PATH / "taxonomy" / "occupations.csv", low_memory=False)
        id_to_code = dict(zip(occ_df["ID"], occ_df["CODE"].astype(str)))
        for _, row in onet_df.iterrows():
            code = id_to_code.get(row["OCCUPATIONID"], "")
            onet_skills_by_occ[code].add(row["SKILLID"])

    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        summary_rows = []
        for r in results:
            occ = r["occupation"]
            isco_labels = [data["isco_groups"].get(c, {}).get("label", c) for c in r["isco_codes"]]

            selected_ids = set()
            if r["selected_indices"]:
                selected_ids = {r["candidates"][i]["skill_id"] for i in r["selected_indices"]}

            onet_ids = onet_skills_by_occ.get(occ["code"], set())
            overlap = selected_ids & onet_ids

            summary_rows.append({
                "Code": occ["code"],
                "Occupation": occ["label"],
                "ISCO Groups": " | ".join(isco_labels),
                "Candidates": len(r["candidates"]),
                "ISCO Selected": len(selected_ids) if not dry_run else "DRY RUN",
                "O*NET Selected": len(onet_ids),
                "Overlap": len(overlap) if not dry_run else "N/A",
                "Only ISCO": len(selected_ids - onet_ids) if not dry_run else "N/A",
                "Only O*NET": len(onet_ids - selected_ids) if not dry_run else "N/A",
            })

            # Detail sheet
            rows = []
            for i, c in enumerate(r["candidates"]):
                in_isco = i in r["selected_indices"] if r["selected_indices"] else None
                in_onet = c["skill_id"] in onet_ids
                source_labels = [data["isco_groups"].get(s, {}).get("label", s) for s in list(c["sources"])[:3]]

                rows.append({
                    "Selected": "YES" if in_isco else "",
                    "In O*NET": "YES" if in_onet else "",
                    "Skill Label": c["label"],
                    "Source Groups": len(c["sources"]),
                    "Skill Type": c["skill_type"],
                    "Source ISCO": ", ".join(source_labels),
                })
            rows.sort(key=lambda x: (0 if x["Selected"] == "YES" else 1, -x["Source Groups"]))

            safe = (occ["code"] + "_" + occ["label"][:20]).replace("/", "_").replace(chr(92), "_")[:31]
            pd.DataFrame(rows).to_excel(writer, sheet_name=safe, index=False)

        pd.DataFrame(summary_rows).to_excel(writer, sheet_name="Summary", index=False)

    print(f"\nReport saved: {output_file}")


if __name__ == "__main__":
    main()
