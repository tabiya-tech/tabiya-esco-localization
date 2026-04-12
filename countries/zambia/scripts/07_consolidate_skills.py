"""
Consolidate all skill matching results into a single taxonomy output.

Combines:
- Tier 1 (TK+RK) validated matches
- Tier 2 (CS+PS) validated matches
- PC gap analysis results
- Occupation matching results

Deduplicates new labels, removes false negatives (labels already in ESCO),
and builds the occupation-to-skill mapping.

Output:
  - outputs/zambia_new_skills.xlsx - All new/contextualised skills for review
  - outputs/zambia_occupation_skill_map.xlsx - Full occupation-to-skill mapping
  - outputs/zambia_consolidation_summary.json - Stats
"""

import json
import sys
import io
import re
import pandas as pd
from pathlib import Path
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

BASE_PATH = Path(__file__).parent.parent.parent.parent
OUTPUT_DIR = Path(__file__).parent.parent / "outputs"

ESCO_SKILLS = BASE_PATH / "shared_data" / "esco_taxonomy" / "skills.csv"
ESCO_OCCS = BASE_PATH / "shared_data" / "esco_taxonomy" / "occupations.csv"
ESCO_OCC_SKILLS = BASE_PATH / "shared_data" / "esco_taxonomy" / "occupation_to_skill_relations.csv"
ESCO_HIERARCHY = BASE_PATH / "shared_data" / "esco_taxonomy" / "skill_hierarchy.csv"
ESCO_GROUPS = BASE_PATH / "shared_data" / "esco_taxonomy" / "skill_groups.csv"


def load_esco_label_set() -> set[str]:
    """Load all ESCO skill labels (preferred + alt) for false negative check."""
    df = pd.read_csv(ESCO_SKILLS, encoding="utf-8")
    labels = set(df["PREFERREDLABEL"].str.lower().str.strip().dropna())
    for alt in df["ALTLABELS"].dropna():
        for label in str(alt).split("\n"):
            labels.add(label.lower().strip())
    return labels


def load_esco_skill_lookup() -> dict:
    """Build label -> skill info lookup."""
    df = pd.read_csv(ESCO_SKILLS, encoding="utf-8")
    lookup = {}
    for _, row in df.iterrows():
        label = str(row.get("PREFERREDLABEL", "")).lower().strip()
        if label and label != "nan":
            lookup[label] = {
                "id": str(row.get("ID", "")),
                "label": str(row.get("PREFERREDLABEL", "")),
                "type": str(row.get("SKILLTYPE", "")),
                "reuse_level": str(row.get("REUSELEVEL", "")),
            }
    return lookup


def load_hierarchy_lookup() -> tuple[dict, dict]:
    """Build child->parent and id->group_label lookups."""
    hier = pd.read_csv(ESCO_HIERARCHY, encoding="utf-8")
    groups = pd.read_csv(ESCO_GROUPS, encoding="utf-8")
    child_to_parent = dict(zip(hier["CHILDID"], hier["PARENTID"]))
    group_labels = dict(zip(groups["ID"], groups["PREFERREDLABEL"]))
    return child_to_parent, group_labels


