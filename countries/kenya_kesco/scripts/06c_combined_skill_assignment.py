"""
Combined skill assignment using ISCO group pooling + O*NET crosswalk.

Merges candidate pools from both approaches, then LLM filters with
a home-group-aware prompt that distinguishes leadership from practitioner skills.

Usage:
    python scripts/06c_combined_skill_assignment.py --occupations 1112_1 2352_1 5249_1 6111_1
    python scripts/06c_combined_skill_assignment.py --all
"""

import os
import json
import argparse
import numpy as np
import pandas as pd
from pathlib import Path
from collections import defaultdict
from dotenv import load_dotenv
import google.generativeai as genai

BASE_PATH = Path(__file__).parent.parent
ROOT_PATH = BASE_PATH.parent.parent
SHARED_DATA = ROOT_PATH / "shared_data" / "esco_taxonomy"
SHARED_ROOT = ROOT_PATH / "shared_data"
OUTPUT_PATH = BASE_PATH / "outputs"
ONET_PATH = ROOT_PATH.parent / "ONET"
ONET_DB = ONET_PATH / "db_30_1" / "db_30_1_text"

load_dotenv(ROOT_PATH / ".env")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-3-flash-preview")


def load_data() -> dict:
    """Load all required data sources."""
    print("Loading data...")

    # --- ISCO side ---
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

    esco_occ_df = pd.read_csv(SHARED_DATA / "occupations.csv", low_memory=False)
    esco_rels_df = pd.read_csv(SHARED_DATA / "occupation_to_skill_relations.csv", low_memory=False)
    occ_to_skills = defaultdict(set)
    for _, row in esco_rels_df.iterrows():
        occ_to_skills[row["OCCUPATIONID"]].add(row["SKILLID"])

    group_to_occ_ids = defaultdict(list)
    for _, row in esco_occ_df.iterrows():
        group_to_occ_ids[str(row["OCCUPATIONGROUPCODE"])].append(row["ID"])

    group_to_skills = {}
    for code in isco_groups:
        skills = set()
        for oid in group_to_occ_ids.get(code, []):
            skills |= occ_to_skills.get(oid, set())
        group_to_skills[code] = skills
    print(f"  ESCO skill relations: {len(esco_rels_df)}")

    # --- O*NET side ---
    onet_emb_file = SHARED_ROOT / "onet_embeddings_gemini.json"
    with open(onet_emb_file, "r", encoding="utf-8") as f:
        onet_emb_data = json.load(f)
    onet_emb_matrix = np.array([item["embedding"] for item in onet_emb_data["occupations"]])
    onet_emb_codes = [item["onet_code"] for item in onet_emb_data["occupations"]]
    print(f"  O*NET embeddings: {len(onet_emb_codes)}")

    onet_occs = pd.read_csv(ONET_DB / "Occupation Data.txt", sep="\t")
    onet_lookup = {}
    for _, row in onet_occs.iterrows():
        onet_lookup[row["O*NET-SOC Code"]] = row["Title"]

    onet_tasks = pd.read_csv(ONET_DB / "Task Statements.txt", sep="\t")
    occ_to_task_ids = defaultdict(set)
    for _, row in onet_tasks.iterrows():
        occ_to_task_ids[row["O*NET-SOC Code"]].add(str(row["Task ID"]))

    # --- Skills (needed before crosswalk for ID mapping) ---
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

    crosswalk = pd.read_parquet(ONET_PATH / "prune_skill_to_onet_task_edges.parquet")
    crosswalk = crosswalk[crosswalk["is_valid"] == True].copy()
    crosswalk["task_id"] = crosswalk["onet_task_code"].str.split(":").str[2]
    task_to_esco = defaultdict(list)
    for _, row in crosswalk.iterrows():
        # Crosswalk uses different IDs; map via label to taxonomy ID
        tax_id = label_to_id.get(row["esco_skill_label"])
        if tax_id:
            task_to_esco[row["task_id"]].append({
                "label": row["esco_skill_label"],
                "skill_id": tax_id,
            })
    print(f"  O*NET crosswalk valid edges: {len(crosswalk)}")

    # Local embeddings
    local_emb_file = OUTPUT_PATH / "new_local_embeddings.json"
    with open(local_emb_file, "r", encoding="utf-8") as f:
        local_emb_data = json.load(f)
    local_embeddings = {
        item["code"]: np.array(item["embedding"])
        for item in local_emb_data["occupations"]
    }

    # --- Local occupations ---
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
        "onet_emb_matrix": onet_emb_matrix,
        "onet_emb_codes": onet_emb_codes,
        "onet_lookup": onet_lookup,
        "occ_to_task_ids": occ_to_task_ids,
        "task_to_esco": task_to_esco,
        "local_embeddings": local_embeddings,
        "label_to_id": label_to_id,
        "id_to_label": id_to_label,
        "id_to_info": id_to_info,
        "local_occs": local_occs,
    }


