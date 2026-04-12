"""
PC (Performance Criteria) Gap Analysis.

For each NOS occupation, compare its PCs (task-level descriptions) against
the ESCO occupation's existing skill set to identify:
1. Which ESCO skills are evidenced by the PCs
2. Skill gaps - PCs that reveal skills/knowledge not in the current ESCO profile

This is NOT direct matching. PCs are tasks. The LLM identifies the underlying
skills/knowledge that these tasks evidence.

Prerequisites:
  - outputs/nos_extractions.json
  - outputs/occupation_matches_validated.json
  - shared_data/esco_taxonomy/ (occupations, skills, occupation_to_skill_relations)
  - GEMINI_API_KEY in .env

Output:
  - outputs/pc_gap_analysis.json
  - outputs/pc_gap_analysis.xlsx
"""

import json
import sys
import io
import os
import time
import re
import pandas as pd
from pathlib import Path
import google.generativeai as genai
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

BASE_PATH = Path(__file__).parent.parent.parent.parent
load_dotenv(BASE_PATH / ".env")

NOS_EXTRACTIONS = Path(__file__).parent.parent / "outputs" / "nos_extractions.json"
OCC_MATCHES = Path(__file__).parent.parent / "outputs" / "occupation_matches_validated.json"
ESCO_OCCS = BASE_PATH / "shared_data" / "esco_taxonomy" / "occupations.csv"
ESCO_SKILLS = BASE_PATH / "shared_data" / "esco_taxonomy" / "skills.csv"
ESCO_OCC_SKILLS = BASE_PATH / "shared_data" / "esco_taxonomy" / "occupation_to_skill_relations.csv"
OUTPUT_DIR = Path(__file__).parent.parent / "outputs"
CHECKPOINT_FILE = OUTPUT_DIR / "pc_gap_checkpoint.json"

MODEL_NAME = "models/gemini-2.0-flash"
MAX_RETRIES = 5


SYSTEM_PROMPT = """You are an expert at analyzing occupational competencies using the ESCO framework.

You are given:
1. A Zambia NOS occupation with its Performance Criteria (PCs) - these are TASKS, not skills
2. The matched ESCO occupation's existing skill/knowledge profile

Your task is to identify SKILL GAPS: tasks described in the PCs that require skills or knowledge NOT already in the ESCO occupation's profile.

Important distinctions:
- Tasks are specific work activities (what someone does)
- Skills are underlying capabilities (what someone can do)
- Multiple tasks often map to ONE skill
- Do NOT create task-level items as skills

For each gap you identify:
- State whether it is a skill/competence (verb phrase) or knowledge (noun phrase)
- Phrase it in ESCO style:
  - Skills: verb + object [+ qualifier], lowercase, 2-8 words
  - Knowledge: noun phrase, no "knowledge of", lowercase, 2-8 words
- Explain which PCs evidence this gap

Reply with ONLY a JSON object:
{
  "gaps": [
    {
      "type": "skill/competence" or "knowledge",
      "label": "esco-style label",
      "evidencing_pcs": ["PC1 text", "PC2 text"],
      "rationale": "brief explanation of why this is a gap"
    }
  ],
  "coverage_assessment": "brief assessment of how well existing ESCO skills cover the NOS PCs"
}

If no gaps are found, return {"gaps": [], "coverage_assessment": "..."}"""


def load_esco_skills_for_occupation(occ_code: str, occs_df: pd.DataFrame,
                                     skills_df: pd.DataFrame,
                                     rel_df: pd.DataFrame) -> list[dict]:
    """Get all skills attached to an ESCO occupation."""
    occ_row = occs_df[occs_df["CODE"] == occ_code]
    if occ_row.empty:
        return []

    occ_id = occ_row.iloc[0]["ID"]
    rels = rel_df[rel_df["OCCUPATIONID"] == occ_id]

    result = []
    for _, rel in rels.iterrows():
        skill_row = skills_df[skills_df["ID"] == rel["SKILLID"]]
        if not skill_row.empty:
            result.append({
                "label": skill_row.iloc[0]["PREFERREDLABEL"],
                "type": skill_row.iloc[0]["SKILLTYPE"],
                "relation": rel["RELATIONTYPE"],
            })
    return result


