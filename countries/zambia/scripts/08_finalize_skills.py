"""
Finalize new and contextualised skills for the Zambia localization.

Combined pipeline:
  Step 1: Generate ESCO-style descriptions for new skills (LLM)
  Step 2: Place new skills in ESCO skill group hierarchy (LLM)
  Step 3: Map all skills to occupations (new + contextualised)

Usage:
  python 08_finalize_skills.py                # Run full pipeline
  python 08_finalize_skills.py --describe     # Step 1 only
  python 08_finalize_skills.py --place        # Step 2 only
  python 08_finalize_skills.py --map          # Step 3 only

Prerequisites:
  - outputs/zambia_new_skills.xlsx (from 07_consolidate_skills.py)
  - outputs/skill_matches_tier1_validated.json
  - outputs/skill_matches_tier2_validated.json
  - outputs/occupation_matches_validated.json
  - shared_data/esco_taxonomy/
  - GEMINI_API_KEY in .env

Output:
  - outputs/zambia_new_skills_final.xlsx
  - outputs/zambia_skill_occupation_map.xlsx
  - outputs/zambia_finalize_summary.json
"""

import json
import sys
import io
import os
import time
import re
import argparse
import pandas as pd
from pathlib import Path
import google.generativeai as genai
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

BASE_PATH = Path(__file__).parent.parent.parent.parent
load_dotenv(BASE_PATH / ".env")

OUTPUT_DIR = Path(__file__).parent.parent / "outputs"
ESCO_SKILLS_CSV = BASE_PATH / "shared_data" / "esco_taxonomy" / "skills.csv"
ESCO_OCCS_CSV = BASE_PATH / "shared_data" / "esco_taxonomy" / "occupations.csv"
ESCO_OCC_SKILLS_CSV = BASE_PATH / "shared_data" / "esco_taxonomy" / "occupation_to_skill_relations.csv"
ESCO_HIERARCHY_CSV = BASE_PATH / "shared_data" / "esco_taxonomy" / "skill_hierarchy.csv"
ESCO_GROUPS_CSV = BASE_PATH / "shared_data" / "esco_taxonomy" / "skill_groups.csv"

LLM_MODEL = "models/gemini-2.0-flash"
MAX_RETRIES = 5
BATCH_SIZE = 10

# Checkpoint files
DESC_CHECKPOINT = OUTPUT_DIR / "finalize_desc_checkpoint.json"
HIER_CHECKPOINT = OUTPUT_DIR / "finalize_hier_checkpoint.json"


def call_llm(system_prompt: str, user_prompt: str) -> str:
    model = genai.GenerativeModel(LLM_MODEL, system_instruction=system_prompt)
    for attempt in range(MAX_RETRIES):
        try:
            response = model.generate_content(user_prompt)
            return response.text.strip()
        except Exception as e:
            if "429" in str(e) or "quota" in str(e).lower():
                wait = 45 * (attempt + 1)
                print(f"    Rate limited, waiting {wait}s...")
                time.sleep(wait)
            else:
                print(f"    Error (attempt {attempt + 1}): {e}")
                time.sleep(5)
    return ""


