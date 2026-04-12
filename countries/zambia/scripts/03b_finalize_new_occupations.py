"""
Generate ESCO-style descriptions and alternative labels for NEW_LOCAL occupations.

For each NEW_LOCAL occupation, uses the NOS description, purpose, and unit titles
to generate:
  - An ESCO-style occupation description
  - Alternative labels (synonyms, related job titles)
  - An empty ISCO unit group code column for human assignment

Usage:
  python 03b_finalize_new_occupations.py               # Generate descriptions + alt labels
  python 03b_finalize_new_occupations.py --apply-codes  # Read ISCO codes from reviewed Excel

Prerequisites:
  - outputs/occupation_matches_validated.json (from 03_validate_occupation_matches.py)
  - outputs/nos_extractions.json (for NOS context)
  - GEMINI_API_KEY in .env

Output:
  - outputs/new_occupations_finalized.json
  - outputs/new_occupations_finalized.xlsx (includes empty isco_unit_group_code column)
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
OCC_MATCHES = OUTPUT_DIR / "occupation_matches_validated.json"
NOS_EXTRACTIONS = OUTPUT_DIR / "nos_extractions.json"

LLM_MODEL = "models/gemini-2.0-flash"
MAX_RETRIES = 5


SYSTEM_PROMPT = """You are an expert at writing ESCO-style occupation descriptions and labels.

You are given a Zambia National Occupational Standard (NOS) occupation that has no equivalent in ESCO and needs to be created as a new occupation.

You must generate:

1. An ESCO-style occupation description:
   - 2-4 sentences
   - Describes what the worker does, the context they work in, and key responsibilities
   - Written in third person plural (e.g., "Professional drivers transport...")
   - Factual and neutral, no promotional language
   - Do not reference Zambia specifically in the description

2. Alternative labels (3-8 synonyms or related job titles):
   - Other titles someone in this role might be known by
   - Include both formal and informal variants
   - Lowercase unless proper nouns
   - Can include more specific or more general variants

Reply with ONLY a JSON object:
{
  "preferred_label": "the primary occupation title",
  "description": "ESCO-style description",
  "alt_labels": ["label1", "label2", "label3", ...]
}"""


USER_PROMPT_TEMPLATE = """NOS Occupation:
- Title: {title}
- Sector: {sector}
- Description: {description}
- Purpose: {purpose}
- Key functions (unit titles): {unit_titles}
- ZQF Level: {zqf_level}
- Reason not matched to ESCO: {reason}