def build_user_prompt(nos_title: str, nos_pcs: list[str],
                       esco_label: str, esco_skills: list[dict]) -> str:
    """Build prompt for gap analysis."""
    # Format PCs (limit to first 40 to stay within context)
    pc_text = ""
    for i, pc in enumerate(nos_pcs[:40]):
        pc_text += f"  PC{i+1}: {pc}\n"

    # Format existing ESCO skills
    essential = [s for s in esco_skills if s["relation"] == "essential"]
    optional = [s for s in esco_skills if s["relation"] == "optional"]

    skills_text = "Essential skills/knowledge:\n"
    for s in essential:
        skills_text += f"  [{s['type']}] {s['label']}\n"
    skills_text += f"\nOptional skills/knowledge ({len(optional)} items):\n"
    for s in optional[:20]:
        skills_text += f"  [{s['type']}] {s['label']}\n"
    if len(optional) > 20:
        skills_text += f"  ... and {len(optional) - 20} more\n"

    return f"""NOS Occupation: {nos_title}
Performance Criteria (tasks this worker must do):
{pc_text}
Matched ESCO Occupation: {esco_label}
Existing ESCO skills/knowledge profile:
{skills_text}
Identify any skill or knowledge gaps - capabilities required by the PCs that are NOT covered by the existing ESCO profile."""


def call_llm(system_prompt: str, user_prompt: str) -> str:
    model = genai.GenerativeModel(MODEL_NAME, system_instruction=system_prompt)
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