def select_isco_groups(occupation: dict, data: dict) -> list[str]:
    """Use LLM to select relevant ISCO 4-digit groups."""
    isco_groups = data["isco_groups"]
    group_to_skills = data["group_to_skills"]

    group_lines = []
    for code, info in sorted(isco_groups.items()):
        if len(group_to_skills.get(code, set())) == 0:
            continue
        desc = info["description"][:200].split("\n")[0] if info["description"] else ""
        group_lines.append(f"{code} - {info['label']}: {desc}")

    group_list = "\n".join(group_lines)

    prompt = f"""You are selecting ISCO-08 4-digit occupation groups that are relevant to a local occupation in Kenya.

OCCUPATION:
- Label: {occupation['label']}
- Description: {occupation['description']}
- Alt labels: {occupation.get('alt_labels', 'None')}
- Assigned ISCO group: {occupation['group_code']}

TASK: Select ALL ISCO 4-digit groups whose occupations would share relevant skills with this occupation. Include:
- The occupation's own ISCO group (if it has ESCO occupations)
- Other groups where the core work overlaps
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

    selected = []
    for part in text.replace("\n", ",").split(","):
        code = part.strip()
        if code in isco_groups and len(group_to_skills.get(code, set())) > 0:
            selected.append(code)

    return selected


def find_onet_matches(occupation: dict, data: dict) -> list[tuple[str, float]]:
    """Find closest O*NET occupations via embedding similarity."""
    onet_matrix = data["onet_emb_matrix"]
    onet_codes = data["onet_emb_codes"]
    local_embeddings = data["local_embeddings"]

    vec = local_embeddings.get(occupation["code"])
    if vec is None:
        return []

    norms = np.linalg.norm(onet_matrix, axis=1) * np.linalg.norm(vec)
    sims = np.dot(onet_matrix, vec) / np.maximum(norms, 1e-10)
    top5 = np.argsort(sims)[::-1][:5]

    matches = []
    for idx in top5:
        sim = float(sims[idx])
        if sim >= 0.70 or len(matches) < 2:
            matches.append((onet_codes[idx], sim))

    return matches


def get_onet_candidate_skills(onet_codes: list[str], data: dict) -> dict[str, set]:
    """Get ESCO skill IDs via O*NET task crosswalk. Returns skill_id -> source O*NET codes."""
    skill_sources = defaultdict(set)
    for code in onet_codes:
        task_ids = data["occ_to_task_ids"].get(code, set())
        for tid in task_ids:
            for edge in data["task_to_esco"].get(tid, []):
                skill_sources[edge["skill_id"]].add(code)
    return skill_sources


def build_combined_candidates(
    isco_codes: list[str],
    onet_codes: list[str],
    data: dict,
) -> list[dict]:
    """Merge ISCO and O*NET candidate pools into a single deduplicated list."""

    id_to_info = data["id_to_info"]
    isco_groups = data["isco_groups"]
    onet_lookup = data["onet_lookup"]
    group_to_skills = data["group_to_skills"]

    # Track sources per skill
    skill_meta = defaultdict(lambda: {"isco_sources": set(), "onet_sources": set()})

    # ISCO candidates
    for code in isco_codes:
        for skill_id in group_to_skills.get(code, set()):
            skill_meta[skill_id]["isco_sources"].add(code)

    # O*NET candidates
    onet_skill_sources = get_onet_candidate_skills(onet_codes, data)
    for skill_id, sources in onet_skill_sources.items():
        skill_meta[skill_id]["onet_sources"] = sources

    # Build combined list
    candidates = []
    for skill_id, meta in skill_meta.items():
        info = id_to_info.get(skill_id)
        if not info:
            continue

        # Build readable source string
        source_parts = []
        if meta["isco_sources"]:
            isco_labels = [isco_groups.get(c, {}).get("label", c) for c in sorted(meta["isco_sources"])]
            source_parts.append(f"ISCO: {', '.join(isco_labels[:2])}")
        if meta["onet_sources"]:
            onet_labels = [onet_lookup.get(c, c) for c in sorted(meta["onet_sources"])]
            source_parts.append(f"O*NET: {', '.join(onet_labels[:2])}")

        candidates.append({
            "skill_id": skill_id,
            "label": info["label"],
            "skill_type": info.get("skill_type", ""),
            "isco_sources": meta["isco_sources"],
            "onet_sources": meta["onet_sources"],
            "n_total_sources": len(meta["isco_sources"]) + len(meta["onet_sources"]),
            "source_str": " | ".join(source_parts),
            "in_both": bool(meta["isco_sources"] and meta["onet_sources"]),
        })

    # Sort: skills found in both pools first, then by total source count
    candidates.sort(key=lambda x: (-x["in_both"], -x["n_total_sources"], x["label"]))

    return candidates


def select_skills_with_llm(
    occupation: dict,
    candidates: list[dict],
    isco_codes: list[str],
    onet_codes: list[str],
    data: dict,
) -> list[int]:
    """Use LLM to select skills from the combined candidate pool."""

    isco_groups = data["isco_groups"]
    onet_lookup = data["onet_lookup"]
    home_group = occupation.get("group_code", "")
    home_label = isco_groups.get(home_group, {}).get("label", home_group)

    isco_context = "\n".join([
        f"  - {code}: {isco_groups[code]['label']}"
        for code in isco_codes if code in isco_groups
    ])
    onet_context = "\n".join([
        f"  - {onet_lookup.get(code, code)}"
        for code in onet_codes
    ])

    skill_lines = []
    for i, c in enumerate(candidates):
        skill_lines.append(f"{i+1}. {c['label']} [{c['source_str']}]")
    skill_list = "\n".join(skill_lines)

    prompt = f"""You are selecting ESCO skills for a local occupation in the Kenya national taxonomy.

