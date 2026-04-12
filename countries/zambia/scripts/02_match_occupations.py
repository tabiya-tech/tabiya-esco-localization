"""
Match Zambia NOS occupations to ESCO occupations.

Step 1: Embedding-based semantic matching using Gemini embeddings
  - Generate embeddings for NOS occupation titles + descriptions
  - Compare against pre-computed ESCO occupation embeddings
  - Return top-5 candidates per NOS occupation with similarity scores

Step 2: LLM validation (separate step, run after reviewing Step 1 results)

Prerequisites:
  - NOS extractions: outputs/nos_extractions.json (from 01_extract_nos_skills.py)
  - ESCO embeddings: shared_data/esco_embeddings_en_gemini.json
  - ESCO occupations: shared_data/esco_taxonomy/occupations.csv
  - GEMINI_API_KEY in .env

Output:
  - outputs/occupation_matches_embedding.json
  - outputs/occupation_matches_embedding.csv
"""

import json
import sys
import io
import os
import time
import csv
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

NOS_EXTRACTIONS = Path(__file__).parent.parent / "outputs" / "nos_extractions.json"
ESCO_EMBEDDINGS = BASE_PATH / "shared_data" / "esco_embeddings_en_gemini.json"
ESCO_OCCS_CSV = BASE_PATH / "shared_data" / "esco_taxonomy" / "occupations.csv"
OUTPUT_DIR = Path(__file__).parent.parent / "outputs"

EMBEDDING_MODEL = "models/gemini-embedding-001"
EMBEDDING_DIM = 768
TOP_K = 5
BATCH_SIZE = 50


def load_nos_occupations() -> list[dict]:
    """Load NOS occupations from extraction JSON, deduplicated."""
    with open(NOS_EXTRACTIONS, "r", encoding="utf-8") as f:
        extractions = json.load(f)

    occupations = []
    seen_titles = set()
    for ext in extractions:
        title = ext["overview"].get("job_title", ext["occupation_from_filename"])
        if title.lower() in seen_titles:
            continue
        seen_titles.add(title.lower())

        description = ext["overview"].get("job_description", "")
        purpose = ext["overview"].get("job_purpose", "")
        sector = ext.get("sector", "")
        nos_code = ext["overview"].get("nos_code", "")
        zqf_level = ext["overview"].get("zqf_level", "")

        # Build context string for richer matching
        context_parts = [title]
        if description:
            context_parts.append(description)
        if purpose:
            context_parts.append(purpose)

        occupations.append({
            "title": title,
            "description": description,
            "purpose": purpose,
            "sector": sector,
            "nos_code": nos_code,
            "zqf_level": zqf_level,
            "embedding_text": ". ".join(context_parts),
            "unit_titles": [u.get("title", "") for u in ext.get("units", [])],
        })

    return occupations


def load_esco_embeddings() -> tuple[np.ndarray, list[dict]]:
    """Load pre-computed ESCO occupation embeddings."""
    print("Loading ESCO embeddings...")
    with open(ESCO_EMBEDDINGS, "r", encoding="utf-8") as f:
        raw = json.load(f)
    esco_data = raw["embeddings"] if isinstance(raw, dict) and "embeddings" in raw else raw

    # Use preferred labels only for cleaner matching
    preferred = [e for e in esco_data if e.get("label_type") == "preferred"]
    print(f"  {len(preferred)} preferred-label embeddings (out of {len(esco_data)} total)")

    embeddings = np.array([e["embedding"] for e in preferred], dtype=np.float32)
    metadata = [{
        "esco_code": e["esco_code"],
        "label": e["label"],
        "description": e.get("description", ""),
    } for e in preferred]

    return embeddings, metadata


def load_esco_occupations() -> dict[str, dict]:
    """Load ESCO occupations CSV into a lookup by code."""
    df = pd.read_csv(ESCO_OCCS_CSV, encoding="utf-8")
    lookup = {}
    for _, row in df.iterrows():
        code = str(row.get("CODE", ""))
        lookup[code] = {
            "code": code,
            "label": str(row.get("PREFERREDLABEL", "")),
            "description": str(row.get("DESCRIPTION", "")),
            "alt_labels": str(row.get("ALTLABELS", "")),
            "isco_group": code.split(".")[0] if "." in code else code,
        }
    return lookup


def generate_nos_embeddings(occupations: list[dict]) -> np.ndarray:
    """Generate Gemini embeddings for NOS occupation texts."""
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

    texts = [occ["embedding_text"] for occ in occupations]
    print(f"Generating embeddings for {len(texts)} NOS occupations...")

    all_embeddings = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i:i + BATCH_SIZE]
        result = genai.embed_content(
            model=EMBEDDING_MODEL,
            content=batch,
            task_type="SEMANTIC_SIMILARITY",
            output_dimensionality=EMBEDDING_DIM,
        )
        all_embeddings.extend(result["embedding"])
        print(f"  Embedded batch {i // BATCH_SIZE + 1}/{(len(texts) - 1) // BATCH_SIZE + 1}")
        if i + BATCH_SIZE < len(texts):
            time.sleep(1.5)

    return np.array(all_embeddings, dtype=np.float32)


