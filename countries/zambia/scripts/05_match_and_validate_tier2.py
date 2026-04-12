"""
Tier 2: Match and validate NOS Core Skills + Professional Skills against ESCO.

Combined pipeline:
  Step 1: Embedding match CS+PS phrases against ESCO skill/competence pool
  Step 2: Clean extraction artifacts
  Step 3: LLM validation (ACCEPT / CONTEXTUALIZE / NEW)

Thresholds:
  - >=98% + exact label: auto-ACCEPT (no alt label)
  - 94-98% + near-exact: auto-CONTEXTUALIZE (add as alt label)
  - <94% or different labels: LLM review

Usage:
  python 05_match_and_validate_tier2.py           # Run full pipeline
  python 05_match_and_validate_tier2.py --embed    # Embedding step only
  python 05_match_and_validate_tier2.py --validate # LLM validation only

Prerequisites:
  - outputs/nos_skill_phrases.csv (from 01_extract_nos_skills.py)
  - shared_data/esco_taxonomy/skills.csv
  - GEMINI_API_KEY in .env

Output:
  - outputs/skill_matches_tier2.json (embedding results)
  - outputs/skill_matches_tier2_validated.json
  - outputs/skill_matches_tier2_validated.xlsx
  - shared_data/esco_skill_embeddings_en_gemini.json (cached, reusable)
"""

import json
import sys
import io
import os
import time
import csv
import re
import argparse
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.metrics.pairwise import cosine_similarity
import google.generativeai as genai
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

BASE_PATH = Path(__file__).parent.parent.parent.parent
load_dotenv(BASE_PATH / ".env")

NOS_PHRASES = Path(__file__).parent.parent / "outputs" / "nos_skill_phrases.csv"
ESCO_SKILLS_CSV = BASE_PATH / "shared_data" / "esco_taxonomy" / "skills.csv"
ESCO_SKILL_EMBEDDINGS = BASE_PATH / "shared_data" / "esco_skill_embeddings_en_gemini.json"
OUTPUT_DIR = Path(__file__).parent.parent / "outputs"
EMBEDDING_OUTPUT = OUTPUT_DIR / "skill_matches_tier2.json"
VALIDATED_OUTPUT = OUTPUT_DIR / "skill_matches_tier2_validated.json"
CHECKPOINT_FILE = OUTPUT_DIR / "skill_tier2_validation_checkpoint.json"

# Embedding config
EMBEDDING_MODEL = "models/gemini-embedding-001"
EMBEDDING_DIM = 768
EMBED_BATCH_SIZE = 100
TOP_K = 5
RATE_LIMIT_DELAY = 1.5

# LLM config
LLM_MODEL = "models/gemini-2.0-flash"
MAX_RETRIES = 5
LLM_CHECKPOINT_FREQUENCY = 50
AUTO_ACCEPT_EXACT_THRESHOLD = 98.0
AUTO_ACCEPT_ALT_THRESHOLD = 94.0

# Artifact patterns to clean from NOS text
ARTIFACT_PATTERNS = [
    r"\d+\s*\|\s*P\s*a?\s*g\s*e",
    r"NOS[\s.]*\w{1,5}[\s.]*\d+",
    r"First Edition|Second Edition",
    r"\|\s*Page",
    r"Oral Communication \(Listening.*$",
    r"Critical Thinking\s*$",
    r"Reading Skills\s*$",
    r"Writing Skills\s*$",
]

LLM_SYSTEM_PROMPT = """You are an expert at mapping skills and competences to the ESCO taxonomy.

You are given a skill/competence phrase extracted from a Zambia National Occupational Standard (NOS) and its best ESCO match.

Your task is to decide:

1. ACCEPT - The NOS phrase and ESCO label describe the exact same skill with essentially the same wording. No change needed.

2. CONTEXTUALIZE - The ESCO match is the correct skill, but the NOS phrase adds value as an alternative label. You must:
   - Rephrase the NOS text into proper ESCO-style skill labels (verb phrases, infinitive form without "to")
   - If the NOS phrase contains MULTIPLE distinct skills, SPLIT them into separate labels
   - Each label should be concise (2-8 words)

3. NEW - No ESCO skill covers this competence. Provide a properly phrased ESCO-style label.

ESCO skill label rules:
- Always verb phrases in infinitive form (no "to")
- Pattern: verb + object [+ qualifier]
- Lowercase unless proper nouns
- Concise: 2-8 words typical

Reply with ONLY a JSON object (no markdown, no explanation):
{"decision": "ACCEPT"}
or
{"decision": "CONTEXTUALIZE", "esco_labels": ["label1", "label2", ...]}
or
{"decision": "NEW", "esco_labels": ["label1"]}"""