OCCUPATION:
- Label: {occupation['label']}
- Description: {occupation['description']}
- Alt labels: {occupation.get('alt_labels', 'None')}
- Home ISCO group: {home_group} - {home_label}

RELEVANT ISCO GROUPS:
{isco_context}

MATCHED O*NET OCCUPATIONS:
{onet_context}

CANDIDATE SKILLS ({len(candidates)} total, pooled from ESCO occupations in the ISCO groups above AND from O*NET task crosswalks):
{skill_list}

Select skills that are relevant to this specific occupation in the Kenyan context. Guidelines:

1. SENIORITY: The home ISCO group ({home_group} - {home_label}) defines the seniority and nature of the role. For leadership roles, select strategic, oversight, and governance skills - not hands-on practitioner skills that subordinates would perform. For practitioner roles, select the practical working skills.

2. COMPLETENESS: Aim for 30-60 skills. A broad leadership role spanning multiple domains may reach 50-60. A narrow specialist role may only need 30-40. Prioritise coverage of all distinct skill areas over padding any single area with near-duplicates.

3. PROFESSIONAL VALUES: Include values and professional standards that are core to the role's identity (e.g. ethics, impartiality, confidentiality for an auditor general; duty of care for a healer).

4. DOMAIN KNOWLEDGE: Include knowledge areas this person needs, even if they don't practise them hands-on (e.g. an auditor general needs knowledge of accounting standards, even though they don't do bookkeeping).

5. EXCLUDE skills that belong to a clearly different occupational domain, even if they appeared in a related source occupation.

