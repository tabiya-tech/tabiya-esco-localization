"""
Score ESCO skill relevance for a country's labor market by 4-digit ISCO group.

For each unique (ISCO-4, skill) pair, an LLM evaluates:
- relevance_score: High / Moderate / Low
- reasoning_economist: structural economic rationale
- kenyan_adaptation: how the skill is actually performed locally (for Moderate skills)

Reads the system prompt from config/relevance_prompt.md so domain experts can
update market context without touching code.

Outputs standalone CSV/JSON files (does NOT modify taxonomy files).

Deduplicates 134k+ occupation-skill relations to ~67k unique (ISCO-4, skill) pairs.
Processes one skill at a time per LLM call for quality; batches per ISCO group for
checkpoint granularity.

Usage:
    python scripts/07_skill_relevance_scoring.py --group 1112
    python scripts/07_skill_relevance_scoring.py --all
    python scripts/07_skill_relevance_scoring.py --all --resume
    python scripts/07_skill_relevance_scoring.py --export-only
"""

import os
import json
import argparse
import hashlib
import time
import re
import threading
import pandas as pd
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
import google.generativeai as genai

BASE_PATH = Path(__file__).parent.parent
ROOT_PATH = BASE_PATH.parent.parent
SHARED_DATA = ROOT_PATH / "shared_data" / "esco_taxonomy"
OUTPUT_PATH = BASE_PATH / "outputs"
TAXONOMY_PATH = OUTPUT_PATH / "taxonomy"
CONFIG_PATH = BASE_PATH / "config"

CHECKPOINT_FILE = OUTPUT_PATH / "skill_relevance_checkpoint.json"
OUTPUT_CSV = OUTPUT_PATH / "skill_relevance_kenya.csv"
OUTPUT_JSON = OUTPUT_PATH / "skill_relevance_kenya.json"

SKILL_BATCH_SIZE = 80
MAX_RETRIES = 5
MODEL_NAME = "gemini-3-flash-preview"

load_dotenv(ROOT_PATH / ".env")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(MODEL_NAME)


def load_system_prompt() -> str:
    """Load system prompt from config/relevance_prompt.md."""
    prompt_file = CONFIG_PATH / "relevance_prompt.md"
    if not prompt_file.exists():
        raise FileNotFoundError(
            f"System prompt not found: {prompt_file}\n"
            "Create config/relevance_prompt.md with market context for this country."
        )
    text = prompt_file.read_text(encoding="utf-8")
    # Strip markdown frontmatter title if present
    text = re.sub(r"^#[^\n]*\n*", "", text).strip()
    text += "\n\nYou MUST return valid JSON only. No markdown, no commentary outside the JSON."
    return text


def prompt_hash(text: str) -> str:
    """Short hash of prompt text for versioning."""
    return hashlib.sha256(text.encode()).hexdigest()[:12]


SYSTEM_PROMPT = load_system_prompt()
PROMPT_VERSION = prompt_hash(SYSTEM_PROMPT)