LLM_USER_PROMPT = """NOS skill phrase: "{nos_text}"
NOS category: {nos_category}
Used by occupations: {occupations}

Best ESCO match: "{esco_label}" ({similarity}%)
ESCO description: {esco_description}

What is your decision?"""


# =========================================================================
# SHARED UTILITIES
# =========================================================================

def clean_nos_text(text: str) -> str:
    """Clean NOS text of extraction artifacts."""
    for pat in ARTIFACT_PATTERNS:
        text = re.sub(pat, "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip().rstrip(".,;:")
    return text


def is_artifact(text: str) -> bool:
    """Check if text is primarily an extraction artifact."""
    return bool(re.search(
        r"\d+\s*\|\s*P\s*a?\s*g\s*e|NOS\.\w+\.\d+|First Edition|Page NOS|\| Pa ge",
        text
    ))


def generate_embeddings_batched(texts: list[str]) -> np.ndarray:
    """Generate Gemini embeddings in batches with rate limiting."""
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    all_embeddings = []
    total_batches = (len(texts) - 1) // EMBED_BATCH_SIZE + 1

    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i:i + EMBED_BATCH_SIZE]
        batch_num = i // EMBED_BATCH_SIZE + 1

        for attempt in range(5):
            try:
                result = genai.embed_content(
                    model=EMBEDDING_MODEL,
                    content=batch,
                    task_type="SEMANTIC_SIMILARITY",
                    output_dimensionality=EMBEDDING_DIM,
                )
                all_embeddings.extend(result["embedding"])
                print(f"  Batch {batch_num}/{total_batches} ({len(all_embeddings)}/{len(texts)})")
                break
            except Exception as e:
                if "429" in str(e) or "quota" in str(e).lower():
                    wait = 45 * (attempt + 1)
                    print(f"  Rate limited, waiting {wait}s...")
                    time.sleep(wait)
                else:
                    print(f"  Error (attempt {attempt+1}): {e}")
                    time.sleep(5)

        if i + EMBED_BATCH_SIZE < len(texts):
            time.sleep(RATE_LIMIT_DELAY)

    return np.array(all_embeddings, dtype=np.float32)


def call_llm(system_prompt: str, user_prompt: str) -> str:
    """Call Gemini LLM with retries."""
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


