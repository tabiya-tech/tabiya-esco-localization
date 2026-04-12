"""
LLM validation of Zambia NOS occupation -> ESCO matches.

Reads the embedding match results from Step 2 and uses Gemini to validate
each match, selecting the best candidate or flagging as NEW_LOCAL.

Prerequisites:
  - outputs/occupation_matches_embedding.json (from 02_match_occupations.py)
  - GEMINI_API_KEY in .env

Output:
  - outputs/occupation_matches_validated.json
  - outputs/occupation_matches_validated.csv
"""

import json
import sys
import io
import os
import time
import csv
import re
from pathlib import Path
import google.generativeai as genai
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

BASE_PATH = Path(__file__).parent.parent.parent.parent
load_dotenv(BASE_PATH / ".env")

INPUT_FILE = Path(__file__).parent.parent / "outputs" / "occupation_matches_embedding.json"
OUTPUT_DIR = Path(__file__).parent.parent / "outputs"
CHECKPOINT_FILE = OUTPUT_DIR / "occupation_validation_checkpoint.json"

MODEL_NAME = "models/gemini-2.0-flash"
MAX_RETRIES = 5
CHECKPOINT_FREQUENCY = 10


SYSTEM_PROMPT = """You are an expert at matching occupational classifications for the Zambian labor market.

You are given a Zambia NOS (National Occupational Standard) occupation and a list of candidate ESCO (European Skills, Competences, Qualifications and Occupations) matches ranked by semantic similarity.

Your task is to select the BEST matching ESCO occupation, or indicate that this NOS occupation has no suitable ESCO equivalent and should be created as a new local occupation.

A match is GOOD if:
1. The occupations describe fundamentally the same work/role
2. The NOS occupation is a local or contextualised version of the ESCO occupation (e.g., same core function, possibly with Zambia-specific scope)
3. A Zambian worker in the NOS role would recognise the ESCO description as describing their job

A match is BAD if:
1. The occupations describe different types of work
2. The similarity is superficial (similar words but different roles)
3. The NOS occupation covers a significantly different scope than the ESCO candidate

Reply with ONLY a JSON object (no markdown, no explanation):
{"choice": <number 1-5>, "confidence": "high"|"medium"|"low"}
OR
{"choice": "NEW", "reason": "<brief reason why no ESCO match fits>"}"""


def build_user_prompt(result: dict) -> str:
    """Build the user prompt for a single NOS occupation."""
    nos_title = result["nos_title"]
    nos_sector = result.get("nos_sector", "")
    nos_description = result.get("nos_description", "")
    nos_purpose = result.get("nos_purpose", "")

    # Get unit titles from the original extraction if available
    unit_titles = result.get("unit_titles", [])
    unit_text = ", ".join(t for t in unit_titles if t) if unit_titles else "N/A"

    # Build candidates text
    candidates_text = ""
    for c in result["candidates"]:
        desc = c.get("esco_description", "")
        # Truncate long descriptions
        if len(desc) > 300:
            desc = desc[:297] + "..."
        candidates_text += (
            f"{c['rank']}. {c['esco_label']} ({c['similarity']}%)\n"
            f"   Description: {desc}\n\n"
        )

    prompt = f"""Zambia NOS Occupation:
- Title: {nos_title}
- Sector: {nos_sector}
- Description: {nos_description}
- Purpose: {nos_purpose}
- Key functions: {unit_text}

Candidate ESCO Occupations:
{candidates_text}
Which candidate is the best match for this Zambia NOS occupation?"""

    return prompt