def load_data() -> dict:
    """Load all required data sources."""
    print("Loading data...")

    # ISCO groups
    groups_df = pd.read_csv(TAXONOMY_PATH / "occupation_groups.csv")
    isco_groups = {}
    for _, row in groups_df.iterrows():
        code = str(row["CODE"])
        isco_groups[code] = {
            "code": code,
            "label": row["PREFERREDLABEL"],
            "description": str(row.get("DESCRIPTION", "")) if pd.notna(row.get("DESCRIPTION")) else "",
        }
    print(f"  ISCO groups: {len(isco_groups)}")

    # Occupations
    occs_df = pd.read_csv(TAXONOMY_PATH / "occupations.csv")
    occ_id_to_info = {}
    for _, row in occs_df.iterrows():
        occ_id_to_info[row["ID"]] = {
            "code": str(row["CODE"]),
            "label": row["PREFERREDLABEL"],
            "isco4": str(row["OCCUPATIONGROUPCODE"]),
        }
    print(f"  Occupations: {len(occ_id_to_info)}")

    # Skills
    skills_df = pd.read_csv(SHARED_DATA / "skills.csv")
    skill_lookup = {}
    for _, row in skills_df.iterrows():
        skill_lookup[row["ID"]] = {
            "id": row["ID"],
            "label": row["PREFERREDLABEL"],
            "description": str(row.get("DESCRIPTION", ""))[:300] if pd.notna(row.get("DESCRIPTION")) else "",
            "skill_type": row.get("SKILLTYPE", ""),
        }
    print(f"  Skills: {len(skill_lookup)}")

    # Occupation-to-skill relations
    rels_df = pd.read_csv(TAXONOMY_PATH / "occupation_to_skill_relations.csv", low_memory=False)
    print(f"  Relations: {len(rels_df)}")

    # Map relations to (ISCO4, SKILLID) pairs
    rels_df["ISCO4"] = rels_df["OCCUPATIONID"].map(lambda x: occ_id_to_info.get(x, {}).get("isco4"))

    # Deduplicate
    deduped = rels_df[["ISCO4", "SKILLID"]].dropna(subset=["ISCO4"]).drop_duplicates()
    print(f"  Unique (ISCO4, SKILLID) pairs: {len(deduped)}")

    # Group skills by ISCO4
    isco4_skills = {}
    for _, row in deduped.iterrows():
        isco4 = row["ISCO4"]
        skill_id = row["SKILLID"]
        if isco4 not in isco4_skills:
            isco4_skills[isco4] = []
        if skill_id in skill_lookup:
            isco4_skills[isco4].append(skill_lookup[skill_id])
    print(f"  ISCO4 groups with skills: {len(isco4_skills)}")

    # Map ISCO4 -> list of occupation labels
    isco4_occupations = {}
    for occ_id, info in occ_id_to_info.items():
        isco4 = info["isco4"]
        if isco4 not in isco4_occupations:
            isco4_occupations[isco4] = []
        isco4_occupations[isco4].append(info["label"])

    return {
        "isco_groups": isco_groups,
        "isco4_skills": isco4_skills,
        "isco4_occupations": isco4_occupations,
        "skill_lookup": skill_lookup,
    }


def build_task_prompt(group_info: dict, occupations: list[str], skills: list[dict]) -> str:
    """Build the task prompt for one batch of skills in an ISCO group."""

    occ_list = "\n".join(f"- {occ}" for occ in sorted(set(occupations)))

    skill_lines = []
    for i, s in enumerate(skills, 1):
        desc_short = s["description"][:200] if s["description"] else "No description"
        skill_lines.append(f'{i}. "{s["label"]}" ({s["skill_type"]}): {desc_short}')
    skill_list = "\n".join(skill_lines)

    return f"""**Input Data:**
* **Broader Occupation Group:** {group_info['code']} - {group_info['label']}
* **Group Description:** {group_info['description'][:500]}
* **Occupations in this group:**
{occ_list}

**Skills to evaluate ({len(skills)} total):**
{skill_list}

**Task:**
For each skill, analyze it against the market context defined in your system instructions.

1. **Reasoning:** Briefly analyze the mechanism. Does this skill map to the local production function? Is it replaced by labor or a different technology?
2. **Modification:** If the skill is relevant but usually performed differently locally, specify the local equivalent.
3. **Score:** Assign a discrete classification: "High", "Moderate", or "Low".

Return a JSON array with one object per skill:
[
  {{
    "skill_name": "exact skill name from the list",
    "relevance_score": "High" | "Moderate" | "Low",
    "reasoning_economist": "2-3 sentences explaining the structural reason for the score (e.g., labor substitution, tech difference, regulatory difference).",
    "kenyan_adaptation": "If Moderate, briefly describe how this is actually done in Kenya (e.g., 'Done manually' or 'Using mobile money'). If High or Low, put 'N/A'."
  }}
]

Return ONLY the JSON array. No other text."""


def parse_llm_response(response_text: str, expected_count: int) -> list[dict]:
    """Parse LLM JSON response, handling common formatting issues."""
    text = response_text.strip()

    # Strip markdown code fences
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    parsed = json.loads(text)

    if not isinstance(parsed, list):
        raise ValueError(f"Expected JSON array, got {type(parsed)}")

    if len(parsed) != expected_count:
        print(f"  WARNING: Expected {expected_count} results, got {len(parsed)}")

    return parsed