6. AVOID REDUNDANCY: If multiple candidate skills cover the same competency (e.g. "manage pest control" and "pest management techniques"), pick the one most relevant and skip the others.

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
    parser = argparse.ArgumentParser(description="Combined ISCO+O*NET skill assignment")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--occupations", nargs="+", help="Occupation codes to process")
    group.add_argument("--all", action="store_true", help="Process all new local occupations")
    parser.add_argument("--dry-run", action="store_true", help="Skip LLM skill selection")
    args = parser.parse_args()

    print("=" * 70)
    print("COMBINED ISCO + O*NET SKILL ASSIGNMENT")
    print("=" * 70)

    data = load_data()

    if args.all:
        occ_codes = sorted(data["local_occs"].keys())
        print(f"\nProcessing all {len(occ_codes)} local occupations")
    else:
        occ_codes = args.occupations

    # Load previous results for comparison
    prev_onet = defaultdict(set)
    prev_file = OUTPUT_PATH / "new_local_skill_relations.csv"
    if prev_file.exists():
        occ_df = pd.read_csv(OUTPUT_PATH / "taxonomy" / "occupations.csv", low_memory=False)
        id_to_code = dict(zip(occ_df["ID"], occ_df["CODE"].astype(str)))
        for _, row in pd.read_csv(prev_file).iterrows():
            code = id_to_code.get(row["OCCUPATIONID"], "")
            prev_onet[code].add(row["SKILLID"])

    results = []

    for occ_code in occ_codes:
        if occ_code not in data["local_occs"]:
            print(f"\nSKIP: {occ_code} not found")
            continue

        occupation = data["local_occs"][occ_code]
        print(f"\n{'='*70}")
        print(f"OCCUPATION: {occ_code} - {occupation['label']}")
        print(f"{'='*70}")

        # Step 1: Select ISCO groups
        print("\nStep 1: Selecting relevant ISCO groups...")
        isco_codes = select_isco_groups(occupation, data)
        for code in isco_codes:
            g = data["isco_groups"].get(code, {})
            n = len(data["group_to_skills"].get(code, set()))
            print(f"  -> {code}: {g.get('label', '?')} ({n} skills)")

        # Step 2: Find O*NET matches
        print("\nStep 2: Finding O*NET matches...")
        onet_matches = find_onet_matches(occupation, data)
        onet_codes = [code for code, _ in onet_matches]
        for code, sim in onet_matches:
            print(f"  -> {data['onet_lookup'].get(code, code)} (sim={sim:.3f})")

        # Step 3: Build combined candidate pool
        print("\nStep 3: Building combined candidate pool...")
        candidates = build_combined_candidates(isco_codes, onet_codes, data)
        n_both = sum(1 for c in candidates if c["in_both"])
        n_isco_only = sum(1 for c in candidates if c["isco_sources"] and not c["onet_sources"])
        n_onet_only = sum(1 for c in candidates if c["onet_sources"] and not c["isco_sources"])
        print(f"  Total candidates: {len(candidates)}")
        print(f"    In both pools: {n_both}")
        print(f"    ISCO only: {n_isco_only}")
        print(f"    O*NET only: {n_onet_only}")

        if not candidates:
            print("  WARNING: No candidates found")
            continue

        # Step 4: LLM selection
        if args.dry_run:
            print(f"\n[DRY RUN] Would select from {len(candidates)} candidates")
            results.append({
                "occupation": occupation,
                "isco_codes": isco_codes,
                "onet_codes": onet_codes,
                "candidates": candidates,
                "selected_indices": [],
            })
            continue

        print(f"\nStep 4: LLM selecting from {len(candidates)} candidates...")
        selected_indices = select_skills_with_llm(
            occupation, candidates, isco_codes, onet_codes, data
        )
        selected = [candidates[i] for i in selected_indices]
        n_from_both = sum(1 for c in selected if c["in_both"])
        n_from_isco = sum(1 for c in selected if c["isco_sources"] and not c["onet_sources"])
        n_from_onet = sum(1 for c in selected if c["onet_sources"] and not c["isco_sources"])
        print(f"  Selected: {len(selected)} skills")
        print(f"    From both pools: {n_from_both}")
        print(f"    ISCO only: {n_from_isco}")
        print(f"    O*NET only: {n_from_onet}")

        results.append({
            "occupation": occupation,
            "isco_codes": isco_codes,
            "onet_codes": onet_codes,
            "candidates": candidates,
            "selected_indices": selected_indices,
        })

    if results:
        generate_report(results, prev_onet, data, args.dry_run)


def generate_report(
    results: list[dict],
    prev_onet: dict,
    data: dict,
    dry_run: bool,
) -> None:
    """Generate Excel comparison report."""

    output_file = OUTPUT_PATH / "combined_skill_comparison.xlsx"
    isco_groups = data["isco_groups"]
    onet_lookup = data["onet_lookup"]

    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        summary_rows = []
        for r in results:
            occ = r["occupation"]
            selected_ids = set()
            if r["selected_indices"]:
                selected_ids = {r["candidates"][i]["skill_id"] for i in r["selected_indices"]}

            prev_ids = prev_onet.get(occ["code"], set())
            overlap = selected_ids & prev_ids

            isco_labels = [isco_groups.get(c, {}).get("label", c) for c in r["isco_codes"]]
            onet_labels = [onet_lookup.get(c, c) for c in r["onet_codes"]]

            summary_rows.append({
                "Code": occ["code"],
                "Occupation": occ["label"],
                "ISCO Groups": " | ".join(isco_labels),
                "O*NET Matches": " | ".join(onet_labels),
                "Candidates": len(r["candidates"]),
                "Combined Selected": len(selected_ids) if not dry_run else "DRY RUN",
                "Prev O*NET Selected": len(prev_ids),
                "Overlap": len(overlap) if not dry_run else "N/A",
            })

            # Detail sheet
            rows = []
            for i, c in enumerate(r["candidates"]):
                is_sel = i in r["selected_indices"] if r["selected_indices"] else None
                in_prev = c["skill_id"] in prev_ids

                rows.append({
                    "Selected": "YES" if is_sel else "",
                    "In Prev O*NET": "YES" if in_prev else "",
                    "Skill Label": c["label"],
                    "In Both Pools": "YES" if c["in_both"] else "",
                    "Sources": c["source_str"],
                    "Skill Type": c["skill_type"],
                })
            rows.sort(key=lambda x: (0 if x["Selected"] == "YES" else 1, x["Skill Label"]))

            safe = (occ["code"] + "_" + occ["label"][:20]).replace("/", "_").replace(chr(92), "_")[:31]
            pd.DataFrame(rows).to_excel(writer, sheet_name=safe, index=False)

        pd.DataFrame(summary_rows).to_excel(writer, sheet_name="Summary", index=False)

    print(f"\nReport saved: {output_file}")


if __name__ == "__main__":
    main()