def parse_llm_response(text: str) -> dict:
    """Parse the LLM JSON response."""
    text = text.strip()
    # Remove markdown code blocks if present
    text = re.sub(r"^```json?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    try:
        parsed = json.loads(text)
        choice = parsed.get("choice")
        if choice == "NEW":
            return {
                "decision": "NEW_LOCAL",
                "reason": parsed.get("reason", ""),
                "confidence": "N/A",
            }
        elif isinstance(choice, int) and 1 <= choice <= 5:
            return {
                "decision": "MATCH",
                "chosen_rank": choice,
                "confidence": parsed.get("confidence", "medium"),
            }
        else:
            return {"decision": "PARSE_ERROR", "raw": text}
    except json.JSONDecodeError:
        # Try to extract choice from text
        if "NEW" in text.upper():
            return {"decision": "NEW_LOCAL", "reason": text, "confidence": "N/A"}
        number_match = re.search(r'"choice"\s*:\s*(\d)', text)
        if number_match:
            return {
                "decision": "MATCH",
                "chosen_rank": int(number_match.group(1)),
                "confidence": "medium",
            }
        return {"decision": "PARSE_ERROR", "raw": text}


def call_llm(system_prompt: str, user_prompt: str) -> str:
    """Call Gemini with retries."""
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


def load_checkpoint() -> dict:
    """Load checkpoint if it exists."""
    if CHECKPOINT_FILE.exists():
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_checkpoint(validated: dict) -> None:
    """Save checkpoint."""
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(validated, f, indent=2, ensure_ascii=False)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

    # Load embedding results
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        results = json.load(f)
    print(f"Loaded {len(results)} occupation matches for validation")

    # Load checkpoint
    checkpoint = load_checkpoint()
    print(f"Checkpoint: {len(checkpoint)} already validated")

    # Validate each
    validated_results = []
    for i, result in enumerate(results):
        nos_title = result["nos_title"]

        if nos_title in checkpoint:
            # Use cached result
            validated_results.append(checkpoint[nos_title])
            continue

        print(f"[{i+1}/{len(results)}] {nos_title}")

        user_prompt = build_user_prompt(result)
        raw_response = call_llm(SYSTEM_PROMPT, user_prompt)
        parsed = parse_llm_response(raw_response)

        # Build validated result
        validated = {
            "nos_title": nos_title,
            "nos_sector": result.get("nos_sector", ""),
            "nos_code": result.get("nos_code", ""),
            "nos_description": result.get("nos_description", ""),
            "nos_purpose": result.get("nos_purpose", ""),
            "zqf_level": result.get("zqf_level", ""),
            "decision": parsed["decision"],
            "llm_confidence": parsed.get("confidence", ""),
            "llm_raw": raw_response,
        }

        if parsed["decision"] == "MATCH":
            chosen_rank = parsed["chosen_rank"]
            if chosen_rank <= len(result["candidates"]):
                chosen = result["candidates"][chosen_rank - 1]
                validated["esco_code"] = chosen["esco_code"]
                validated["esco_label"] = chosen["esco_label"]
                validated["esco_description"] = chosen["esco_description"]
                validated["similarity"] = chosen["similarity"]
                validated["chosen_rank"] = chosen_rank
                validated["embedding_top_label"] = result["candidates"][0]["esco_label"]
                validated["embedding_top_sim"] = result["candidates"][0]["similarity"]
                changed = " (CHANGED from embedding top)" if chosen_rank > 1 else ""
                print(f"  -> MATCH: {chosen['esco_label']} ({chosen['similarity']}%) "
                      f"[confidence: {parsed['confidence']}]{changed}")
            else:
                validated["decision"] = "PARSE_ERROR"
                validated["error"] = f"chosen_rank {chosen_rank} out of range"
                print(f"  -> PARSE_ERROR: rank {chosen_rank} out of range")

        elif parsed["decision"] == "NEW_LOCAL":
            validated["reason"] = parsed.get("reason", "")
            validated["embedding_top_label"] = result["candidates"][0]["esco_label"]
            validated["embedding_top_sim"] = result["candidates"][0]["similarity"]
            print(f"  -> NEW_LOCAL: {parsed.get('reason', '')}")

        else:
            validated["error"] = parsed.get("raw", "")
            print(f"  -> PARSE_ERROR: {parsed.get('raw', '')[:80]}")

        validated_results.append(validated)
        checkpoint[nos_title] = validated

        # Checkpoint save
        if (i + 1) % CHECKPOINT_FREQUENCY == 0:
            save_checkpoint(checkpoint)
            print(f"  [checkpoint saved: {len(checkpoint)} items]")

        # Rate limiting
        time.sleep(1)

    # Final checkpoint save
    save_checkpoint(checkpoint)

    # Summary
    print(f"\n{'='*70}")
    print("LLM VALIDATION RESULTS")
    print(f"{'='*70}")

    matched = [v for v in validated_results if v["decision"] == "MATCH"]
    new_local = [v for v in validated_results if v["decision"] == "NEW_LOCAL"]
    errors = [v for v in validated_results if v["decision"] == "PARSE_ERROR"]

    print(f"Total: {len(validated_results)}")
    print(f"  MATCH: {len(matched)}")
    print(f"  NEW_LOCAL: {len(new_local)}")
    print(f"  PARSE_ERROR: {len(errors)}")

    # Confidence breakdown for matches
    if matched:
        high = sum(1 for m in matched if m.get("llm_confidence") == "high")
        med = sum(1 for m in matched if m.get("llm_confidence") == "medium")
        low = sum(1 for m in matched if m.get("llm_confidence") == "low")
        print(f"\n  Match confidence: {high} high, {med} medium, {low} low")

    # How many did the LLM change from the embedding top pick?
    changed = sum(1 for m in matched if m.get("chosen_rank", 1) > 1)
    print(f"  LLM changed from embedding top pick: {changed}")

    if new_local:
        print(f"\nNEW_LOCAL occupations:")
        for v in new_local:
            print(f"  {v['nos_title']}: {v.get('reason', '')}")

    if errors:
        print(f"\nParse errors:")
        for v in errors:
            print(f"  {v['nos_title']}: {v.get('error', '')[:80]}")

    # Save outputs
    json_path = OUTPUT_DIR / "occupation_matches_validated.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(validated_results, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {json_path.name}")

    csv_path = OUTPUT_DIR / "occupation_matches_validated.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "nos_title", "nos_sector", "nos_code", "zqf_level",
            "decision", "llm_confidence",
            "esco_code", "esco_label", "similarity", "chosen_rank",
            "embedding_top_label", "embedding_top_sim",
            "reason", "nos_description",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for v in validated_results:
            writer.writerow(v)
    print(f"Wrote {csv_path.name}")


if __name__ == "__main__":
    main()