def find_top_matches(
    nos_embeddings: np.ndarray,
    esco_embeddings: np.ndarray,
    esco_metadata: list[dict],
    esco_lookup: dict[str, dict],
    top_k: int = TOP_K,
) -> list[list[dict]]:
    """Find top-K ESCO matches for each NOS occupation."""
    print(f"Computing cosine similarity ({nos_embeddings.shape[0]} x {esco_embeddings.shape[0]})...")
    sim_matrix = cosine_similarity(nos_embeddings, esco_embeddings)

    all_matches = []
    for i in range(sim_matrix.shape[0]):
        scores = sim_matrix[i]
        top_indices = np.argsort(scores)[::-1][:top_k]

        matches = []
        for idx in top_indices:
            meta = esco_metadata[idx]
            code = meta["esco_code"]
            full_info = esco_lookup.get(code, {})
            matches.append({
                "rank": len(matches) + 1,
                "esco_code": code,
                "esco_label": meta["label"],
                "esco_description": full_info.get("description", meta.get("description", "")),
                "esco_isco_group": full_info.get("isco_group", ""),
                "similarity": round(float(scores[idx]) * 100, 1),
            })
        all_matches.append(matches)

    return all_matches


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load data
    nos_occupations = load_nos_occupations()
    print(f"Loaded {len(nos_occupations)} unique NOS occupations")

    esco_embeddings, esco_metadata = load_esco_embeddings()
    esco_lookup = load_esco_occupations()

    # Generate NOS embeddings
    nos_embeddings = generate_nos_embeddings(nos_occupations)

    # Find matches
    all_matches = find_top_matches(nos_embeddings, esco_embeddings, esco_metadata, esco_lookup)

    # Build results
    results = []
    for i, occ in enumerate(nos_occupations):
        matches = all_matches[i]
        top_match = matches[0] if matches else {}
        results.append({
            "nos_title": occ["title"],
            "nos_description": occ["description"],
            "nos_purpose": occ["purpose"],
            "nos_sector": occ["sector"],
            "nos_code": occ["nos_code"],
            "zqf_level": occ["zqf_level"],
            "top_match_esco_code": top_match.get("esco_code", ""),
            "top_match_esco_label": top_match.get("esco_label", ""),
            "top_match_similarity": top_match.get("similarity", 0),
            "top_match_esco_description": top_match.get("esco_description", ""),
            "candidates": matches,
        })

    # Print summary
    print(f"\n{'='*70}")
    print("OCCUPATION MATCHING RESULTS")
    print(f"{'='*70}")

    high_conf = [r for r in results if r["top_match_similarity"] >= 90]
    medium_conf = [r for r in results if 75 <= r["top_match_similarity"] < 90]
    low_conf = [r for r in results if r["top_match_similarity"] < 75]

    print(f"Total NOS occupations: {len(results)}")
    print(f"  High confidence (>=90%): {len(high_conf)}")
    print(f"  Medium confidence (75-90%): {len(medium_conf)}")
    print(f"  Low confidence (<75%): {len(low_conf)}")

    print(f"\nHigh confidence matches:")
    for r in sorted(high_conf, key=lambda x: -x["top_match_similarity"]):
        print(f"  {r['top_match_similarity']:5.1f}% | {r['nos_title']:<45} -> {r['top_match_esco_label']}")

    print(f"\nMedium confidence matches:")
    for r in sorted(medium_conf, key=lambda x: -x["top_match_similarity"]):
        print(f"  {r['top_match_similarity']:5.1f}% | {r['nos_title']:<45} -> {r['top_match_esco_label']}")

    print(f"\nLow confidence matches:")
    for r in sorted(low_conf, key=lambda x: -x["top_match_similarity"]):
        print(f"  {r['top_match_similarity']:5.1f}% | {r['nos_title']:<45} -> {r['top_match_esco_label']}")

    # Save JSON
    json_path = OUTPUT_DIR / "occupation_matches_embedding.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {json_path.name}")

    # Save CSV (flat, one row per NOS occupation with top match + all candidates)
    csv_path = OUTPUT_DIR / "occupation_matches_embedding.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "nos_title", "nos_sector", "nos_code", "zqf_level", "nos_description",
            "top_match_esco_code", "top_match_esco_label", "top_match_similarity",
            "top_match_esco_description",
            "candidate_2_label", "candidate_2_sim",
            "candidate_3_label", "candidate_3_sim",
            "candidate_4_label", "candidate_4_sim",
            "candidate_5_label", "candidate_5_sim",
        ])
        writer.writeheader()
        for r in results:
            row = {
                "nos_title": r["nos_title"],
                "nos_sector": r["nos_sector"],
                "nos_code": r["nos_code"],
                "zqf_level": r["zqf_level"],
                "nos_description": r["nos_description"],
                "top_match_esco_code": r["top_match_esco_code"],
                "top_match_esco_label": r["top_match_esco_label"],
                "top_match_similarity": r["top_match_similarity"],
                "top_match_esco_description": r["top_match_esco_description"],
            }
            for j in range(1, 4):
                if j < len(r["candidates"]):
                    c = r["candidates"][j]
                    row[f"candidate_{j+1}_label"] = c["esco_label"]
                    row[f"candidate_{j+1}_sim"] = c["similarity"]
            writer.writerow(row)
    print(f"Wrote {csv_path.name}")


if __name__ == "__main__":
    main()
