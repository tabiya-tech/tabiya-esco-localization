"""
Generate O*NET Occupation Embeddings using Gemini gemini-embedding-001

Embeds O*NET occupation titles + descriptions for semantic matching
against local occupations during skill assignment.

Input: {ONET_PATH}/db_30_1/db_30_1_text/Occupation Data.txt
Output: shared_data/onet_embeddings_gemini.json

Requirements:
    pip install google-generativeai pandas tqdm python-dotenv

Usage:
    python shared_data/generate_onet_embeddings.py
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
PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / '.env')

# Paths
ONET_PATH = Path(__file__).parent / 'onet'
ONET_DB = ONET_PATH / 'db_30_1' / 'db_30_1_text'
ONET_FILE = ONET_DB / 'Occupation Data.txt'
OUTPUT_FILE = Path(__file__).parent / 'onet_embeddings_gemini.json'

# Model configuration
MODEL_NAME = 'models/gemini-embedding-001'
BATCH_SIZE = 100
TASK_TYPE = 'SEMANTIC_SIMILARITY'
OUTPUT_DIMENSIONALITY = 768


def configure_gemini() -> None:
    """Configure Gemini API."""
    api_key = os.environ.get('GOOGLE_API_KEY') or os.environ.get('GEMINI_API_KEY')
    if not api_key:
        raise ValueError(
            "GOOGLE_API_KEY or GEMINI_API_KEY environment variable not set.\n"
            "Set it with: set GOOGLE_API_KEY=your_key_here"
        )
    genai.configure(api_key=api_key)
    print(f"  Gemini API configured")


def load_onet_occupations() -> pd.DataFrame:
    """Load O*NET occupations with titles and descriptions."""
    print(f"\n[1/3] Loading O*NET occupations from {ONET_FILE}...")

    if not ONET_FILE.exists():
        raise FileNotFoundError(f"O*NET file not found: {ONET_FILE}")

    df = pd.read_csv(ONET_FILE, sep='\t')
    print(f"  Loaded {len(df)} O*NET occupations")
    print(f"  Columns: {list(df.columns)}")
    return df


def create_embedding_items(df: pd.DataFrame) -> list:
    """Create embedding items for O*NET occupations using title + description."""
    print("\n[2/3] Creating O*NET embedding items (title + description)...")

    embedding_items = []
    for _, row in df.iterrows():
        code = row['O*NET-SOC Code']
        title = str(row['Title']).strip()
        description = str(row['Description']).strip() if pd.notna(row['Description']) else ''

        # Embed title + description together for richer semantic matching
        embedding_text = f"{title}: {description}" if description else title

        embedding_items.append({
            'onet_code': code,
            'title': title,
            'description': description[:300],
            'embedding_text': embedding_text,
        })

    print(f"  Created {len(embedding_items)} O*NET embedding items")
    return embedding_items


def generate_gemini_embeddings(embedding_items: list) -> list:
    """Generate embeddings using Gemini gemini-embedding-001."""
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
                    print(f"\n  Rate limit at batch {i//BATCH_SIZE}, waiting {wait_time}s (attempt {attempt+1}/{max_retries})...")
                    time.sleep(wait_time)
                else:
                    print(f"\n  Error at batch {i//BATCH_SIZE}: {e}")
                    time.sleep(5)

                if attempt == max_retries - 1:
                    raise

        time.sleep(1.5)

    print(f"  Generated {len(all_embeddings)} embeddings")
    print(f"  Dimensions: {len(all_embeddings[0])}")

    # Add embeddings to items and remove embedding_text
    for i, item in enumerate(embedding_items):
        item['embedding'] = all_embeddings[i]
        del item['embedding_text']

    return embedding_items


def save_embeddings(embedding_items: list) -> None:
    """Save O*NET embeddings to JSON file."""
    print(f"\nSaving to {OUTPUT_FILE}...")

    data = {
        'metadata': {
            'model': MODEL_NAME,
            'source': 'O*NET 30.1 (Occupation Data.txt)',
            'source_file': str(ONET_FILE),
            'num_occupations': len(embedding_items),
            'embedding_dim': len(embedding_items[0]['embedding']),
            'format': 'title + description - Gemini gemini-embedding-001',
            'task_type': TASK_TYPE,
            'date_generated': pd.Timestamp.now().isoformat()
        },
        'occupations': embedding_items
    }

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    file_size_mb = OUTPUT_FILE.stat().st_size / (1024 * 1024)
    print(f"  Saved {len(embedding_items)} O*NET embeddings")
    print(f"  File size: {file_size_mb:.1f} MB")


def main():
    print("=" * 80)
    print("GENERATE O*NET OCCUPATION EMBEDDINGS - GEMINI-EMBEDDING-001")
    print("=" * 80)

    try:
        configure_gemini()
        df = load_onet_occupations()
        embedding_items = create_embedding_items(df)
        embedding_items = generate_gemini_embeddings(embedding_items)
        save_embeddings(embedding_items)

        print("\n" + "=" * 80)
        print("O*NET EMBEDDINGS COMPLETE")
        print("=" * 80)
        print(f"Occupations: {len(embedding_items)}")
        print(f"Embedding dimensions: {len(embedding_items[0]['embedding'])}")
        print(f"Output: {OUTPUT_FILE}")
        print("=" * 80)

    except Exception as e:
        print(f"\nERROR: {str(e)}")
        raise


if __name__ == '__main__':
    main()
