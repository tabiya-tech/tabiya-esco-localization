"""
Generate English ESCO Embeddings using Gemini gemini-embedding-001

Uses Google's latest Gemini embedding model (100+ languages, top MTEB scores).
Creates separate embeddings for each preferred label and alt label (label-only, no descriptions).

Input: shared_data/esco_taxonomy/occupations.csv (English)
Output: shared_data/esco_embeddings_en_gemini.json

Requirements:
    pip install google-generativeai pandas tqdm python-dotenv

Usage:
    python shared_data/generate_esco_embeddings_en.py
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
ENGLISH_ESCO_FILE = Path(__file__).parent / 'esco_taxonomy' / 'occupations.csv'
OUTPUT_FILE = Path(__file__).parent / 'esco_embeddings_en_gemini.json'

# Model configuration
MODEL_NAME = 'models/gemini-embedding-001'
BATCH_SIZE = 100  # Gemini allows up to 100 texts per batch
TASK_TYPE = 'SEMANTIC_SIMILARITY'
OUTPUT_DIMENSIONALITY = 768  # Using 768 for compatibility


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


def load_english_esco() -> pd.DataFrame:
    """Load English ESCO occupations."""
    print(f"\n[1/4] Loading English ESCO occupations from {ENGLISH_ESCO_FILE}...")

    if not ENGLISH_ESCO_FILE.exists():
        raise FileNotFoundError(f"English ESCO file not found: {ENGLISH_ESCO_FILE}")

    df = pd.read_csv(ENGLISH_ESCO_FILE)

    # Filter out ISCO groups (codes starting with 'I') and special codes
    df = df[
        ~df['CODE'].astype(str).str.startswith('I') &
        ~df['CODE'].astype(str).str.contains('5221_2', na=False)
    ]

    print(f"  Loaded {len(df)} English ESCO occupations")

    required_cols = ['CODE', 'PREFERREDLABEL', 'ALTLABELS']
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    return df


def create_separate_label_items(df: pd.DataFrame) -> list:
    """Create separate embedding items for each label (label-only, no descriptions)."""
    print("\n[2/4] Creating separate label items...")

    embedding_items = []
    seen_combinations = set()
    stats = {'total_occupations': 0, 'total_items': 0, 'duplicates': 0}

    for _, row in tqdm(df.iterrows(), total=len(df), desc="  Processing"):
        stats['total_occupations'] += 1
        esco_code = str(row['CODE']) if pd.notna(row['CODE']) else ''
        description = str(row['DESCRIPTION']) if pd.notna(row.get('DESCRIPTION')) else ''

        # Preferred label
        preferred_label = str(row['PREFERREDLABEL']) if pd.notna(row['PREFERREDLABEL']) else ''
        if preferred_label:
            dedup_key = (esco_code, preferred_label.lower())
            if dedup_key not in seen_combinations:
                seen_combinations.add(dedup_key)
                embedding_items.append({
                    'esco_code': esco_code,
                    'label': preferred_label,
                    'label_type': 'preferred',
                    'description': description[:200],
                    'embedding_text': preferred_label  # Label only!
                })
                stats['total_items'] += 1
            else:
                stats['duplicates'] += 1

        # Alt labels
        altlabels_raw = str(row['ALTLABELS']) if pd.notna(row['ALTLABELS']) else ''
        if altlabels_raw and altlabels_raw != 'nan':
            altlabels = [alt.strip() for alt in altlabels_raw.split('\n') if alt.strip()]
            for alt_label in altlabels:
                dedup_key = (esco_code, alt_label.lower())
                if dedup_key not in seen_combinations:
                    seen_combinations.add(dedup_key)
                    embedding_items.append({
                        'esco_code': esco_code,
                        'label': alt_label,
                        'label_type': 'alternative',
                        'description': description[:200],
                        'embedding_text': alt_label  # Label only!
                    })
                    stats['total_items'] += 1
                else:
                    stats['duplicates'] += 1

    print(f"  Created {stats['total_items']} label items from {stats['total_occupations']} occupations")
    print(f"  Duplicates removed: {stats['duplicates']}")
    return embedding_items


def generate_gemini_embeddings(embedding_items: list) -> list:
    """Generate embeddings using Gemini gemini-embedding-001."""
    print(f"\n[3/4] Generating embeddings with Gemini {MODEL_NAME}...")
    print(f"  Total items: {len(embedding_items)}")
    print(f"  Batch size: {BATCH_SIZE}")
    print(f"  Task type: {TASK_TYPE}")

    texts = [item['embedding_text'] for item in embedding_items]
    all_embeddings = []

    # Process in batches
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

        # Rate limit delay
        time.sleep(1.5)

    print(f"  Generated {len(all_embeddings)} embeddings")
    print(f"  Dimensions: {len(all_embeddings[0])}")

    # Add embeddings to items
    for i, item in enumerate(embedding_items):
        item['embedding'] = all_embeddings[i]

    return embedding_items


def save_embeddings(embedding_items: list, total_occupations: int) -> None:
    """Save embeddings to JSON file."""
    print(f"\n[4/4] Saving to {OUTPUT_FILE}...")

    data = {
        'metadata': {
            'model': MODEL_NAME,
            'language': 'English',
            'approach': 'Gemini Embeddings - Separate per Label',
            'source_file': str(ENGLISH_ESCO_FILE),
            'num_source_occupations': total_occupations,
            'num_embeddings': len(embedding_items),
            'embeddings_per_occupation': len(embedding_items) / total_occupations,
            'embedding_dim': len(embedding_items[0]['embedding']),
            'format': 'label only (no description) - Gemini gemini-embedding-001',
            'task_type': TASK_TYPE,
            'date_generated': pd.Timestamp.now().isoformat()
        },
        'embeddings': embedding_items
    }

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    file_size_mb = OUTPUT_FILE.stat().st_size / (1024 * 1024)
    print(f"  Saved {len(embedding_items)} embeddings")
    print(f"  File size: {file_size_mb:.1f} MB")


def main():
    """Main execution"""
    print("=" * 80)
    print("GENERATE ENGLISH ESCO EMBEDDINGS - GEMINI-EMBEDDING-001")
    print("=" * 80)

    try:
        configure_gemini()
        df = load_english_esco()
        total_occupations = len(df)
        embedding_items = create_separate_label_items(df)
        embedding_items = generate_gemini_embeddings(embedding_items)
        save_embeddings(embedding_items, total_occupations)

        print("\n" + "=" * 80)
        print("ENGLISH ESCO EMBEDDINGS COMPLETE")
        print("=" * 80)
        print(f"Source occupations: {total_occupations}")
        print(f"Total embeddings: {len(embedding_items)}")
        print(f"Embedding dimensions: {len(embedding_items[0]['embedding'])}")
        print(f"Output: {OUTPUT_FILE}")
        print("=" * 80)

    except Exception as e:
        print(f"\nERROR: {str(e)}")
        raise


if __name__ == '__main__':
    main()
