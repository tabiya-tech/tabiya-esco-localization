"""
Generate Tabiya 9-file taxonomy output for Zambia localization.

Takes the base ESCO taxonomy and applies all Zambia localization changes:
  - Adds 16 new local occupations (with descriptions, alt labels)
  - Adds 683 new skills (with descriptions, hierarchy placement)
  - Adds alt labels to 1,456 existing ESCO skills
  - Adds occupation-to-skill mappings (new attachments)
  - Marks modified ESCO items as ISLOCALIZED=True

Import rules (from Kenya findings):
  - New occupations: OCCUPATIONTYPE=localoccupation, ISLOCALIZED=False
  - Modified ESCO occupations: ISLOCALIZED=True
  - PREFERREDLABEL must be in ALTLABELS
  - No duplicate ALTLABELS
  - SIGNALLINGVALUE only on localoccupation->skill relations
  - SIGNALLINGVALUE and RELATIONTYPE are mutually exclusive

Prerequisites:
  - All outputs from steps 01-08
  - shared_data/esco_taxonomy/ (base taxonomy)

Output:
  - outputs/taxonomy/ (9 CSV files + model_info.csv)
"""

import json
import sys
import io
import csv
import uuid
import re
from datetime import datetime
from pathlib import Path
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

BASE_PATH = Path(__file__).parent.parent.parent.parent
ESCO_DIR = BASE_PATH / "shared_data" / "esco_taxonomy"
OUTPUT_DIR = Path(__file__).parent.parent / "outputs"
TAX_DIR = OUTPUT_DIR / "taxonomy"

# Input files
OCC_MATCHES = OUTPUT_DIR / "occupation_matches_validated.json"
NEW_OCCS = OUTPUT_DIR / "new_occupations_finalized.json"
NEW_SKILLS_FINAL = OUTPUT_DIR / "zambia_new_skills_final.xlsx"
SKILL_MAP = OUTPUT_DIR / "zambia_skill_occupation_map.xlsx"
T1_VALIDATED = OUTPUT_DIR / "skill_matches_tier1_validated.json"
T2_VALIDATED = OUTPUT_DIR / "skill_matches_tier2_validated.json"
HIERARCHY_PLACEMENT = OUTPUT_DIR / "skill_hierarchy_placement.json"


def generate_id() -> str:
    """Generate a unique ID in the same hex format as ESCO."""
    return uuid.uuid4().hex[:24]


def ensure_preferred_in_alt(preferred: str, alt_labels: list[str]) -> list[str]:
    """Ensure preferred label is in the alt labels list (convention)."""
    alt_lower = [a.lower().strip() for a in alt_labels]
    if preferred.lower().strip() not in alt_lower:
        alt_labels = [preferred] + alt_labels
    return alt_labels


def dedupe_alt_labels(alt_labels: list[str]) -> list[str]:
    """Remove duplicate alt labels, preserving order."""
    seen = set()
    result = []
    for label in alt_labels:
        key = label.lower().strip()
        if key not in seen and key:
            seen.add(key)
            result.append(label)
    return result


def format_alt_labels(labels: list[str]) -> str:
    """Format alt labels as newline-separated string for CSV."""
    return "\n".join(labels)