def parse_json_response(text: str) -> list | dict:
    text = text.strip()
    text = re.sub(r"^```json?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return []


def load_checkpoint(path: Path) -> dict:
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_checkpoint(path: Path, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# =========================================================================
# STEP 1: GENERATE DESCRIPTIONS
# =========================================================================

DESC_SYSTEM_PROMPT = """You are an expert at writing ESCO-style skill and knowledge descriptions.

You are given a batch of new skills/knowledge concepts that need descriptions.

ESCO description rules:
- 50-300 characters (aim for 100-200)
- Explain what the skill/knowledge is about
- Do not just reformulate the label
- Be concise and specific
- For skills (verb phrases): describe what the person can do and in what context
- For knowledge (noun phrases): describe the body of knowledge, theories, or practices covered
- Do not use national references
- Use third person ("The ability to..." or "The body of knowledge...")

Reply with ONLY a JSON array:
[
  {"label": "skill label", "description": "Generated description"},
  ...
]"""


def run_descriptions(df: pd.DataFrame) -> pd.DataFrame:
    """Generate ESCO-style descriptions for new skills."""
    print(f"\n{'='*70}")
    print("STEP 1: GENERATE DESCRIPTIONS")
    print(f"{'='*70}")

    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    checkpoint = load_checkpoint(DESC_CHECKPOINT)
    print(f"Skills to describe: {len(df)}")
    print(f"Checkpoint: {len(checkpoint)} already done")

    skills = []
    for _, row in df.iterrows():
        skills.append({"label": str(row["label"]), "type": str(row["type"])})

    remaining = [s for s in skills if s["label"] not in checkpoint]
    print(f"Remaining: {len(remaining)}")

    for i in range(0, len(remaining), BATCH_SIZE):
        batch = remaining[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = (len(remaining) - 1) // BATCH_SIZE + 1

        items_text = ""
        for s in batch:
            items_text += f"- \"{s['label']}\" (type: {s['type']})\n"

        user_prompt = f"Write ESCO-style descriptions for these concepts:\n\n{items_text}"
        raw = call_llm(DESC_SYSTEM_PROMPT, user_prompt)
        parsed = parse_json_response(raw)

        if isinstance(parsed, list) and len(parsed) == len(batch):
            for s, p in zip(batch, parsed):
                checkpoint[s["label"]] = p.get("description", "")
        else:
            for s in batch:
                if s["label"] not in checkpoint:
                    checkpoint[s["label"]] = ""

        if batch_num % 5 == 0 or batch_num == total_batches:
            save_checkpoint(DESC_CHECKPOINT, checkpoint)
            print(f"  Batch {batch_num}/{total_batches} [checkpoint: {len(checkpoint)}]")

        time.sleep(0.5)

    save_checkpoint(DESC_CHECKPOINT, checkpoint)

    # Apply descriptions to dataframe
    df["description"] = df["label"].map(checkpoint).fillna("")
    described = df[df["description"] != ""].shape[0]
    print(f"Descriptions generated: {described}/{len(df)}")

    return df


# =========================================================================
# STEP 2: HIERARCHY PLACEMENT
# =========================================================================

def get_leaf_skill_groups() -> list[str]:
    hier = pd.read_csv(ESCO_HIERARCHY_CSV, encoding="utf-8")
    groups = pd.read_csv(ESCO_GROUPS_CSV, encoding="utf-8")
    skill_parents = hier[hier["CHILDOBJECTTYPE"] == "skill"]["PARENTID"].unique()
    return sorted(groups[groups["ID"].isin(skill_parents)]["PREFERREDLABEL"].dropna().unique())


def build_hier_system_prompt(groups_list: list[str]) -> str:
    groups_text = "\n".join(f"  - {g}" for g in groups_list)
    return f"""You are an expert at organizing skills within the ESCO taxonomy hierarchy.

You are given a batch of new skills. For each one, assign the most appropriate
parent skill group from the list below.

Consider the skill's type (skill/competence vs knowledge) and its domain when
choosing. Select the most specific group that fits.

Available skill groups:
{groups_text}

Reply with ONLY a JSON array, one entry per skill:
[
  {{"label": "skill label", "group": "chosen group name"}},
  ...
]"""


def run_hierarchy_placement(df: pd.DataFrame) -> pd.DataFrame:
    """Place new skills in ESCO skill group hierarchy via LLM."""
    print(f"\n{'='*70}")
    print("STEP 2: HIERARCHY PLACEMENT")
    print(f"{'='*70}")

    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    checkpoint = load_checkpoint(HIER_CHECKPOINT)
    groups_list = get_leaf_skill_groups()
    print(f"Skills to place: {len(df)}")
    print(f"Available groups: {len(groups_list)}")
    print(f"Checkpoint: {len(checkpoint)} already done")

    system_prompt = build_hier_system_prompt(groups_list)

    skills = [{"label": str(row["label"]), "type": str(row["type"])} for _, row in df.iterrows()]
    remaining = [s for s in skills if s["label"] not in checkpoint]
    print(f"Remaining: {len(remaining)}")

    for i in range(0, len(remaining), BATCH_SIZE):
        batch = remaining[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = (len(remaining) - 1) // BATCH_SIZE + 1

        items_text = ""
        for s in batch:
            items_text += f"- Label: \"{s['label']}\" (type: {s['type']})\n"

        user_prompt = f"Assign each skill to the most appropriate skill group:\n\n{items_text}"
        raw = call_llm(system_prompt, user_prompt)
        parsed = parse_json_response(raw)

        if isinstance(parsed, list) and len(parsed) == len(batch):
            for s, p in zip(batch, parsed):
                checkpoint[s["label"]] = p.get("group", "")
        else:
            for s in batch:
                if s["label"] not in checkpoint:
                    checkpoint[s["label"]] = ""

        if batch_num % 5 == 0 or batch_num == total_batches:
            save_checkpoint(HIER_CHECKPOINT, checkpoint)
            print(f"  Batch {batch_num}/{total_batches} [checkpoint: {len(checkpoint)}]")

        time.sleep(0.5)

    save_checkpoint(HIER_CHECKPOINT, checkpoint)

    df["parent_skill_group"] = df["label"].map(checkpoint).fillna("")
    placed = df[df["parent_skill_group"] != ""].shape[0]
    print(f"Placed: {placed}/{len(df)}")

    return df


# =========================================================================
# STEP 3: OCCUPATION-SKILL MAPPING
# =========================================================================

def run_occupation_mapping(df_new_skills: pd.DataFrame) -> pd.DataFrame:
    """Build complete occupation-to-skill mapping including contextualised skills."""
    print(f"\n{'='*70}")
    print("STEP 3: OCCUPATION-SKILL MAPPING")
    print(f"{'='*70}")

    # Load all data
    with open(OUTPUT_DIR / "occupation_matches_validated.json", "r", encoding="utf-8") as f:
        occ_matches = json.load(f)
    with open(OUTPUT_DIR / "skill_matches_tier1_validated.json", "r", encoding="utf-8") as f:
        t1_data = json.load(f)
    with open(OUTPUT_DIR / "skill_matches_tier2_validated.json", "r", encoding="utf-8") as f:
        t2_data = json.load(f)

    occs_df = pd.read_csv(ESCO_OCCS_CSV, encoding="utf-8")
    skills_df = pd.read_csv(ESCO_SKILLS_CSV, encoding="utf-8")
    rel_df = pd.read_csv(ESCO_OCC_SKILLS_CSV, encoding="utf-8")

    code_to_id = dict(zip(occs_df["CODE"].astype(str), occs_df["ID"]))
    skill_id_to_label = dict(zip(skills_df["ID"], skills_df["PREFERREDLABEL"]))
    skill_id_to_type = dict(zip(skills_df["ID"], skills_df["SKILLTYPE"]))

    # Build NOS title -> ESCO occupation lookup
    nos_to_esco = {}
    for o in occ_matches:
        nos_to_esco[o["nos_title"]] = {
            "decision": o["decision"],
            "esco_label": o.get("esco_label", ""),
            "esco_code": o.get("esco_code", ""),
            "nos_sector": o.get("nos_sector", ""),
        }

    mappings = []

    # A) Existing ESCO skills for matched occupations
    print("  Loading existing ESCO occupation-skill relations...")
    for o in occ_matches:
        if o["decision"] != "MATCH" or not o.get("esco_code"):
            continue
        occ_id = code_to_id.get(o["esco_code"], "")
        if not occ_id:
            continue
        rels = rel_df[rel_df["OCCUPATIONID"] == occ_id]
        for _, rel in rels.iterrows():
            mappings.append({
                "nos_occupation": o["nos_title"],
                "nos_sector": o.get("nos_sector", ""),
                "occ_decision": "MATCH",
                "esco_occupation": o["esco_label"],
                "skill_label": skill_id_to_label.get(rel["SKILLID"], ""),
                "skill_type": skill_id_to_type.get(rel["SKILLID"], ""),
                "relation_type": rel["RELATIONTYPE"],
                "skill_source": "esco_existing",
                "zambia_localized": False,
            })

    existing_count = len(mappings)
    print(f"  Existing ESCO mappings: {existing_count}")

    # B) New skills -> occupations (from consolidation)
    print("  Mapping new skills to occupations...")
    for _, row in df_new_skills.iterrows():
        label = str(row["label"])
        occ_list = str(row.get("nos_occupations", "")).split(", ")
        for occ_name in occ_list:
            occ_name = occ_name.strip().rstrip(".")
            if not occ_name:
                continue
            occ_info = nos_to_esco.get(occ_name, {})
            esco_occ = occ_info.get("esco_label", "") if occ_info.get("decision") == "MATCH" else f"NEW: {occ_name}"
            mappings.append({
                "nos_occupation": occ_name,
                "nos_sector": occ_info.get("nos_sector", ""),
                "occ_decision": occ_info.get("decision", ""),
                "esco_occupation": esco_occ,
                "skill_label": label,
                "skill_type": str(row["type"]),
                "relation_type": "essential",
                "skill_source": "zambia_new",
                "zambia_localized": True,
            })

    new_count = len(mappings) - existing_count
    print(f"  New skill mappings: {new_count}")

    # C) ACCEPT/CONTEXTUALIZE skills -> occupations
    # For MATCH occupations: attach ESCO skills not already in the profile
    # For NEW_LOCAL occupations: attach ALL matched ESCO skills (they have no existing profile)
    print("  Mapping ACCEPT/CONTEXTUALIZE skills to occupations...")
    ctx_match_count = 0
    ctx_newlocal_count = 0
    for v in t1_data + t2_data:
        if v["decision"] not in ("ACCEPT", "CONTEXTUALIZE"):
            continue
        esco_label = v.get("top_match_label", "")
        if not esco_label:
            continue

        occ_list = v.get("occupations", "").split(", ")
        for occ_name in occ_list:
            occ_name = occ_name.strip().rstrip(".")
            if not occ_name:
                continue
            occ_info = nos_to_esco.get(occ_name, {})
            occ_decision = occ_info.get("decision", "")

            if occ_decision == "MATCH":
                # Check if this ESCO skill is already attached
                esco_code = occ_info.get("esco_code", "")
                occ_id = code_to_id.get(esco_code, "")
                skill_row = skills_df[skills_df["PREFERREDLABEL"].str.lower() == esco_label.lower()]
                if skill_row.empty or not occ_id:
                    continue

                skill_id = skill_row.iloc[0]["ID"]
                already_attached = not rel_df[
                    (rel_df["OCCUPATIONID"] == occ_id) & (rel_df["SKILLID"] == skill_id)
                ].empty

                if not already_attached:
                    mappings.append({
                        "nos_occupation": occ_name,
                        "nos_sector": occ_info.get("nos_sector", ""),
                        "occ_decision": "MATCH",
                        "esco_occupation": occ_info.get("esco_label", ""),
                        "skill_label": esco_label,
                        "skill_type": skill_row.iloc[0]["SKILLTYPE"],
                        "relation_type": "essential",
                        "skill_source": "zambia_contextualized_new_attachment",
                        "zambia_localized": True,
                    })
                    ctx_match_count += 1

            elif occ_decision == "NEW_LOCAL":
                # NEW_LOCAL occupations get ALL matched ESCO skills attached
                skill_row = skills_df[skills_df["PREFERREDLABEL"].str.lower() == esco_label.lower()]
                skill_type = skill_row.iloc[0]["SKILLTYPE"] if not skill_row.empty else v.get("nos_category", "")
                # Map knowledge categories to ESCO types
                if skill_type in ("technical_knowledge", "regulatory_knowledge", "organisational_knowledge"):
                    skill_type = "knowledge"
                elif skill_type in ("core_skills", "professional_skills", "performance_criteria"):
                    skill_type = "skill/competence"

                mappings.append({
                    "nos_occupation": occ_name,
                    "nos_sector": occ_info.get("nos_sector", ""),
                    "occ_decision": "NEW_LOCAL",
                    "esco_occupation": f"NEW: {occ_name}",
                    "skill_label": esco_label,
                    "skill_type": skill_type,
                    "relation_type": "essential",
                    "skill_source": "esco_skill_for_new_local",
                    "zambia_localized": True,
                })
                ctx_newlocal_count += 1

    print(f"  Contextualised new attachments (MATCH): {ctx_match_count}")
    print(f"  ESCO skills attached to NEW_LOCAL: {ctx_newlocal_count}")
    print(f"  Total mappings: {len(mappings)}")

    # Build DataFrame
    df_map = pd.DataFrame(mappings)

    # Deduplicate (same occupation + same skill)
    before = len(df_map)
    df_map = df_map.drop_duplicates(subset=["nos_occupation", "skill_label"], keep="first")
    print(f"  After dedup: {len(df_map)} (removed {before - len(df_map)} duplicates)")

    return df_map


# =========================================================================
# SAVE OUTPUTS
# =========================================================================

def save_outputs(df_skills: pd.DataFrame, df_map: pd.DataFrame) -> None:
    """Save final Excel outputs."""
    print(f"\n{'='*70}")
    print("SAVING OUTPUTS")
    print(f"{'='*70}")

    # New skills Excel
    skills_path = OUTPUT_DIR / "zambia_new_skills_final.xlsx"

    # Load alt labels from consolidation
    try:
        with pd.ExcelFile(OUTPUT_DIR / "zambia_new_skills.xlsx") as xls:
            df_alt = pd.read_excel(xls, sheet_name="Alt Labels")
    except Exception:
        df_alt = pd.DataFrame(columns=["esco_skill", "new_alt_label"])

    with pd.ExcelWriter(skills_path, engine="openpyxl") as writer:
        df_skills.to_excel(writer, sheet_name="All New Skills", index=False)
        df_skills[df_skills["type"] == "skill/competence"].to_excel(
            writer, sheet_name="New Skills", index=False)
        df_skills[df_skills["type"] == "knowledge"].to_excel(
            writer, sheet_name="New Knowledge", index=False)
        df_alt.to_excel(writer, sheet_name="Alt Labels", index=False)

    print(f"  Wrote {skills_path.name}")

    # Occupation-skill map Excel
    map_path = OUTPUT_DIR / "zambia_skill_occupation_map.xlsx"
    with pd.ExcelWriter(map_path, engine="openpyxl") as writer:
        df_map.to_excel(writer, sheet_name="Full Map", index=False)
        df_map[df_map["zambia_localized"] == True].to_excel(
            writer, sheet_name="Zambia Localized Only", index=False)

        # Summary per occupation
        summary = df_map.groupby(["nos_occupation", "occ_decision", "esco_occupation"]).agg(
            total_skills=("skill_label", "count"),
            esco_existing=("skill_source", lambda x: sum(1 for v in x if v == "esco_existing")),
            zambia_new=("skill_source", lambda x: sum(1 for v in x if v == "zambia_new")),
            zambia_ctx=("skill_source", lambda x: sum(1 for v in x if v == "zambia_contextualized_new_attachment")),
            esco_for_new_local=("skill_source", lambda x: sum(1 for v in x if v == "esco_skill_for_new_local")),
        ).reset_index()
        summary.to_excel(writer, sheet_name="Occupation Summary", index=False)

    print(f"  Wrote {map_path.name}")

    # Summary JSON
    summary_data = {
        "new_skills": {
            "total": len(df_skills),
            "with_description": int(df_skills["description"].astype(bool).sum()) if "description" in df_skills.columns else 0,
            "with_hierarchy": int(df_skills["parent_skill_group"].astype(bool).sum()) if "parent_skill_group" in df_skills.columns else 0,
            "skill_competence": int((df_skills["type"] == "skill/competence").sum()),
            "knowledge": int((df_skills["type"] == "knowledge").sum()),
        },
        "alt_labels": {
            "esco_skills_with_alt_labels": int(df_alt["esco_skill"].nunique()) if len(df_alt) > 0 else 0,
            "total_alt_labels": len(df_alt),
        },
        "occupation_skill_map": {
            "total_mappings": len(df_map),
            "esco_existing": int((df_map["skill_source"] == "esco_existing").sum()),
            "zambia_new": int((df_map["skill_source"] == "zambia_new").sum()),
            "zambia_ctx_new_attachment": int((df_map["skill_source"] == "zambia_contextualized_new_attachment").sum()),
            "esco_skill_for_new_local": int((df_map["skill_source"] == "esco_skill_for_new_local").sum()),
        },
    }

    with open(OUTPUT_DIR / "zambia_finalize_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary_data, f, indent=2)
    print(f"\n{json.dumps(summary_data, indent=2)}")


# =========================================================================
# MAIN
# =========================================================================

def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    parser = argparse.ArgumentParser()
    parser.add_argument("--describe", action="store_true", help="Generate descriptions only")
    parser.add_argument("--place", action="store_true", help="Hierarchy placement only")
    parser.add_argument("--map", action="store_true", help="Occupation mapping only")
    args = parser.parse_args()

    # Load new skills
    df_skills = pd.read_excel(OUTPUT_DIR / "zambia_new_skills.xlsx", sheet_name="All New Skills")

    if args.describe:
        df_skills = run_descriptions(df_skills)
        df_skills.to_excel(OUTPUT_DIR / "zambia_new_skills.xlsx", sheet_name="All New Skills", index=False)
    elif args.place:
        df_skills = run_hierarchy_placement(df_skills)
        df_skills.to_excel(OUTPUT_DIR / "zambia_new_skills.xlsx", sheet_name="All New Skills", index=False)
    elif args.map:
        df_map = run_occupation_mapping(df_skills)
        save_outputs(df_skills, df_map)
    else:
        # Full pipeline
        df_skills = run_descriptions(df_skills)
        df_skills = run_hierarchy_placement(df_skills)
        df_map = run_occupation_mapping(df_skills)
        save_outputs(df_skills, df_map)


if __name__ == "__main__":
    main()
