"""
Assign skills to new local occupations using O*NET task-based crosswalk.

Approach:
1. Semantic embedding match to find the closest O*NET occupation(s) for each local occupation
2. Get those occupations' task IDs from O*NET
3. Use the ESCO-to-O*NET-task crosswalk (prune files) to find candidate ESCO skills
   via direct task ID matching (not DWA-level, which is too broad)
4. Use Gemini to filter candidates to the most relevant skills

Prerequisites:
    python shared_data/generate_onet_embeddings.py

Usage:
    python scripts/07_onet_skill_assignment.py --occupations 1112_1 2352_1 5249_1 6111_1
    python scripts/07_onet_skill_assignment.py --all
    python scripts/07_onet_skill_assignment.py --occupations 1112_1 --dry-run
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
ONET_EMBEDDINGS_FILE = SHARED_ROOT / "onet_embeddings_gemini.json"

load_dotenv(ROOT_PATH / ".env")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-3-flash-preview")


def load_data() -> dict:
    """Load all required data sources."""
    print("Loading data...")

    # O*NET occupations
    onet_occs = pd.read_csv(ONET_DB / "Occupation Data.txt", sep="\t")
    print(f"  O*NET occupations: {len(onet_occs)}")

    # O*NET embeddings
    if not ONET_EMBEDDINGS_FILE.exists():
        raise FileNotFoundError(
            f"O*NET embeddings not found: {ONET_EMBEDDINGS_FILE}\n"
            "Run: python shared_data/generate_onet_embeddings.py"
        )
    with open(ONET_EMBEDDINGS_FILE, 'r', encoding='utf-8') as f:
        onet_emb_data = json.load(f)
    onet_emb_items = onet_emb_data['occupations']
    onet_emb_matrix = np.array([item['embedding'] for item in onet_emb_items])
    onet_emb_codes = [item['onet_code'] for item in onet_emb_items]
    print(f"  O*NET embeddings: {len(onet_emb_items)} ({onet_emb_matrix.shape[1]} dims)")

    # New local occupation embeddings
    if not NEW_LOCAL_EMBEDDINGS.exists():
        raise FileNotFoundError(
            f"New local embeddings not found: {NEW_LOCAL_EMBEDDINGS}\n"
            "Run: python scripts/05_create_new_local.py embed"
        )
    with open(NEW_LOCAL_EMBEDDINGS, 'r', encoding='utf-8') as f:
        local_emb_data = json.load(f)
    local_embeddings = {
        item['code']: np.array(item['embedding'])
        for item in local_emb_data['occupations']
    }
    print(f"  New local embeddings: {len(local_embeddings)}")

    # O*NET tasks
    onet_tasks = pd.read_csv(ONET_DB / "Task Statements.txt", sep="\t")
    print(f"  O*NET tasks: {len(onet_tasks)}")

    # ESCO-to-O*NET crosswalk (valid edges only)
    crosswalk = pd.read_parquet(ONET_PATH / "prune_skill_to_onet_task_edges.parquet")
    crosswalk = crosswalk[crosswalk["is_valid"] == True].copy()
    crosswalk["task_id"] = crosswalk["onet_task_code"].str.split(":").str[2]
    print(f"  Crosswalk valid edges: {len(crosswalk)}")

    # Build task_id -> ESCO skills lookup
    task_to_esco = defaultdict(list)
    for _, row in crosswalk.iterrows():
        task_to_esco[row["task_id"]].append({
            "label": row["esco_skill_label"],
            "crosswalk_id": row["esco_skill_id"],
            "cosine_similarity": row["best_cosine_similarity"],
            "onet_task_title": row["onet_semantic_title"],
        })
    print(f"  Tasks with ESCO mappings: {len(task_to_esco)}")

    # ESCO taxonomy skills (for ID mapping: label -> taxonomy ID)
    esco_skills = pd.read_csv(SHARED_DATA / "skills.csv")
    label_to_id = dict(zip(esco_skills["PREFERREDLABEL"], esco_skills["ID"]))
    label_to_info = {}
    for _, row in esco_skills.iterrows():
        label_to_info[row["PREFERREDLABEL"]] = {
            "id": row["ID"],
            "label": row["PREFERREDLABEL"],
            "description": row.get("DESCRIPTION", ""),
            "skill_type": row.get("SKILLTYPE", ""),
        }
    print(f"  ESCO skills: {len(esco_skills)}")

    # New local occupations
    local_df = pd.read_csv(OUTPUT_PATH / "new_local_occupations.csv")
    local_occs = {}
    for _, row in local_df.iterrows():
        local_occs[str(row["CODE"])] = {
            "code": str(row["CODE"]),
            "label": row["PREFERREDLABEL"],
            "alt_labels": row.get("ALTLABELS", ""),
            "description": row.get("DESCRIPTION", ""),
            "group_code": row["OCCUPATIONGROUPCODE"],
        }
    print(f"  New local occupations: {len(local_occs)}")

    # Build O*NET occupation -> task IDs and task details
    occ_to_task_ids = defaultdict(set)
    occ_to_tasks = defaultdict(list)
    for _, row in onet_tasks.iterrows():
        task_id = str(row["Task ID"])
        occ_to_task_ids[row["O*NET-SOC Code"]].add(task_id)
        occ_to_tasks[row["O*NET-SOC Code"]].append({
            "task_id": task_id,
            "task": row["Task"],
            "task_type": row.get("Task Type", ""),
        })

    # Build O*NET lookup by code
    onet_lookup = {}
    for _, row in onet_occs.iterrows():
        code = row["O*NET-SOC Code"]
        onet_lookup[code] = {
            "code": code,
            "title": row["Title"],
            "description": row["Description"],
        }

    return {
        "onet_lookup": onet_lookup,
        "onet_occs": onet_occs,
        "onet_emb_matrix": onet_emb_matrix,
        "onet_emb_codes": onet_emb_codes,
        "local_embeddings": local_embeddings,
        "occ_to_task_ids": occ_to_task_ids,
        "occ_to_tasks": occ_to_tasks,
        "task_to_esco": task_to_esco,
        "label_to_id": label_to_id,
        "label_to_info": label_to_info,
        "local_occs": local_occs,
    }


NEW_LOCAL_EMBEDDINGS = OUTPUT_PATH / "new_local_embeddings.json"


def find_onet_matches(
    occupation: dict,
    data: dict,
    top_k: int = 5,
    sim_threshold: float = 0.70,
) -> list[tuple[str, float]]:
    """Find closest O*NET occupations using pre-generated embedding similarity.

    Returns list of (onet_code, similarity_score) tuples.
    Takes top_k candidates above sim_threshold, minimum 2.
    """
    onet_matrix = data["onet_emb_matrix"]
    onet_codes = data["onet_emb_codes"]
    local_embeddings = data["local_embeddings"]

    # Look up pre-generated embedding for this occupation
    occ_code = occupation["code"]
    if occ_code not in local_embeddings:
        raise ValueError(
            f"No embedding found for {occ_code}. "
            "Run: python scripts/05_create_new_local.py embed"
        )
    query_vec = local_embeddings[occ_code]

    # Cosine similarity
    norms = np.linalg.norm(onet_matrix, axis=1) * np.linalg.norm(query_vec)
    similarities = np.dot(onet_matrix, query_vec) / np.maximum(norms, 1e-10)

    # Get top_k indices
    top_indices = np.argsort(similarities)[::-1][:top_k]

    # Filter by threshold, but always keep at least 2
    matches = []
    for idx in top_indices:
        code = onet_codes[idx]
        sim = float(similarities[idx])
        if sim >= sim_threshold or len(matches) < 2:
            matches.append((code, sim))

    return matches


def get_candidate_skills_from_onet(
    onet_codes: list[str],
    data: dict,
) -> tuple[list[dict], dict]:
    """Get ESCO skills via O*NET occupation -> tasks -> crosswalk (task-level matching)."""

    occ_to_task_ids = data["occ_to_task_ids"]
    task_to_esco = data["task_to_esco"]
    onet_lookup = data["onet_lookup"]
    label_to_info = data["label_to_info"]

    # Collect all task IDs from matched O*NET occupations
    all_task_ids = set()
    task_source = {}  # Track which O*NET occupation each task came from
    for code in onet_codes:
        task_ids = occ_to_task_ids.get(code, set())
        for tid in task_ids:
            all_task_ids.add(tid)
            if tid not in task_source:
                task_source[tid] = code

    # Get ESCO skills via crosswalk at the task level
    skill_scores = defaultdict(lambda: {"max_sim": 0, "sources": set(), "tasks": set()})
    for task_id in all_task_ids:
        esco_edges = task_to_esco.get(task_id, [])
        for edge in esco_edges:
            label = edge["label"]
            skill_scores[label]["max_sim"] = max(
                skill_scores[label]["max_sim"], edge["cosine_similarity"]
            )
            skill_scores[label]["sources"].add(task_source.get(task_id, "unknown"))
            skill_scores[label]["tasks"].add(task_id)

    # Build candidate list with metadata
    candidates = []
    for label, info in skill_scores.items():
        if label in label_to_info:
            skill_info = label_to_info[label]
            candidates.append({
                "label": label,
                "taxonomy_id": skill_info["id"],
                "description": skill_info.get("description", ""),
                "skill_type": skill_info.get("skill_type", ""),
                "max_cosine_sim": info["max_sim"],
                "n_onet_sources": len(info["sources"]),
                "n_tasks": len(info["tasks"]),
                "onet_sources": list(info["sources"]),
            })

    # Sort by number of supporting tasks (more evidence = better), then similarity
    candidates.sort(key=lambda x: (-x["n_tasks"], -x["max_cosine_sim"]))

    # Stats
    stats = {
        "n_onet_occupations": len(onet_codes),
        "n_tasks": len(all_task_ids),
        "n_tasks_in_crosswalk": len([t for t in all_task_ids if t in task_to_esco]),
        "n_candidate_skills": len(candidates),
    }

    return candidates, stats


def select_skills_with_llm(
    occupation: dict,
    candidates: list[dict],
    onet_codes: list[str],
    data: dict,
) -> list[int]:
    """Use Gemini to select the most relevant skills from candidates."""

    onet_lookup = data["onet_lookup"]
    onet_context = "\n".join([
        f"  - {code}: {onet_lookup.get(code, {}).get('title', 'Unknown')}"
        for code in onet_codes
    ])

    # Build numbered candidate list with source O*NET occupation
    onet_titles = {
        code: onet_lookup.get(code, {}).get('title', code) for code in onet_codes
    }
    skill_lines = []
    for i, c in enumerate(candidates):
        # Show which O*NET occupation(s) this skill came from
        sources = [onet_titles.get(s, s) for s in c['onet_sources']]
        source_str = sources[0] if len(sources) == 1 else f"{sources[0]} + {len(sources)-1} more"
        skill_lines.append(f"{i+1}. {c['label']} [from: {source_str}]")
    skill_list = "\n".join(skill_lines)

    prompt = f"""You are selecting ESCO skills for a local occupation in the Kenya national taxonomy.