def score_skill_batch(
    group_info: dict,
    occupations: list[str],
    skills: list[dict],
) -> list[dict]:
    """Score a batch of skills for one ISCO group via LLM."""

    prompt = build_task_prompt(group_info, occupations, skills)

    for attempt in range(MAX_RETRIES):
        try:
            response = model.generate_content(
                [SYSTEM_PROMPT, prompt],
                generation_config=genai.types.GenerationConfig(
                    temperature=0.2,
                    max_output_tokens=8192 * 4,
                    response_mime_type="application/json",
                ),
            )
            results = parse_llm_response(response.text, len(skills))

            # Build a lookup by skill name for matching
            result_lookup = {r["skill_name"].lower(): r for r in results}

            scored = []
            for s in skills:
                match = result_lookup.get(s["label"].lower())
                if match:
                    scored.append({
                        "skill_id": s["id"],
                        "skill_label": s["label"],
                        "skill_type": s["skill_type"],
                        "relevance_score": match.get("relevance_score", "Moderate"),
                        "reasoning_economist": match.get("reasoning_economist", ""),
                        "kenyan_adaptation": match.get("kenyan_adaptation", "N/A"),
                    })
                else:
                    print(f"  WARNING: No LLM result for '{s['label']}' - defaulting to Moderate")
                    scored.append({
                        "skill_id": s["id"],
                        "skill_label": s["label"],
                        "skill_type": s["skill_type"],
                        "relevance_score": "Moderate",
                        "reasoning_economist": "No LLM response for this skill",
                        "kenyan_adaptation": "N/A",
                    })
            return scored

        except json.JSONDecodeError as e:
            print(f"  JSON parse error (attempt {attempt+1}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(5)
        except Exception as e:
            if "429" in str(e) or "quota" in str(e).lower():
                wait = 30 * (attempt + 1)
                print(f"  Rate limit (attempt {attempt+1}/{MAX_RETRIES}), waiting {wait}s...")
                time.sleep(wait)
            else:
                print(f"  Error (attempt {attempt+1}/{MAX_RETRIES}): {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(5)
                else:
                    raise

    raise RuntimeError(f"Failed after {MAX_RETRIES} attempts")


def load_checkpoint() -> dict:
    """Load checkpoint of completed groups."""
    if CHECKPOINT_FILE.exists():
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"completed_groups": {}, "metadata": {}}


def save_checkpoint(checkpoint: dict) -> None:
    """Save checkpoint."""
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(checkpoint, f, ensure_ascii=False, indent=2)


def export_outputs(checkpoint: dict, data: dict) -> None:
    """Export standalone CSV and JSON from checkpoint data. Does NOT modify taxonomy."""

    all_rows = []
    json_groups = {}

    for isco4, group_data in sorted(checkpoint["completed_groups"].items()):
        group_info = data["isco_groups"].get(isco4, {"label": isco4, "description": ""})
        occupations = data["isco4_occupations"].get(isco4, [])

        json_groups[isco4] = {
            "label": group_info.get("label", ""),
            "description": group_info.get("description", ""),
            "occupations": sorted(set(occupations)),
            "skills": group_data["skills"],
        }

        for s in group_data["skills"]:
            all_rows.append({
                "ISCO4": isco4,
                "ISCO4_LABEL": group_info.get("label", ""),
                "SKILLID": s["skill_id"],
                "SKILL_LABEL": s["skill_label"],
                "SKILL_TYPE": s["skill_type"],
                "RELEVANCE": s["relevance_score"],
                "REASONING": s["reasoning_economist"],
                "ADAPTATION": s["kenyan_adaptation"],
            })

    # CSV
    df = pd.DataFrame(all_rows)
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"\nCSV: {len(df)} rows -> {OUTPUT_CSV}")

    # JSON with run metadata
    dist = df["RELEVANCE"].value_counts().to_dict() if len(df) > 0 else {}

    json_output = {
        "metadata": {
            "date": datetime.now().isoformat(),
            "model": MODEL_NAME,
            "country": "Kenya",
            "prompt_version": checkpoint.get("metadata", {}).get("prompt_version", PROMPT_VERSION),
            "config_file": "config/relevance_prompt.md",
            "total_groups": len(json_groups),
            "total_skill_pairs": len(all_rows),
            "distribution": dist,
        },
        "groups": json_groups,
    }

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(json_output, f, ensure_ascii=False, indent=2)
    print(f"JSON: {len(json_groups)} groups -> {OUTPUT_JSON}")