def parse_llm_response(text: str) -> dict:
    """Parse LLM JSON response."""
    text = text.strip()
    text = re.sub(r"^```json?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
        decision = parsed.get("decision", "").upper()
        if decision == "ACCEPT":
            return {"decision": "ACCEPT"}
        elif decision in ("CONTEXTUALIZE", "CONTEXTUALISE"):
            labels = parsed.get("esco_labels", [])
            return {"decision": "CONTEXTUALIZE", "esco_labels": labels if isinstance(labels, list) else [labels]}
        elif decision == "NEW":
            labels = parsed.get("esco_labels", [])
            return {"decision": "NEW", "esco_labels": labels if isinstance(labels, list) else [labels]}
        else:
            return {"decision": "PARSE_ERROR", "raw": text}
    except json.JSONDecodeError:
        return {"decision": "PARSE_ERROR", "raw": text}


# =========================================================================
# STEP 1: EMBEDDING MATCH
# =========================================================================

def load_or_generate_esco_skill_embeddings() -> tuple[np.ndarray, list[dict]]:
    """Load cached ESCO skill embeddings or generate them."""
    if ESCO_SKILL_EMBEDDINGS.exists():
        print("Loading cached ESCO skill embeddings...")
        with open(ESCO_SKILL_EMBEDDINGS, "r", encoding="utf-8") as f:
            data = json.load(f)
        embeddings = np.array([e["embedding"] for e in data["embeddings"]], dtype=np.float32)
        metadata = [{k: v for k, v in e.items() if k != "embedding"} for e in data["embeddings"]]
        print(f"  Loaded {len(metadata)} skill embeddings")
        return embeddings, metadata

    print("Generating ESCO skill embeddings (first time, will cache)...")
    df = pd.read_csv(ESCO_SKILLS_CSV, encoding="utf-8")
    skills_df = df[df["SKILLTYPE"] == "skill/competence"].copy()
    print(f"  {len(skills_df)} skill/competence concepts to embed")

    metadata = []
    texts = []
    for _, row in skills_df.iterrows():
        label = str(row.get("PREFERREDLABEL", ""))
        if not label or label == "nan":
            continue
        metadata.append({
            "id": str(row.get("ID", "")),
            "label": label,
            "reuse_level": str(row.get("REUSELEVEL", "")),
            "description": str(row.get("DESCRIPTION", ""))[:300],
        })
        texts.append(label)

    print(f"  Embedding {len(texts)} skill labels...")
    embeddings = generate_embeddings_batched(texts)

    cache_data = {
        "metadata": {
            "model": EMBEDDING_MODEL, "embedding_dim": EMBEDDING_DIM,
            "num_embeddings": len(texts), "skill_type": "skill/competence",
            "date_generated": pd.Timestamp.now().isoformat(),
        },
        "embeddings": [{**meta, "embedding": emb.tolist()} for meta, emb in zip(metadata, embeddings)],
    }
    with open(ESCO_SKILL_EMBEDDINGS, "w", encoding="utf-8") as f:
        json.dump(cache_data, f, ensure_ascii=False)
    print(f"  Cached {len(texts)} embeddings")
    return embeddings, metadata


def load_nos_cs_ps() -> list[dict]:
    """Load and deduplicate NOS CS+PS phrases with artifact cleaning."""
    with open(NOS_PHRASES, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    cs_ps = [r for r in rows if r["category"] in ("core_skills", "professional_skills")]

    unique = {}
    for r in cs_ps:
        text = clean_nos_text(r["raw_text"])
        if is_artifact(text) or not text or len(text) < 5:
            continue
        key = text.lower().strip()
        if key not in unique:
            unique[key] = {"text": text, "category": r["category"], "occupations": [], "nos_codes": []}
        occ = r["occupation"]
        if occ not in unique[key]["occupations"]:
            unique[key]["occupations"].append(occ)

    phrases = list(unique.values())
    print(f"Loaded {len(cs_ps)} CS+PS rows -> {len(phrases)} unique phrases (after cleaning)")
    return phrases


def run_embedding_match() -> list[dict]:
    """Step 1: Embedding match NOS phrases against ESCO skills."""
    print(f"\n{'='*70}")
    print("STEP 1: EMBEDDING MATCH")
    print(f"{'='*70}")

    esco_embeddings, esco_metadata = load_or_generate_esco_skill_embeddings()
    nos_phrases = load_nos_cs_ps()

    nos_texts = [p["text"] for p in nos_phrases]
    print(f"\nGenerating embeddings for {len(nos_texts)} NOS CS+PS phrases...")
    nos_embeddings = generate_embeddings_batched(nos_texts)

    print(f"\nComputing cosine similarity ({nos_embeddings.shape[0]} x {esco_embeddings.shape[0]})...")
    sim_matrix = cosine_similarity(nos_embeddings, esco_embeddings)

    results = []
    for i, phrase in enumerate(nos_phrases):
        scores = sim_matrix[i]
        top_indices = np.argsort(scores)[::-1][:TOP_K]

        candidates = []
        for idx in top_indices:
            meta = esco_metadata[idx]
            candidates.append({
                "rank": len(candidates) + 1,
                "esco_label": meta["label"],
                "esco_id": meta["id"],
                "esco_reuse_level": meta["reuse_level"],
                "esco_description": meta.get("description", ""),
                "similarity": round(float(scores[idx]) * 100, 1),
            })

        top = candidates[0] if candidates else {}
        results.append({
            "nos_text": phrase["text"],
            "nos_category": phrase["category"],
            "num_occupations": len(phrase["occupations"]),
            "occupations": ", ".join(phrase["occupations"][:5]) + ("..." if len(phrase["occupations"]) > 5 else ""),
            "top_match_label": top.get("esco_label", ""),
            "top_match_similarity": top.get("similarity", 0),
            "top_match_reuse_level": top.get("esco_reuse_level", ""),
            "top_match_description": top.get("esco_description", ""),
            "candidates": candidates,
        })

    high = len([r for r in results if r["top_match_similarity"] >= 85])
    medium = len([r for r in results if 70 <= r["top_match_similarity"] < 85])
    low = len([r for r in results if r["top_match_similarity"] < 70])
    print(f"\nEmbedding results: {len(results)} phrases")
    print(f"  High (>=85%): {high}, Medium (70-85%): {medium}, Low (<70%): {low}")

    with open(EMBEDDING_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"Wrote {EMBEDDING_OUTPUT.name}")

    return results


# =========================================================================
# STEP 2: LLM VALIDATION
# =========================================================================

def run_llm_validation(data: list[dict]) -> list[dict]:
    """Step 2: LLM validation of embedding matches."""
    print(f"\n{'='*70}")
    print("STEP 2: LLM VALIDATION")
    print(f"{'='*70}")

    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

    checkpoint = {}
    if CHECKPOINT_FILE.exists():
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            checkpoint = json.load(f)
    print(f"Checkpoint: {len(checkpoint)} already validated")

    auto_accept_exact = []
    auto_ctx = []
    needs_llm = []

    for r in data:
        nos = r["nos_text"].lower().strip()
        esco = r["top_match_label"].lower().strip()
        sim = r["top_match_similarity"]

        if sim >= AUTO_ACCEPT_EXACT_THRESHOLD and (nos == esco or nos in esco or esco in nos):
            auto_accept_exact.append(r)
        elif sim >= AUTO_ACCEPT_ALT_THRESHOLD and (nos == esco or nos in esco or esco in nos):
            auto_ctx.append(r)
        else:
            needs_llm.append(r)

    print(f"Auto-accept (>=98% exact): {len(auto_accept_exact)}")
    print(f"Auto-contextualize (94-98% near-exact): {len(auto_ctx)}")
    print(f"Needs LLM review: {len(needs_llm)}")

    validated = []

    for r in auto_accept_exact:
        validated.append({**r, "decision": "ACCEPT", "esco_labels": [], "llm_reviewed": False})

    for r in auto_ctx:
        validated.append({**r, "decision": "CONTEXTUALIZE",
                          "esco_labels": [r["nos_text"].lower().strip()], "llm_reviewed": False})

    llm_count = 0
    for r in needs_llm:
        key = r["nos_text"].lower().strip()
        if key in checkpoint:
            validated.append({**r, **checkpoint[key], "llm_reviewed": True})
            continue

        llm_count += 1
        if llm_count % 100 == 0:
            print(f"  [{llm_count}/{len(needs_llm)}] Processing...")

        user_prompt = LLM_USER_PROMPT.format(
            nos_text=r["nos_text"], nos_category=r["nos_category"],
            occupations=r["occupations"], esco_label=r["top_match_label"],
            similarity=r["top_match_similarity"],
            esco_description=r.get("top_match_description", "")[:200],
        )

        raw_response = call_llm(LLM_SYSTEM_PROMPT, user_prompt)
        parsed = parse_llm_response(raw_response)

        result = {"decision": parsed["decision"], "esco_labels": parsed.get("esco_labels", []),
                   "llm_raw": raw_response, "llm_reviewed": True}
        validated.append({**r, **result})
        checkpoint[key] = result

        if llm_count % LLM_CHECKPOINT_FREQUENCY == 0:
            with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
                json.dump(checkpoint, f, indent=2, ensure_ascii=False)
            print(f"  [checkpoint saved: {len(checkpoint)} items]")

        time.sleep(0.3)

    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(checkpoint, f, indent=2, ensure_ascii=False)

    # Summary
    accept = [v for v in validated if v["decision"] == "ACCEPT"]
    context = [v for v in validated if v["decision"] == "CONTEXTUALIZE"]
    new = [v for v in validated if v["decision"] == "NEW"]
    errors = [v for v in validated if v["decision"] == "PARSE_ERROR"]

    print(f"\nValidation results:")
    print(f"  ACCEPT: {len(accept)}")
    print(f"  CONTEXTUALIZE: {len(context)} ({sum(len(v.get('esco_labels', [])) for v in context)} alt labels)")
    print(f"  NEW: {len(new)} ({sum(len(v.get('esco_labels', [])) for v in new)} new labels)")
    print(f"  PARSE_ERROR: {len(errors)}")

    # Save
    with open(VALIDATED_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(validated, f, indent=2, ensure_ascii=False)

    # Excel
    excel_path = OUTPUT_DIR / "skill_matches_tier2_validated.xlsx"
    rows = [{
        "nos_phrase": v["nos_text"], "nos_category": v["nos_category"],
        "num_occupations": v["num_occupations"], "sample_occupations": v["occupations"],
        "esco_match": v["top_match_label"], "similarity": v["top_match_similarity"],
        "decision": v["decision"],
        "generated_labels": " | ".join(v.get("esco_labels", [])),
        "esco_description": v.get("top_match_description", ""),
    } for v in validated]

    df = pd.DataFrame(rows)
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        df.sort_values("similarity", ascending=False).to_excel(writer, sheet_name="All", index=False)
        df[df["decision"] == "ACCEPT"].to_excel(writer, sheet_name="Accept", index=False)
        df[df["decision"] == "CONTEXTUALIZE"].to_excel(writer, sheet_name="Contextualize", index=False)
        df[df["decision"] == "NEW"].to_excel(writer, sheet_name="New", index=False)

    print(f"Wrote {excel_path.name}")
    return validated


# =========================================================================
# MAIN
# =========================================================================

def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    parser = argparse.ArgumentParser()
    parser.add_argument("--embed", action="store_true", help="Run embedding step only")
    parser.add_argument("--validate", action="store_true", help="Run LLM validation only")
    args = parser.parse_args()

    if args.embed:
        run_embedding_match()
    elif args.validate:
        with open(EMBEDDING_OUTPUT, "r", encoding="utf-8") as f:
            data = json.load(f)
        run_llm_validation(data)
    else:
        data = run_embedding_match()
        run_llm_validation(data)


if __name__ == "__main__":
    main()