OCCUPATION:
- Label: {occupation['label']}
- Description: {occupation['description']}
- Alt labels: {occupation.get('alt_labels', 'None')}

MATCHED O*NET OCCUPATIONS (ranked by similarity to this occupation):
{onet_context}

CANDIDATE SKILLS ({len(candidates)} total, sourced from the O*NET occupations above):
{skill_list}

Select ONLY the skills that are directly relevant to the duties of this specific occupation. Guidelines:
- Target 25-50 skills
- Prioritise skills from the closest-matching O*NET occupation (listed first above)
- Include both specific technical skills and relevant knowledge areas
- Exclude skills that belong to a different occupational domain, even if they appeared in a related O*NET occupation
- When in doubt, leave it out

Return ONLY the numbers of selected skills as a comma-separated list.
Example: 1, 3, 5, 8, 12, 15

SELECTED SKILLS:"""

    response = model.generate_content(prompt)
    text = response.text.strip()

    # Parse numbers
    selected = []
    for part in text.replace("\n", ",").split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(candidates):
                selected.append(idx)

    return selected


def main():
    parser = argparse.ArgumentParser(description="O*NET-based skill assignment")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--occupations", nargs="+", help="Occupation codes to process")
    group.add_argument("--all", action="store_true", help="Process all new local occupations")
    parser.add_argument("--dry-run", action="store_true", help="Skip LLM skill selection")
    args = parser.parse_args()

    print("=" * 70)
    print("O*NET TASK-BASED SKILL ASSIGNMENT")
    print("=" * 70)

    data = load_data()

    # Also load existing skill-group pipeline results for comparison
    existing_relations_file = OUTPUT_PATH / "new_local_skill_relations.csv"
    existing_skills = defaultdict(set)
    if existing_relations_file.exists():
        existing_df = pd.read_csv(existing_relations_file)
        for _, row in existing_df.iterrows():
            existing_skills[str(row["OCCUPATIONID"])].add(row["SKILLID"])
        print(f"\nLoaded existing skill-group pipeline results: {len(existing_df)} relations")

    # Determine which occupations to process
    if args.all:
        occ_codes_to_process = sorted(data["local_occs"].keys())
        print(f"\nProcessing all {len(occ_codes_to_process)} local occupations")
    else:
        occ_codes_to_process = args.occupations

    results = []

    for occ_code in occ_codes_to_process:
        if occ_code not in data["local_occs"]:
            print(f"\nSKIP: {occ_code} not found in local occupations")
            continue

        occupation = data["local_occs"][occ_code]
        print(f"\n{'='*70}")
        print(f"OCCUPATION: {occ_code} - {occupation['label']}")
        print(f"Description: {occupation['description'][:120]}...")
        print(f"{'='*70}")

        # Step 1: Find O*NET matches via semantic similarity
        print("\nStep 1: Finding O*NET matches (semantic)...")
        onet_matches = find_onet_matches(occupation, data)
        onet_codes = [code for code, _ in onet_matches]
        for code, sim in onet_matches:
            onet_occ = data["onet_lookup"].get(code, {})
            print(f"  -> {code}: {onet_occ.get('title', 'UNKNOWN')} (sim={sim:.3f})")

        if not onet_codes:
            print("  WARNING: No O*NET matches found")
            continue

        # Step 2: Get candidate ESCO skills via task-level crosswalk
        print("\nStep 2: Getting candidate skills via task-level crosswalk...")
        candidates, stats = get_candidate_skills_from_onet(onet_codes, data)
        print(f"  Tasks from O*NET: {stats['n_tasks']} ({stats['n_tasks_in_crosswalk']} in crosswalk)")
        print(f"  Candidate ESCO skills: {stats['n_candidate_skills']}")

        if not candidates:
            print("  WARNING: No candidate skills found")
            continue

        # Step 3: LLM selection
        if args.dry_run:
            print(f"\n[DRY RUN] Would select from {len(candidates)} candidates")
            # Still record candidates for the report
            results.append({
                "occupation": occupation,
                "onet_codes": onet_codes,
                "candidates": candidates,
                "selected_indices": [],
                "stats": stats,
            })
            continue

        print(f"\nStep 3: LLM selecting from {len(candidates)} candidates...")
        selected_indices = select_skills_with_llm(occupation, candidates, onet_codes, data)
        selected = [candidates[i] for i in selected_indices]
        print(f"  Selected: {len(selected)} skills")

        results.append({
            "occupation": occupation,
            "onet_codes": onet_codes,
            "candidates": candidates,
            "selected_indices": selected_indices,
            "stats": stats,
        })

    # Generate comparison report and export CSVs
    if results:
        generate_excel_report(results, existing_skills, data, args.dry_run)
        if not args.dry_run:
            export_skill_relations(results, data)


def generate_excel_report(
    results: list[dict],
    existing_skills: dict,
    data: dict,
    dry_run: bool,
) -> None:
    """Generate Excel report comparing O*NET-based vs skill-group-based results."""

    output_file = OUTPUT_PATH / "onet_skill_comparison.xlsx"
    label_to_id = data["label_to_id"]

    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:

        # Sheet 1: Summary
        summary_rows = []
        for r in results:
            occ = r["occupation"]
            onet_titles = [
                data["onet_lookup"].get(c, {}).get("title", c) for c in r["onet_codes"]
            ]
            selected_labels = set()
            if r["selected_indices"]:
                selected_labels = {r["candidates"][i]["label"] for i in r["selected_indices"]}
            selected_ids = {label_to_id.get(l, "") for l in selected_labels}

            existing_ids = existing_skills.get(occ["code"], set())
            # Map existing IDs back to labels for comparison
            id_to_label = {v: k for k, v in label_to_id.items()}
            existing_labels = {id_to_label.get(sid, sid) for sid in existing_ids}

            overlap = selected_labels & existing_labels
            only_onet = selected_labels - existing_labels
            only_groups = existing_labels - selected_labels

            summary_rows.append({
                "Occupation Code": occ["code"],
                "Occupation Label": occ["label"],
                "O*NET Matches": " | ".join(onet_titles),
                "O*NET Codes": ", ".join(r["onet_codes"]),
                "Tasks Used": r["stats"]["n_tasks"],
                "Tasks in Crosswalk": r["stats"]["n_tasks_in_crosswalk"],
                "Candidate Skills": r["stats"]["n_candidate_skills"],
                "O*NET Selected": len(selected_labels) if not dry_run else "DRY RUN",
                "Skill-Group Selected": len(existing_ids),
                "Overlap": len(overlap) if not dry_run else "N/A",
                "Only in O*NET": len(only_onet) if not dry_run else "N/A",
                "Only in Skill-Groups": len(only_groups) if not dry_run else "N/A",
            })
        pd.DataFrame(summary_rows).to_excel(writer, sheet_name="Summary", index=False)

        # Sheet per occupation: detailed skill comparison
        for r in results:
            occ = r["occupation"]
            sheet_name = f"{occ['code']}_{occ['label'][:20]}"
            # Sanitize sheet name
            sheet_name = sheet_name.replace("/", "_").replace("\\", "_")[:31]

            existing_ids = existing_skills.get(occ["code"], set())
            id_to_label = {v: k for k, v in label_to_id.items()}
            existing_labels = {id_to_label.get(sid, sid) for sid in existing_ids}

            selected_labels = set()
            if r["selected_indices"]:
                selected_labels = {r["candidates"][i]["label"] for i in r["selected_indices"]}

            # All candidate skills with their status
            rows = []
            for i, c in enumerate(r["candidates"]):
                in_onet = i in r["selected_indices"] if r["selected_indices"] else None
                in_groups = c["label"] in existing_labels

                if in_onet and in_groups:
                    status = "BOTH"
                elif in_onet:
                    status = "ONET_ONLY"
                elif in_groups:
                    status = "GROUPS_ONLY"
                else:
                    status = "candidate (not selected)"

                rows.append({
                    "Selected": "YES" if in_onet else "",
                    "Skill Label": c["label"],
                    "Status": status if not dry_run else ("IN_GROUPS" if in_groups else "candidate"),
                    "O*NET Evidence (Tasks)": c["n_tasks"],
                    "O*NET Sources": c["n_onet_sources"],
                    "Max Cosine Sim": round(c["max_cosine_sim"], 3),
                    "Skill Type": c["skill_type"],
                    "Source O*NET Occs": ", ".join(c["onet_sources"]),
                })

            # Add skills that are in groups pipeline but NOT in candidates
            candidate_labels = {c["label"] for c in r["candidates"]}
            for label in sorted(existing_labels - candidate_labels):
                rows.append({
                    "Selected": "",
                    "Skill Label": label,
                    "Status": "GROUPS_ONLY (not in O*NET candidates)",
                    "O*NET Evidence (Tasks)": 0,
                    "O*NET Sources": 0,
                    "Max Cosine Sim": "",
                    "Skill Type": "",
                    "Source O*NET Occs": "",
                })

            # Sort: BOTH first, then ONET_ONLY, then GROUPS_ONLY, then candidates
            status_order = {"BOTH": 0, "ONET_ONLY": 1, "GROUPS_ONLY": 2, "IN_GROUPS": 1}
            rows.sort(key=lambda x: (
                status_order.get(x["Status"], 9),
                -x["O*NET Evidence (Tasks)"] if isinstance(x["O*NET Evidence (Tasks)"], int) else 0,
            ))

            pd.DataFrame(rows).to_excel(writer, sheet_name=sheet_name, index=False)

    print(f"\nReport saved: {output_file}")


def export_skill_relations(results: list[dict], data: dict) -> None:
    """Export selected skills as CSVs and merge into taxonomy."""

    label_to_id = data["label_to_id"]
    taxonomy_path = OUTPUT_PATH / "taxonomy"

    # Build occupation code -> ID mapping from occupations.csv
    occ_df = pd.read_csv(taxonomy_path / "occupations.csv")
    code_to_occ_id = dict(zip(occ_df["CODE"].astype(str), occ_df["ID"]))

    # Build rows for new local skill relations
    rows = []
    for r in results:
        occ = r["occupation"]
        occ_id = code_to_occ_id.get(occ["code"])
        if not occ_id:
            print(f"  WARNING: No ID found for {occ['code']} - skipping")
            continue
        if not r["selected_indices"]:
            continue
        for idx in r["selected_indices"]:
            skill_label = r["candidates"][idx]["label"]
            skill_id = label_to_id.get(skill_label)
            if not skill_id:
                print(f"  WARNING: No skill ID for '{skill_label}' - skipping")
                continue
            rows.append({
                "OCCUPATIONTYPE": "localoccupation",
                "OCCUPATIONID": occ_id,
                "RELATIONTYPE": "essential",
                "SKILLID": skill_id,
                "SIGNALLINGVALUELABEL": "",
                "SIGNALLINGVALUE": "",
            })

    new_rels_df = pd.DataFrame(rows)

    # 1. Write new_local_skill_relations.csv
    new_rels_file = OUTPUT_PATH / "new_local_skill_relations.csv"
    new_rels_df.to_csv(new_rels_file, index=False)
    print(f"\nExported {len(new_rels_df)} skill relations for {new_rels_df['OCCUPATIONID'].nunique()} occupations")
    print(f"  -> {new_rels_file}")

    # 2. Merge into taxonomy/occupation_to_skill_relations.csv
    tax_rels_file = taxonomy_path / "occupation_to_skill_relations.csv"
    tax_rels_df = pd.read_csv(tax_rels_file)

    # Remove any existing relations for these occupation IDs (in case of re-runs)
    new_occ_ids = set(new_rels_df["OCCUPATIONID"])
    before_count = len(tax_rels_df)
    tax_rels_df = tax_rels_df[~tax_rels_df["OCCUPATIONID"].isin(new_occ_ids)]
    removed = before_count - len(tax_rels_df)
    if removed:
        print(f"  Removed {removed} existing relations for these occupations (re-run)")

    # Append new relations
    merged_df = pd.concat([tax_rels_df, new_rels_df], ignore_index=True)
    merged_df.to_csv(tax_rels_file, index=False)
    print(f"  Merged into taxonomy: {len(tax_rels_df)} existing + {len(new_rels_df)} new = {len(merged_df)} total")
    print(f"  -> {tax_rels_file}")


if __name__ == "__main__":
    main()