Generate an ESCO-style description and alternative labels for this occupation."""


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


def parse_response(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```json?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def apply_isco_codes() -> None:
    """Read ISCO codes from reviewed Excel and update the JSON."""
    excel_path = OUTPUT_DIR / "new_occupations_finalized.xlsx"
    json_path = OUTPUT_DIR / "new_occupations_finalized.json"

    df = pd.read_excel(excel_path, sheet_name="New Occupations")
    with open(json_path, "r", encoding="utf-8") as f:
        results = json.load(f)

    # Build lookup from Excel
    code_lookup = {}
    for _, row in df.iterrows():
        title = str(row["nos_title"])
        code = str(row.get("isco_unit_group_code", "")).strip()
        if code and code != "nan":
            code_lookup[title] = code

    # Update JSON
    updated = 0
    for r in results:
        code = code_lookup.get(r["nos_title"], "")
        if code:
            r["isco_unit_group_code"] = code
            updated += 1

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"Applied ISCO codes: {updated}/{len(results)}")
    missing = [r["nos_title"] for r in results if not r.get("isco_unit_group_code")]
    if missing:
        print(f"Still missing codes:")
        for m in missing:
            print(f"  {m}")


def run_generate() -> None:
    """Generate descriptions, alt labels, and output Excel with ISCO column."""
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

    # Load occupation matches
    with open(OCC_MATCHES, "r", encoding="utf-8") as f:
        occ_data = json.load(f)

    # Load NOS extractions for full context
    with open(NOS_EXTRACTIONS, "r", encoding="utf-8") as f:
        extractions = json.load(f)

    # Build NOS context lookup
    nos_context = {}
    for ext in extractions:
        title = ext["overview"].get("job_title", ext["occupation_from_filename"])
        units = [u.get("title", "").strip(". ") for u in ext.get("units", [])]
        units = [re.sub(r"^Unit No\.\s*\d+\s*Unit Title\s*", "", u).strip() for u in units]
        units = [u for u in units if u and len(u) > 3]
        nos_context[title] = {
            "description": ext["overview"].get("job_description", ""),
            "purpose": ext["overview"].get("job_purpose", ""),
            "sector": ext.get("sector", ""),
            "zqf_level": ext["overview"].get("zqf_level", ""),
            "unit_titles": units,
        }

    # Process NEW_LOCAL occupations
    new_local = [o for o in occ_data if o["decision"] == "NEW_LOCAL"]
    print(f"NEW_LOCAL occupations to finalize: {len(new_local)}")

    results = []
    for i, occ in enumerate(new_local):
        title = occ["nos_title"]
        ctx = nos_context.get(title, {})

        print(f"[{i+1}/{len(new_local)}] {title}")

        user_prompt = USER_PROMPT_TEMPLATE.format(
            title=title,
            sector=ctx.get("sector", occ.get("nos_sector", "")),
            description=ctx.get("description", occ.get("nos_description", "")),
            purpose=ctx.get("purpose", occ.get("nos_purpose", "")),
            unit_titles=", ".join(ctx.get("unit_titles", [])[:8]),
            zqf_level=ctx.get("zqf_level", occ.get("zqf_level", "")),
            reason=occ.get("reason", ""),
        )

        raw = call_llm(SYSTEM_PROMPT, user_prompt)
        parsed = parse_response(raw)

        result = {
            "nos_title": title,
            "nos_sector": ctx.get("sector", occ.get("nos_sector", "")),
            "zqf_level": ctx.get("zqf_level", ""),
            "preferred_label": parsed.get("preferred_label", title.lower()),
            "description": parsed.get("description", ""),
            "alt_labels": parsed.get("alt_labels", []),
            "isco_unit_group_code": "",
            "nos_description": ctx.get("description", ""),
            "nos_purpose": ctx.get("purpose", ""),
            "reason_new_local": occ.get("reason", ""),
        }
        results.append(result)

        print(f"  Label: {result['preferred_label']}")
        print(f"  Alt labels: {result['alt_labels'][:4]}")
        print(f"  Description: {result['description'][:80]}...")
        print()

        time.sleep(1)

    # Summary
    print(f"\n{'='*70}")
    print("NEW OCCUPATION FINALIZATION RESULTS")
    print(f"{'='*70}")
    print(f"Total: {len(results)}")
    print(f"With descriptions: {sum(1 for r in results if r['description'])}")
    print(f"With alt labels: {sum(1 for r in results if r['alt_labels'])}")
    total_alt = sum(len(r["alt_labels"]) for r in results)
    print(f"Total alt labels generated: {total_alt}")

    # Save JSON
    json_path = OUTPUT_DIR / "new_occupations_finalized.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {json_path.name}")

    # Save Excel with empty ISCO column for human review
    excel_path = OUTPUT_DIR / "new_occupations_finalized.xlsx"
    rows = [{
        "nos_title": r["nos_title"],
        "preferred_label": r["preferred_label"],
        "sector": r["nos_sector"],
        "zqf_level": r["zqf_level"],
        "isco_unit_group_code": "",
        "description": r["description"],
        "alt_labels": "\n".join(r["alt_labels"]),
        "num_alt_labels": len(r["alt_labels"]),
        "reason_new_local": r["reason_new_local"],
        "nos_description": r["nos_description"],
    } for r in results]

    df = pd.DataFrame(rows)
    df.to_excel(excel_path, sheet_name="New Occupations", index=False)
    print(f"Wrote {excel_path.name}")
    print(f"\nNext: Fill in isco_unit_group_code column in the Excel, then run:")
    print(f"  python 03b_finalize_new_occupations.py --apply-codes")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    parser = argparse.ArgumentParser()
    parser.add_argument("--apply-codes", action="store_true",
                        help="Read ISCO codes from reviewed Excel and update JSON")
    args = parser.parse_args()

    if args.apply_codes:
        apply_isco_codes()
    else:
        run_generate()


if __name__ == "__main__":
    main()