def parse_response(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```json?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"gaps": [], "coverage_assessment": "parse error", "raw": text}


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

    # Load data
    with open(NOS_EXTRACTIONS, "r", encoding="utf-8") as f:
        extractions = json.load(f)
    with open(OCC_MATCHES, "r", encoding="utf-8") as f:
        occ_matches = json.load(f)

    occs_df = pd.read_csv(ESCO_OCCS, encoding="utf-8")
    skills_df = pd.read_csv(ESCO_SKILLS, encoding="utf-8")
    rel_df = pd.read_csv(ESCO_OCC_SKILLS, encoding="utf-8")

    # Build lookup
    occ_match_lookup = {o["nos_title"]: o for o in occ_matches}

    # Load checkpoint
    checkpoint = {}
    if CHECKPOINT_FILE.exists():
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            checkpoint = json.load(f)
    print(f"Checkpoint: {len(checkpoint)} already analyzed")

    results = []
    for ext in extractions:
        title = ext["overview"].get("job_title", ext["occupation_from_filename"])
        match = occ_match_lookup.get(title, {})

        # Get PCs for this occupation
        pcs = [item["text"] for item in ext["skill_phrases"].get("performance_criteria", [])]
        if not pcs:
            continue

        # Skip if already done
        if title in checkpoint:
            results.append(checkpoint[title])
            continue

        esco_code = match.get("esco_code", "")
        esco_label = match.get("esco_label", "")
        decision = match.get("decision", "")

        # For NEW_LOCAL occupations, we can't compare to ESCO skills
        if decision == "NEW_LOCAL":
            result = {
                "nos_title": title,
                "nos_sector": ext.get("sector", ""),
                "decision": "NEW_LOCAL",
                "esco_label": "",
                "num_pcs": len(pcs),
                "gaps": [],
                "coverage_assessment": "NEW_LOCAL occupation - all PCs represent new skill requirements",
                "sample_pcs": pcs[:10],
            }
            results.append(result)
            checkpoint[title] = result
            print(f"[NEW_LOCAL] {title}: {len(pcs)} PCs (skipped - no ESCO to compare)")
            continue

        # Get ESCO skills for matched occupation
        esco_skills = load_esco_skills_for_occupation(esco_code, occs_df, skills_df, rel_df)

        print(f"Analyzing: {title} -> {esco_label} ({len(pcs)} PCs, {len(esco_skills)} ESCO skills)")

        user_prompt = build_user_prompt(title, pcs, esco_label, esco_skills)
        raw_response = call_llm(SYSTEM_PROMPT, user_prompt)
        parsed = parse_response(raw_response)

        result = {
            "nos_title": title,
            "nos_sector": ext.get("sector", ""),
            "decision": "MATCH",
            "esco_label": esco_label,
            "esco_code": esco_code,
            "num_pcs": len(pcs),
            "num_esco_skills": len(esco_skills),
            "gaps": parsed.get("gaps", []),
            "coverage_assessment": parsed.get("coverage_assessment", ""),
            "num_gaps": len(parsed.get("gaps", [])),
        }
        results.append(result)
        checkpoint[title] = result

        gap_count = len(parsed.get("gaps", []))
        print(f"  -> {gap_count} gaps found. {parsed.get('coverage_assessment', '')[:80]}")

        with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
            json.dump(checkpoint, f, indent=2, ensure_ascii=False)

        time.sleep(1)

    # Summary
    print(f"\n{'='*70}")
    print("PC GAP ANALYSIS RESULTS")
    print(f"{'='*70}")

    matched = [r for r in results if r["decision"] == "MATCH"]
    new_local = [r for r in results if r["decision"] == "NEW_LOCAL"]

    total_gaps = sum(r.get("num_gaps", 0) for r in matched)
    total_pcs = sum(r["num_pcs"] for r in results)

    print(f"Occupations analyzed: {len(matched)} matched + {len(new_local)} new_local")
    print(f"Total PCs reviewed: {total_pcs}")
    print(f"Skill gaps found: {total_gaps}")

    # Gap type breakdown
    all_gaps = []
    for r in matched:
        for gap in r.get("gaps", []):
            all_gaps.append(gap)

    skill_gaps = [g for g in all_gaps if g.get("type") == "skill/competence"]
    knowledge_gaps = [g for g in all_gaps if g.get("type") == "knowledge"]
    print(f"  Skill/competence gaps: {len(skill_gaps)}")
    print(f"  Knowledge gaps: {len(knowledge_gaps)}")

    print(f"\nOccupations with most gaps:")
    for r in sorted(matched, key=lambda x: -x.get("num_gaps", 0))[:10]:
        print(f"  {r['num_gaps']:3d} gaps | {r['nos_title']} -> {r['esco_label']}")

    # Save
    json_path = OUTPUT_DIR / "pc_gap_analysis.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {json_path.name}")

    # Excel
    excel_path = OUTPUT_DIR / "pc_gap_analysis.xlsx"
    summary_rows = []
    gap_rows = []

    for r in results:
        summary_rows.append({
            "nos_title": r["nos_title"],
            "nos_sector": r.get("nos_sector", ""),
            "decision": r["decision"],
            "esco_label": r.get("esco_label", ""),
            "num_pcs": r["num_pcs"],
            "num_esco_skills": r.get("num_esco_skills", ""),
            "num_gaps": r.get("num_gaps", 0),
            "coverage_assessment": r.get("coverage_assessment", ""),
        })

        for gap in r.get("gaps", []):
            gap_rows.append({
                "nos_title": r["nos_title"],
                "nos_sector": r.get("nos_sector", ""),
                "esco_label": r.get("esco_label", ""),
                "gap_type": gap.get("type", ""),
                "gap_label": gap.get("label", ""),
                "rationale": gap.get("rationale", ""),
                "evidencing_pcs": " | ".join(gap.get("evidencing_pcs", [])[:3]),
            })

    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        pd.DataFrame(summary_rows).to_excel(writer, sheet_name="Summary", index=False)
        if gap_rows:
            df_gaps = pd.DataFrame(gap_rows)
            df_gaps.to_excel(writer, sheet_name="All Gaps", index=False)
            df_gaps[df_gaps["gap_type"] == "skill/competence"].to_excel(
                writer, sheet_name="Skill Gaps", index=False)
            df_gaps[df_gaps["gap_type"] == "knowledge"].to_excel(
                writer, sheet_name="Knowledge Gaps", index=False)

    print(f"Wrote {excel_path.name}")


if __name__ == "__main__":
    main()
