"""
Generate KeSCO Embeddings using Gemini gemini-embedding-001

Creates embeddings for all KeSCO occupational titles using Google's Gemini embedding model.
These will be used for semantic matching against ESCO English embeddings.

Input: data/KeSCO_occupations_with_context.xlsx
Output: data/kesco_embeddings.json

Usage:
    python scripts/generate_kesco_embeddings_gemini.py
"""

import pandas as pd
import json
import os
import time
from pathlib import Path
from tqdm import tqdm
import google.generativeai as genai
from dotenv import load_dotenv

# Paths
BASE_PATH = Path("C:/Users/Afsana/Dropbox/Tabiya/Taxonomy/TabiyaESCO_Localization")
load_dotenv(BASE_PATH / '.env')

KESCO_FILE = BASE_PATH / 'countries' / 'kenya_kesco' / 'data' / 'KeSCO_occupations_with_context.xlsx'
OUTPUT_FILE = BASE_PATH / 'countries' / 'kenya_kesco' / 'data' / 'kesco_embeddings.json'

# Model configuration
MODEL_NAME = 'models/gemini-embedding-001'
BATCH_SIZE = 100
TASK_TYPE = 'SEMANTIC_SIMILARITY'
OUTPUT_DIMENSIONALITY = 768


def configure_gemini():
    """Configure Gemini API."""
    api_key = os.environ.get('GOOGLE_API_KEY') or os.environ.get('GEMINI_API_KEY')
    if not api_key:
        raise ValueError("GOOGLE_API_KEY or GEMINI_API_KEY environment variable not set.")
    genai.configure(api_key=api_key)
    print(f"  Gemini API configured")


def load_kesco() -> pd.DataFrame:
    """Load KeSCO occupations with context."""
    print(f"\n[1/3] Loading KeSCO occupations from {KESCO_FILE}...")

    if not KESCO_FILE.exists():
        raise FileNotFoundError(f"KeSCO file not found: {KESCO_FILE}")

    df = pd.read_excel(KESCO_FILE)
    print(f"  Loaded {len(df)} KeSCO occupations")
    print(f"  Columns: {list(df.columns)}")

    return df


def create_embedding_items(df: pd.DataFrame) -> list:
    """Create embedding items for each KeSCO occupation."""
    print("\n[2/3] Creating embedding items...")

    embedding_items = []

    for _, row in tqdm(df.iterrows(), total=len(df), desc="  Processing"):
        kesco_code = str(row['kesco_code'])
        title = str(row['occupational_title']).strip()

        # Build context string for reference (not embedded, just stored)
        context_parts = []
        if pd.notna(row.get('unit_group_label')):
            context_parts.append(str(row['unit_group_label']))
        if pd.notna(row.get('minor_group_label')):
            context_parts.append(str(row['minor_group_label']))

        context = ' > '.join(context_parts) if context_parts else ''

        # Extract ISCO code from KeSCO code (first 4 digits)
        isco_code = kesco_code.split('-')[0] if '-' in kesco_code else kesco_code[:4]

        embedding_items.append({
            'kesco_code': kesco_code,
            'title': title,
            'isco_code': isco_code,
            'unit_group_code': str(row.get('unit_group_code', '')),
            'unit_group_label': str(row.get('unit_group_label', '')),
            'context': context,
            'embedding_text': title  # Just the title for embedding
        })

    print(f"  Created {len(embedding_items)} embedding items")
    return embedding_items


def generate_gemini_embeddings(embedding_items: list) -> list:
    """Generate embeddings using Gemini."""
    print(f"\n[3/3] Generating embeddings with Gemini {MODEL_NAME}...")
    print(f"  Total items: {len(embedding_items)}")
    print(f"  Batch size: {BATCH_SIZE}")

    texts = [item['embedding_text'] for item in embedding_items]
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
                    wait_time = 45 * (attempt + 1)
                    print(f"\n  Rate limit at batch {i//BATCH_SIZE}, waiting {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    print(f"\n  Error at batch {i//BATCH_SIZE}: {e}")
                    time.sleep(5)

                if attempt == max_retries - 1:
                    raise

        time.sleep(1.5)  # Rate limit delay

    print(f"  Generated {len(all_embeddings)} embeddings")
    print(f"  Dimensions: {len(all_embeddings[0])}")

    # Add embeddings to items
    for i, item in enumerate(embedding_items):
        item['embedding'] = all_embeddings[i]
        # Remove embedding_text from output (not needed after embedding)
        del item['embedding_text']

    return embedding_items


def save_embeddings(embedding_items: list) -> None:
    """Save embeddings to JSON file."""
    print(f"\nSaving to {OUTPUT_FILE}...")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    data = {
        'metadata': {
            'model': MODEL_NAME,
            'language': 'English',
            'source': 'KeSCO (Kenya Standard Classification of Occupations)',
            'source_file': str(KESCO_FILE),
            'num_occupations': len(embedding_items),
            'embedding_dim': len(embedding_items[0]['embedding']),
            'task_type': TASK_TYPE,
            'date_generated': pd.Timestamp.now().isoformat()
        },
        'occupations': embedding_items
    }

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    file_size_mb = OUTPUT_FILE.stat().st_size / (1024 * 1024)
    print(f"  Saved {len(embedding_items)} embeddings")
    print(f"  File size: {file_size_mb:.1f} MB")


def main():
    print("=" * 70)
    print("GENERATE KESCO EMBEDDINGS - GEMINI")
    print("=" * 70)

    try:
        configure_gemini()
        df = load_kesco()
        embedding_items = create_embedding_items(df)
        embedding_items = generate_gemini_embeddings(embedding_items)
        save_embeddings(embedding_items)

        print("\n" + "=" * 70)
        print("KESCO EMBEDDINGS COMPLETE")
        print("=" * 70)
        print(f"Occupations: {len(embedding_items)}")
        print(f"Embedding dimensions: {len(embedding_items[0]['embedding'])}")
        print(f"Output: {OUTPUT_FILE}")
        print("=" * 70)

    except Exception as e:
        print(f"\nERROR: {str(e)}")
        raise


if __name__ == '__main__':
    main()