def main() -> None:
    print("Loading ESCO data...")
    esco_labels = load_esco_label_set()
    esco_lookup = load_esco_skill_lookup()
    child_to_parent, group_labels = load_hierarchy_lookup()

    # Load all validated results
    with open(OUTPUT_DIR / "skill_matches_tier1_validated.json", "r", encoding="utf-8") as f:
        t1_data = json.load(f)
    with open(OUTPUT_DIR / "skill_matches_tier2_validated.json", "r", encoding="utf-8") as f:
        t2_data = json.load(f)
    with open(OUTPUT_DIR / "pc_gap_analysis.json", "r", encoding="utf-8") as f:
        pc_data = json.load(f)
    with open(OUTPUT_DIR / "occupation_matches_validated.json", "r", encoding="utf-8") as f:
        occ_data = json.load(f)

    # Build NOS title -> ESCO occupation mapping
    nos_to_esco = {}
    for o in occ_data:
        nos_to_esco[o["nos_title"]] = {
            "decision": o["decision"],
            "esco_label": o.get("esco_label", ""),
            "esco_code": o.get("esco_code", ""),
        }

    # =========================================================
    # 1. COLLECT ALL NEW SKILLS
    # =========================================================
    print("\nCollecting new skills...")
    new_skills = {}  # label -> info

    def add_new_skill(label: str, skill_type: str, source: str,
                       nos_occupation: str, esco_match: str = "", esco_match_id: str = ""):
        label = label.lower().strip()
        if not label or len(label) < 3:
            return
        # Skip if already in ESCO
        if label in esco_labels:
            return
        if label not in new_skills:
            # Find parent group from closest ESCO match
            parent_group = ""
            if esco_match:
                match_info = esco_lookup.get(esco_match.lower().strip(), {})
                if match_info:
                    parent_id = child_to_parent.get(match_info["id"], "")
                    parent_group = group_labels.get(parent_id, "")

            new_skills[label] = {
                "label": label,
                "type": skill_type,
                "sources": [],
                "nos_occupations": set(),
                "esco_match": esco_match,
                "parent_group": parent_group,
            }
        new_skills[label]["sources"].append(source)
        new_skills[label]["nos_occupations"].add(nos_occupation)

    # From Tier 1
    for v in t1_data:
        if v["decision"] == "NEW":
            occs = v.get("occupations", "").split(", ")
            for label in v.get("esco_labels", []):
                for occ in occs:
                    occ = occ.strip().rstrip(".")
                    if occ:
                        add_new_skill(label, "knowledge", "tier1", occ,
                                       v.get("top_match_label", ""))

    # From Tier 2
    for v in t2_data:
        if v["decision"] == "NEW":
            occs = v.get("occupations", "").split(", ")
            for label in v.get("esco_labels", []):
                for occ in occs:
                    occ = occ.strip().rstrip(".")
                    if occ:
                        add_new_skill(label, "skill/competence", "tier2", occ,
                                       v.get("top_match_label", ""))

    # From PC gaps
    for r in pc_data:
        nos_title = r.get("nos_title", "")
        for gap in r.get("gaps", []):
            label = gap.get("label", "")
            gap_type = gap.get("type", "skill/competence")
            add_new_skill(label, gap_type, "pc_gap", nos_title)

    # Convert sets to lists for JSON
    for v in new_skills.values():
        v["nos_occupations"] = sorted(v["nos_occupations"])
        v["source_count"] = len(set(v["sources"]))

    print(f"  New skills (after removing ESCO false negatives): {len(new_skills)}")

    # =========================================================
    # 2. COLLECT ALL CONTEXTUALIZED LABELS
    # =========================================================
    print("Collecting contextualised alt labels...")
    ctx_labels = {}  # esco_label -> list of alt labels

    for v in t1_data:
        if v["decision"] == "CONTEXTUALIZE":
            esco = v.get("top_match_label", "").lower().strip()
            for label in v.get("esco_labels", []):
                label = label.lower().strip()
                if label and label != esco and label not in esco_labels:
                    if esco not in ctx_labels:
                        ctx_labels[esco] = set()
                    ctx_labels[esco].add(label)

    for v in t2_data:
        if v["decision"] == "CONTEXTUALIZE":
            esco = v.get("top_match_label", "").lower().strip()
            for label in v.get("esco_labels", []):
                label = label.lower().strip()
                if label and label != esco and label not in esco_labels:
                    if esco not in ctx_labels:
                        ctx_labels[esco] = set()
                    ctx_labels[esco].add(label)

    total_alt = sum(len(v) for v in ctx_labels.values())
    print(f"  ESCO skills with new alt labels: {len(ctx_labels)}")
    print(f"  Total new alt labels: {total_alt}")

    # =========================================================
    # 3. BUILD OCCUPATION-TO-SKILL MAP
    # =========================================================
    print("\nBuilding occupation-to-skill mapping...")

    # Load existing ESCO occupation-skill relations
    occs_df = pd.read_csv(ESCO_OCCS, encoding="utf-8")
    skills_df = pd.read_csv(ESCO_SKILLS, encoding="utf-8")
    rel_df = pd.read_csv(ESCO_OCC_SKILLS, encoding="utf-8")

    code_to_id = dict(zip(occs_df["CODE"].astype(str), occs_df["ID"]))
    skill_id_to_label = dict(zip(skills_df["ID"], skills_df["PREFERREDLABEL"]))
    skill_id_to_type = dict(zip(skills_df["ID"], skills_df["SKILLTYPE"]))

    occ_skill_map = []  # rows for Excel

    for o in occ_data:
        nos_title = o["nos_title"]
        nos_sector = o.get("nos_sector", "")
        decision = o["decision"]
        esco_label = o.get("esco_label", "")
        esco_code = o.get("esco_code", "")

        if decision == "MATCH" and esco_code:
            # Get existing ESCO skills
            occ_id = code_to_id.get(esco_code, "")
            if occ_id:
                rels = rel_df[rel_df["OCCUPATIONID"] == occ_id]
                for _, rel in rels.iterrows():
                    skill_label = skill_id_to_label.get(rel["SKILLID"], "")
                    skill_type = skill_id_to_type.get(rel["SKILLID"], "")
                    occ_skill_map.append({
                        "nos_occupation": nos_title,
                        "nos_sector": nos_sector,
                        "occ_decision": "MATCH",
                        "esco_occupation": esco_label,
                        "skill_label": skill_label,
                        "skill_type": skill_type,
                        "relation_type": rel["RELATIONTYPE"],
                        "skill_source": "esco_existing",
                        "zambia_localized": False,
                    })

        # Add new skills from all tiers for this occupation
        for label, info in new_skills.items():
            if nos_title in info["nos_occupations"]:
                occ_skill_map.append({
                    "nos_occupation": nos_title,
                    "nos_sector": nos_sector,
                    "occ_decision": decision,
                    "esco_occupation": esco_label if decision == "MATCH" else f"NEW: {nos_title}",
                    "skill_label": info["label"],
                    "skill_type": info["type"],
                    "relation_type": "essential",
                    "skill_source": ", ".join(set(info["sources"])),
                    "zambia_localized": True,
                })

    print(f"  Total occupation-skill mappings: {len(occ_skill_map)}")

    # =========================================================
    # 4. SAVE OUTPUTS
    # =========================================================
    print("\nSaving outputs...")

    # New skills Excel
    new_skills_rows = sorted(new_skills.values(), key=lambda x: (x["type"], x["label"]))
    df_new = pd.DataFrame([{
        "label": s["label"],
        "type": s["type"],
        "sources": ", ".join(set(s["sources"])),
        "source_count": s["source_count"],
        "nos_occupations": ", ".join(s["nos_occupations"][:5]),
        "num_occupations": len(s["nos_occupations"]),
        "closest_esco_match": s.get("esco_match", ""),
        "parent_skill_group": s.get("parent_group", ""),
    } for s in new_skills_rows])

    new_skills_path = OUTPUT_DIR / "zambia_new_skills.xlsx"
    with pd.ExcelWriter(new_skills_path, engine="openpyxl") as writer:
        df_new.to_excel(writer, sheet_name="All New Skills", index=False)
        df_new[df_new["type"] == "skill/competence"].to_excel(
            writer, sheet_name="New Skills", index=False)
        df_new[df_new["type"] == "knowledge"].to_excel(
            writer, sheet_name="New Knowledge", index=False)

        # Alt labels sheet
        alt_rows = []
        for esco, alts in sorted(ctx_labels.items()):
            for alt in sorted(alts):
                alt_rows.append({"esco_skill": esco, "new_alt_label": alt})
        pd.DataFrame(alt_rows).to_excel(writer, sheet_name="Alt Labels", index=False)

    print(f"  Wrote {new_skills_path.name}")

    # Occupation-skill map Excel
    df_map = pd.DataFrame(occ_skill_map)
    map_path = OUTPUT_DIR / "zambia_occupation_skill_map.xlsx"
    with pd.ExcelWriter(map_path, engine="openpyxl") as writer:
        df_map.to_excel(writer, sheet_name="Full Map", index=False)
        df_map[df_map["zambia_localized"] == True].to_excel(
            writer, sheet_name="Zambia Localized Only", index=False)
        # Summary per occupation
        summary = df_map.groupby(["nos_occupation", "occ_decision", "esco_occupation"]).agg(
            total_skills=("skill_label", "count"),
            esco_existing=("skill_source", lambda x: sum(1 for v in x if v == "esco_existing")),
            zambia_new=("zambia_localized", "sum"),
        ).reset_index()
        summary.to_excel(writer, sheet_name="Occupation Summary", index=False)

    print(f"  Wrote {map_path.name}")

    # Summary JSON
    summary_data = {
        "occupations": {
            "total_nos": len(occ_data),
            "matched": sum(1 for o in occ_data if o["decision"] == "MATCH"),
            "new_local": sum(1 for o in occ_data if o["decision"] == "NEW_LOCAL"),
        },
        "new_skills": {
            "total": len(new_skills),
            "skill_competence": len([s for s in new_skills.values() if s["type"] == "skill/competence"]),
            "knowledge": len([s for s in new_skills.values() if s["type"] == "knowledge"]),
        },
        "contextualised_labels": {
            "esco_skills_with_alt_labels": len(ctx_labels),
            "total_alt_labels": total_alt,
        },
        "occupation_skill_map": {
            "total_mappings": len(occ_skill_map),
            "esco_existing": sum(1 for m in occ_skill_map if m["skill_source"] == "esco_existing"),
            "zambia_localized": sum(1 for m in occ_skill_map if m["zambia_localized"]),
        },
    }

    with open(OUTPUT_DIR / "zambia_consolidation_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary_data, f, indent=2)

    print(f"\n{'='*70}")
    print("CONSOLIDATION SUMMARY")
    print(f"{'='*70}")
    print(json.dumps(summary_data, indent=2))


if __name__ == "__main__":
    main()
