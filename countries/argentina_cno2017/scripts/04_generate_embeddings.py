"""
Generate Spanish CNO Embeddings using Gemini gemini-embedding-001

Uses Google's latest Gemini embedding model (100+ languages, top MTEB scores).
Creates embeddings for CNO occupation titles only (no unit context).

Input: data/cno2017_complete.xlsx
Output: data/cno2017_embeddings.json

Requirements:
    pip install google-generativeai pandas tqdm openpyxl

Usage:
    python scripts/2_embeddings/generate_cno_embeddings_gemini.py
"""

import pandas as pd
import json
import os
import time
from pathlib import Path
from tqdm import tqdm
import google.generativeai as genai
from dotenv import load_dotenv

# Load .env file from project root
load_dotenv(Path(__file__).parent.parent.parent / '.env')

# Paths
BASE_DIR = Path(__file__).parent.parent
INPUT_FILE = BASE_DIR / 'data' / 'cno2017_complete.xlsx'
OUTPUT_FILE = BASE_DIR / 'data' / 'cno2017_embeddings.json'

# Model configuration
MODEL_NAME = 'models/gemini-embedding-001'
BATCH_SIZE = 100
TASK_TYPE = 'SEMANTIC_SIMILARITY'
OUTPUT_DIMENSIONALITY = 768  # Using 768 for compatibility (model supports 768, 1536, 3072)


def configure_gemini():
    """Configure Gemini API."""
    api_key = os.environ.get('GOOGLE_API_KEY') or os.environ.get('GEMINI_API_KEY')
    if not api_key:
        raise ValueError(
            "GOOGLE_API_KEY or GEMINI_API_KEY environment variable not set.\n"
            "Set it with: set GOOGLE_API_KEY=your_key_here"
        )
    genai.configure(api_key=api_key)
    print(f"  Gemini API configured")


def load_cno_data() -> pd.DataFrame:
    """Load CNO occupations from Excel file."""
    print(f"\n[1/3] Loading CNO occupations from {INPUT_FILE}...")

    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"CNO file not found: {INPUT_FILE}")

    df = pd.read_excel(INPUT_FILE)
    print(f"  Loaded {len(df)} CNO occupations")

    required_cols = ['occupation_code', 'occupation_es']
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    return df


def generate_gemini_embeddings(df: pd.DataFrame) -> list:
    """Generate embeddings using Gemini text-embedding-004."""
    print(f"\n[2/3] Generating embeddings with Gemini {MODEL_NAME}...")
    print(f"  Total occupations: {len(df)}")
    print(f"  Batch size: {BATCH_SIZE}")
    print(f"  Task type: {TASK_TYPE}")

    # Extract texts - occupation title only (no unit context)
    texts = []
    for _, row in df.iterrows():
        text = str(row['occupation_es']) if pd.notna(row['occupation_es']) else 'Sin título'
        texts.append(text)

    all_embeddings = []
    num_batches = (len(texts) + BATCH_SIZE - 1) // BATCH_SIZE

    for i in tqdm(range(0, len(texts), BATCH_SIZE), total=num_batches, desc="  Embedding"):
        batch_texts = texts[i:i + BATCH_SIZE]

        max_retries = 5
        for attempt in range(max_retries):
            try:
                result = genai.embed_content(
                    model=MODEL_NAME,
                    content=batch_texts,
                    task_type=TASK_TYPE,
                    output_dimensionality=OUTPUT_DIMENSIONALITY
                )
                all_embeddings.extend(result['embedding'])
                break
            except Exception as e:
                if '429' in str(e) or 'quota' in str(e).lower():
                    wait_time = 45 * (attempt + 1)  # 45, 90, 135, 180, 225 seconds
                    print(f"\n  Rate limit at batch {i//BATCH_SIZE}, waiting {wait_time}s (attempt {attempt+1}/{max_retries})...")
                    time.sleep(wait_time)
                else:
                    print(f"\n  Error at batch {i//BATCH_SIZE}: {e}")
                    time.sleep(5)

                if attempt == max_retries - 1:
                    raise

        # Rate limit: ~50 batches per minute (100 items each = 5000/min, under 3000 req limit)
        time.sleep(1.5)

    print(f"  Generated {len(all_embeddings)} embeddings")
    print(f"  Dimensions: {len(all_embeddings[0])}")

    return all_embeddings


def save_embeddings(df: pd.DataFrame, embeddings: list) -> None:
    """Save embeddings to JSON file."""
    print(f"\n[3/3] Saving to {OUTPUT_FILE}...")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    data = {
        'metadata': {
            'model': MODEL_NAME,
            'language': 'Spanish',
            'approach': 'Gemini Embeddings - Occupation Title Only',
            'source_file': str(INPUT_FILE),
            'num_occupations': len(df),
            'embedding_dim': len(embeddings[0]),
            'includes_unit_context': False,
            'task_type': TASK_TYPE,
            'date_generated': pd.Timestamp.now().isoformat()
        },
        'occupations': []
    }

    for idx, row in df.iterrows():
        data['occupations'].append({
            'occupation_code': row['occupation_code'],
            'occupation_es': row['occupation_es'],
            'occupation_en': row.get('occupation_en', None),
            'unit_code': row.get('unit_code', None),
            'subgroup_code': row.get('subgroup_code', None),
            'subgroup_title_es': row.get('subgroup_title_es', None),
            'subgroup_title_en': row.get('subgroup_title_en', None),
            'embedding': embeddings[idx]
        })

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    file_size_mb = OUTPUT_FILE.stat().st_size / (1024 * 1024)
    print(f"  Saved {len(data['occupations'])} embeddings")
    print(f"  File size: {file_size_mb:.1f} MB")


def main():
    """Main execution"""
    print("=" * 80)
    print("GENERATE SPANISH CNO EMBEDDINGS - GEMINI-EMBEDDING-001")
    print("=" * 80)

    try:
        configure_gemini()
        df = load_cno_data()
        embeddings = generate_gemini_embeddings(df)
        save_embeddings(df, embeddings)

        print("\n" + "=" * 80)
        print("GEMINI CNO EMBEDDINGS COMPLETE")
        print("=" * 80)
        print(f"Total occupations: {len(df)}")
        print(f"Embedding dimensions: {len(embeddings[0])}")
        print(f"Output: {OUTPUT_FILE}")
        print("\nNext: Run matching with Gemini embeddings")
        print("  python scripts/approaches/approach4_gemini_matching.py")
        print("=" * 80)

    except Exception as e:
        print(f"\nERROR: {str(e)}")
        raise


if __name__ == '__main__':
    main()