def main() -> None:
    TAX_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading base ESCO taxonomy...")
    esco_occs = pd.read_csv(ESCO_DIR / "occupations.csv", encoding="utf-8")
    esco_skills = pd.read_csv(ESCO_DIR / "skills.csv", encoding="utf-8")
    esco_occ_groups = pd.read_csv(ESCO_DIR / "occupation_groups.csv", encoding="utf-8")
    esco_occ_hier = pd.read_csv(ESCO_DIR / "occupation_hierarchy.csv", encoding="utf-8")
    esco_skill_groups = pd.read_csv(ESCO_DIR / "skill_groups.csv", encoding="utf-8")
    esco_skill_hier = pd.read_csv(ESCO_DIR / "skill_hierarchy.csv", encoding="utf-8")
    esco_occ_skills = pd.read_csv(ESCO_DIR / "occupation_to_skill_relations.csv", encoding="utf-8")
    esco_skill_rels = pd.read_csv(ESCO_DIR / "skill_to_skill_relations.csv", encoding="utf-8")

    print(f"  Occupations: {len(esco_occs)}")
    print(f"  Skills: {len(esco_skills)}")
    print(f"  Occupation-skill relations: {len(esco_occ_skills)}")

    # Load Zambia localization data
    print("\nLoading Zambia localization data...")
    with open(OCC_MATCHES, "r", encoding="utf-8") as f:
        occ_matches = json.load(f)
    with open(NEW_OCCS, "r", encoding="utf-8") as f:
        new_occs = json.load(f)
    with open(T1_VALIDATED, "r", encoding="utf-8") as f:
        t1_data = json.load(f)
    with open(T2_VALIDATED, "r", encoding="utf-8") as f:
        t2_data = json.load(f)

    df_new_skills = pd.read_excel(NEW_SKILLS_FINAL, sheet_name="All New Skills")
    df_alt_labels = pd.read_excel(NEW_SKILLS_FINAL, sheet_name="Alt Labels")
    df_skill_map = pd.read_excel(SKILL_MAP, sheet_name="Full Map")

    # Load hierarchy placement
    hier_placement = {}
    if HIERARCHY_PLACEMENT.exists():
        with open(HIERARCHY_PLACEMENT, "r", encoding="utf-8") as f:
            for item in json.load(f):
                hier_placement[item["label"]] = item.get("parent_skill_group", "")

    # Build lookups
    esco_occ_id_by_code = dict(zip(esco_occs["CODE"].astype(str), esco_occs["ID"]))
    esco_skill_id_by_label = dict(zip(
        esco_skills["PREFERREDLABEL"].str.lower().str.strip(),
        esco_skills["ID"]
    ))
    skill_group_id_by_label = dict(zip(
        esco_skill_groups["PREFERREDLABEL"].str.lower().str.strip(),
        esco_skill_groups["ID"]
    ))

    # Track which ESCO items get modified
    modified_occ_ids = set()
    modified_skill_ids = set()

    # ==================================================================
    # 1. OCCUPATIONS
    # ==================================================================
    print("\n--- OCCUPATIONS ---")

    # Build new occupation lookup
    new_occ_lookup = {o["nos_title"]: o for o in new_occs}
    nos_to_esco = {o["nos_title"]: o for o in occ_matches}

    # Add new local occupations
    new_occ_rows = []
    new_occ_ids = {}  # nos_title -> generated ID

    for occ in occ_matches:
        if occ["decision"] != "NEW_LOCAL":
            continue

        title = occ["nos_title"]
        finalized = new_occ_lookup.get(title, {})

        preferred = finalized.get("preferred_label", title.lower())
        description = finalized.get("description", occ.get("nos_description", ""))
        alt_labels = finalized.get("alt_labels", [])

        # Ensure preferred is in alt labels
        alt_labels = ensure_preferred_in_alt(preferred, alt_labels)
        alt_labels = dedupe_alt_labels(alt_labels)

        occ_id = generate_id()
        new_occ_ids[title] = occ_id

        # ISCO group code from human-assigned codes
        isco_code = str(finalized.get("isco_unit_group_code", "")).strip()
        if isco_code == "nan":
            isco_code = ""
        code = f"{isco_code}.ZM.{occ_id[:4]}" if isco_code else f"ZM_{occ_id[:8]}"

        new_occ_rows.append({
            "ID": occ_id,
            "ORIGINURI": "",
            "UUIDHISTORY": str(uuid.uuid4()),
            "OCCUPATIONGROUPCODE": isco_code,
            "CODE": code,
            "DEFINITION": "",
            "SCOPENOTE": "",
            "REGULATEDPROFESSIONNOTE": "",
            "OCCUPATIONTYPE": "localoccupation",
            "ISLOCALIZED": False,
            "PREFERREDLABEL": preferred,
            "ALTLABELS": format_alt_labels(alt_labels),
            "DESCRIPTION": description,
        })

    print(f"  New local occupations: {len(new_occ_rows)}")

    # Mark matched ESCO occupations that have been localized
    # (occupations that got new skills attached or alt labels)
    matched_occs_with_changes = set()
    for _, row in df_skill_map.iterrows():
        if row.get("occ_decision") == "MATCH" and row.get("zambia_localized") == True:
            matched_occs_with_changes.add(row["nos_occupation"])

    for title in matched_occs_with_changes:
        occ_info = nos_to_esco.get(title, {})
        esco_code = occ_info.get("esco_code", "")
        occ_id = esco_occ_id_by_code.get(esco_code, "")
        if occ_id:
            modified_occ_ids.add(occ_id)

    # Apply ISLOCALIZED to modified ESCO occupations
    esco_occs["ISLOCALIZED"] = esco_occs["ID"].apply(
        lambda x: True if x in modified_occ_ids else esco_occs.loc[esco_occs["ID"] == x, "ISLOCALIZED"].iloc[0]
        if not esco_occs.loc[esco_occs["ID"] == x].empty else False
    )

    # Add ESCO alt labels for matched occupations (NOS title as alt label)
    for occ in occ_matches:
        if occ["decision"] != "MATCH":
            continue
        esco_code = occ.get("esco_code", "")
        nos_title = occ["nos_title"].lower()
        mask = esco_occs["CODE"].astype(str) == esco_code
        if mask.any():
            idx = mask.idxmax()
            current_alt = str(esco_occs.at[idx, "ALTLABELS"]) if pd.notna(esco_occs.at[idx, "ALTLABELS"]) else ""
            current_list = [a.strip() for a in current_alt.split("\n") if a.strip()]
            if nos_title not in [a.lower() for a in current_list]:
                current_list.append(nos_title)
                esco_occs.at[idx, "ALTLABELS"] = "\n".join(current_list)

    # Combine ESCO + new occupations
    df_new_occs = pd.DataFrame(new_occ_rows)
    all_occs = pd.concat([esco_occs, df_new_occs], ignore_index=True)
    print(f"  Total occupations: {len(all_occs)} ({len(esco_occs)} ESCO + {len(new_occ_rows)} new)")
    print(f"  ESCO occupations marked ISLOCALIZED: {len(modified_occ_ids)}")

    # ==================================================================
    # 2. SKILLS
    # ==================================================================
    print("\n--- SKILLS ---")

    # Add alt labels to existing ESCO skills
    alt_label_count = 0
    for _, row in df_alt_labels.iterrows():
        esco_label = str(row.get("esco_skill", "")).lower().strip()
        new_alt = str(row.get("new_alt_label", "")).strip()
        if not esco_label or not new_alt:
            continue

        mask = esco_skills["PREFERREDLABEL"].str.lower().str.strip() == esco_label
        if mask.any():
            idx = mask.idxmax()
            skill_id = esco_skills.at[idx, "ID"]
            modified_skill_ids.add(skill_id)

            current_alt = str(esco_skills.at[idx, "ALTLABELS"]) if pd.notna(esco_skills.at[idx, "ALTLABELS"]) else ""
            current_list = [a.strip() for a in current_alt.split("\n") if a.strip()]
            if new_alt.lower() not in [a.lower() for a in current_list]:
                current_list.append(new_alt)
                esco_skills.at[idx, "ALTLABELS"] = "\n".join(current_list)
                alt_label_count += 1

    print(f"  Alt labels added to ESCO skills: {alt_label_count}")

    # Mark modified skills as localized
    esco_skills["ISLOCALIZED"] = esco_skills["ID"].apply(
        lambda x: True if x in modified_skill_ids else (
            esco_skills.loc[esco_skills["ID"] == x, "ISLOCALIZED"].iloc[0]
            if not esco_skills.loc[esco_skills["ID"] == x].empty else False
        )
    )

    # Ensure preferred label is in alt labels for all skills
    for idx, row in esco_skills.iterrows():
        preferred = str(row.get("PREFERREDLABEL", ""))
        alt = str(row.get("ALTLABELS", "")) if pd.notna(row.get("ALTLABELS")) else ""
        alt_list = [a.strip() for a in alt.split("\n") if a.strip()]
        alt_list = ensure_preferred_in_alt(preferred, alt_list)
        alt_list = dedupe_alt_labels(alt_list)
        esco_skills.at[idx, "ALTLABELS"] = "\n".join(alt_list)

    # Add new skills
    new_skill_rows = []
    new_skill_ids = {}  # label -> generated ID

    for _, row in df_new_skills.iterrows():
        label = str(row["label"])
        skill_type = str(row["type"])
        description = str(row.get("description", "")) if pd.notna(row.get("description")) else ""
        parent_group = str(row.get("parent_skill_group", "")) if pd.notna(row.get("parent_skill_group")) else ""

        skill_id = generate_id()
        new_skill_ids[label.lower().strip()] = skill_id

        alt_labels = ensure_preferred_in_alt(label, [])
        alt_labels = dedupe_alt_labels(alt_labels)

        # Determine reuse level
        num_occs = int(row.get("num_occupations", 1)) if pd.notna(row.get("num_occupations")) else 1
        if num_occs > 10:
            reuse_level = "cross-sector"
        elif num_occs > 1:
            reuse_level = "sector-specific"
        else:
            reuse_level = "occupation-specific"

        new_skill_rows.append({
            "ID": skill_id,
            "ORIGINURI": "",
            "UUIDHISTORY": str(uuid.uuid4()),
            "DEFINITION": "",
            "SCOPENOTE": "",
            "REUSELEVEL": reuse_level,
            "SKILLTYPE": skill_type,
            "PREFERREDLABEL": label,
            "ALTLABELS": format_alt_labels(alt_labels),
            "DESCRIPTION": description,
            "ISLOCALIZED": False,
        })

    df_new_skills_csv = pd.DataFrame(new_skill_rows)
    all_skills = pd.concat([esco_skills, df_new_skills_csv], ignore_index=True)
    print(f"  New skills added: {len(new_skill_rows)}")
    print(f"  ESCO skills marked ISLOCALIZED: {len(modified_skill_ids)}")
    print(f"  Total skills: {len(all_skills)}")

    # ==================================================================
    # 3. SKILL HIERARCHY
    # ==================================================================
    print("\n--- SKILL HIERARCHY ---")

    # Add new skills to hierarchy
    new_hier_rows = []
    placed = 0
    for _, row in df_new_skills.iterrows():
        label = str(row["label"]).lower().strip()
        skill_id = new_skill_ids.get(label, "")
        if not skill_id:
            continue

        # Get parent group from hierarchy placement
        parent_label = str(row.get("parent_skill_group", "")).lower().strip()
        if not parent_label or parent_label == "nan":
            parent_label = hier_placement.get(label, "").lower().strip()

        parent_id = skill_group_id_by_label.get(parent_label, "")
        if parent_id:
            new_hier_rows.append({
                "PARENTOBJECTTYPE": "skillgroup",
                "PARENTID": parent_id,
                "CHILDID": skill_id,
                "CHILDOBJECTTYPE": "skill",
            })
            placed += 1

    df_new_hier = pd.DataFrame(new_hier_rows)
    all_skill_hier = pd.concat([esco_skill_hier, df_new_hier], ignore_index=True)
    print(f"  New skills placed in hierarchy: {placed}/{len(new_skill_rows)}")

    # ==================================================================
    # 4. OCCUPATION-TO-SKILL RELATIONS
    # ==================================================================
    print("\n--- OCCUPATION-TO-SKILL RELATIONS ---")

    # Build full skill ID lookup (ESCO + new)
    all_skill_id_by_label = dict(esco_skill_id_by_label)
    all_skill_id_by_label.update(new_skill_ids)

    new_rel_rows = []
    for _, row in df_skill_map.iterrows():
        source = str(row.get("skill_source", ""))
        if source == "esco_existing":
            continue  # Already in base taxonomy

        nos_occ = str(row["nos_occupation"])
        skill_label = str(row["skill_label"]).lower().strip()
        occ_decision = str(row.get("occ_decision", ""))

        # Get occupation ID
        if occ_decision == "MATCH":
            occ_info = nos_to_esco.get(nos_occ, {})
            occ_id = esco_occ_id_by_code.get(occ_info.get("esco_code", ""), "")
            occ_type = "escooccupation"
        elif occ_decision == "NEW_LOCAL":
            occ_id = new_occ_ids.get(nos_occ, "")
            occ_type = "localoccupation"
        else:
            continue

        # Get skill ID
        skill_id = all_skill_id_by_label.get(skill_label, "")
        if not occ_id or not skill_id:
            continue

        # New relations: leave RELATIONTYPE and SIGNALLINGVALUE empty
        # These can be assigned later through review
        new_rel_rows.append({
            "OCCUPATIONTYPE": occ_type,
            "OCCUPATIONID": occ_id,
            "RELATIONTYPE": "",
            "SKILLID": skill_id,
            "SIGNALLINGVALUELABEL": "",
            "SIGNALLINGVALUE": "",
        })

    # Deduplicate relations
    df_new_rels = pd.DataFrame(new_rel_rows)
    before = len(df_new_rels)
    df_new_rels = df_new_rels.drop_duplicates(subset=["OCCUPATIONID", "SKILLID"], keep="first")
    print(f"  New relations: {len(df_new_rels)} (deduped from {before})")

    all_occ_skills = pd.concat([esco_occ_skills, df_new_rels], ignore_index=True)
    # Deduplicate globally
    before_global = len(all_occ_skills)
    all_occ_skills = all_occ_skills.drop_duplicates(subset=["OCCUPATIONID", "SKILLID"], keep="first")
    print(f"  Total relations: {len(all_occ_skills)} (deduped {before_global - len(all_occ_skills)} global dupes)")

    # ==================================================================
    # 5. OCCUPATION HIERARCHY
    # ==================================================================
    print("\n--- OCCUPATION HIERARCHY ---")
    # New local occupations need to be placed in the occupation hierarchy
    # For now, they don't have ISCO group codes, so we skip hierarchy placement
    # They'll appear as top-level occupations
    all_occ_hier = esco_occ_hier.copy()
    print(f"  Occupation hierarchy: {len(all_occ_hier)} (no new entries for local occupations)")

    # ==================================================================
    # 6. WRITE OUTPUT FILES
    # ==================================================================
    print(f"\n--- WRITING OUTPUT ({TAX_DIR}) ---")

    all_occs.to_csv(TAX_DIR / "occupations.csv", index=False, encoding="utf-8", quoting=csv.QUOTE_ALL)
    print(f"  occupations.csv: {len(all_occs)} rows")

    esco_occ_groups.to_csv(TAX_DIR / "occupation_groups.csv", index=False, encoding="utf-8", quoting=csv.QUOTE_ALL)
    print(f"  occupation_groups.csv: {len(esco_occ_groups)} rows")

    all_occ_hier.to_csv(TAX_DIR / "occupation_hierarchy.csv", index=False, encoding="utf-8", quoting=csv.QUOTE_ALL)
    print(f"  occupation_hierarchy.csv: {len(all_occ_hier)} rows")

    all_skills.to_csv(TAX_DIR / "skills.csv", index=False, encoding="utf-8", quoting=csv.QUOTE_ALL)
    print(f"  skills.csv: {len(all_skills)} rows")

    esco_skill_groups.to_csv(TAX_DIR / "skill_groups.csv", index=False, encoding="utf-8", quoting=csv.QUOTE_ALL)
    print(f"  skill_groups.csv: {len(esco_skill_groups)} rows")

    all_skill_hier.to_csv(TAX_DIR / "skill_hierarchy.csv", index=False, encoding="utf-8", quoting=csv.QUOTE_ALL)
    print(f"  skill_hierarchy.csv: {len(all_skill_hier)} rows")

    all_occ_skills.to_csv(TAX_DIR / "occupation_to_skill_relations.csv", index=False, encoding="utf-8", quoting=csv.QUOTE_ALL)
    print(f"  occupation_to_skill_relations.csv: {len(all_occ_skills)} rows")

    esco_skill_rels.to_csv(TAX_DIR / "skill_to_skill_relations.csv", index=False, encoding="utf-8", quoting=csv.QUOTE_ALL)
    print(f"  skill_to_skill_relations.csv: {len(esco_skill_rels)} rows")

    # Model info
    model_info = pd.DataFrame([{
        "UUIDHISTORY": str(uuid.uuid4()),
        "NAME": "Tabiya ESCO Zambia",
        "LOCALE": "en",
        "DESCRIPTION": "Tabiya ESCO v2.0.1 localized for Zambia using NOS (National Occupational Standards) from the Zambia Qualifications Authority",
        "VERSION": "1.0.0",
        "RELEASED": datetime.now().strftime("%Y-%m-%d"),
        "RELEASENOTES": f"Initial Zambia localization: {len(new_occ_rows)} new occupations, {len(new_skill_rows)} new skills, {alt_label_count} alt labels added",
    }])
    model_info.to_csv(TAX_DIR / "model_info.csv", index=False, encoding="utf-8", quoting=csv.QUOTE_ALL)
    print(f"  model_info.csv: 1 row")

    # ==================================================================
    # SUMMARY
    # ==================================================================
    print(f"\n{'='*70}")
    print("TAXONOMY GENERATION COMPLETE")
    print(f"{'='*70}")
    print(f"Output directory: {TAX_DIR}")
    print(f"Files generated: 9 + model_info.csv")
    print(f"\nChanges from base ESCO:")
    print(f"  New local occupations: {len(new_occ_rows)}")
    print(f"  ESCO occupations localized: {len(modified_occ_ids)}")
    print(f"  New skills: {len(new_skill_rows)}")
    print(f"  ESCO skills with new alt labels: {len(modified_skill_ids)}")
    print(f"  New occupation-skill relations: {len(df_new_rels)}")
    print(f"  New skill hierarchy entries: {len(df_new_hier)}")


if __name__ == "__main__":
    main()