def main():
    parser = argparse.ArgumentParser(description="Score skill relevance by ISCO group")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--group", nargs="+", help="ISCO-4 group codes to process")
    group.add_argument("--all", action="store_true", help="Process all ISCO-4 groups")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    parser.add_argument("--workers", type=int, default=10, help="Parallel workers (default: 10)")
    parser.add_argument("--export-only", action="store_true", help="Export CSV/JSON from existing checkpoint")
    args = parser.parse_args()

    print("=" * 70)
    print("SKILL RELEVANCE SCORING BY ISCO GROUP")
    print(f"Model: {MODEL_NAME} | Prompt version: {PROMPT_VERSION}")
    print(f"Config: {CONFIG_PATH / 'relevance_prompt.md'}")
    print("=" * 70)

    data = load_data()
    checkpoint = load_checkpoint() if (args.resume or args.export_only) else {"completed_groups": {}, "metadata": {}}

    # Store prompt version in checkpoint
    checkpoint.setdefault("metadata", {})["prompt_version"] = PROMPT_VERSION

    if args.export_only:
        export_outputs(checkpoint, data)
        return

    # Determine groups to process
    if args.all:
        groups_to_process = sorted(data["isco4_skills"].keys())
    else:
        groups_to_process = args.group

    # Filter already completed
    if args.resume:
        already_done = set(checkpoint["completed_groups"].keys())
        remaining = [g for g in groups_to_process if g not in already_done]
        print(f"\nResuming: {len(already_done)} done, {len(remaining)} remaining")
        groups_to_process = remaining
    else:
        print(f"\nProcessing {len(groups_to_process)} ISCO groups")

    checkpoint_lock = threading.Lock()
    completed_count = [0]
    total_groups = len(groups_to_process)

    def process_group(isco4: str) -> tuple[str, list[dict] | None]:
        """Process a single ISCO group. Returns (isco4, scored_skills) or (isco4, None) on skip."""
        skills = data["isco4_skills"].get(isco4, [])
        if not skills:
            return isco4, None

        group_info = data["isco_groups"].get(isco4, {"code": isco4, "label": isco4, "description": ""})
        occupations = data["isco4_occupations"].get(isco4, [])

        all_scored = []
        for batch_start in range(0, len(skills), SKILL_BATCH_SIZE):
            batch = skills[batch_start:batch_start + SKILL_BATCH_SIZE]
            scored = score_skill_batch(group_info, occupations, batch)
            all_scored.extend(scored)

        return isco4, all_scored

    print(f"\nRunning with {args.workers} parallel workers")

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(process_group, isco4): isco4 for isco4 in groups_to_process}

        for future in as_completed(futures):
            isco4 = futures[future]
            try:
                isco4, scored = future.result()

                with checkpoint_lock:
                    completed_count[0] += 1
                    idx = completed_count[0]

                if scored is None:
                    print(f"[{idx}/{total_groups}] SKIP {isco4}: no skills")
                    continue

                dist = {}
                for s in scored:
                    dist[s["relevance_score"]] = dist.get(s["relevance_score"], 0) + 1
                adapted = sum(1 for s in scored if s["kenyan_adaptation"] != "N/A")
                print(f"[{idx}/{total_groups}] ISCO {isco4}: {len(scored)} skills, {dist}, adaptations: {adapted}")

                with checkpoint_lock:
                    checkpoint["completed_groups"][isco4] = {"skills": scored}
                    save_checkpoint(checkpoint)

            except Exception as e:
                print(f"[ERROR] ISCO {isco4}: {e}")

    # Export final outputs
    print("\n" + "=" * 70)
    print("EXPORTING RESULTS")
    print("=" * 70)
    export_outputs(checkpoint, data)

    # Summary
    total = sum(len(g["skills"]) for g in checkpoint["completed_groups"].values())
    print(f"\nDone: {len(checkpoint['completed_groups'])} groups, {total} skill scores")


if __name__ == "__main__":
    main()
