"""
Generate Embeddings using Gemini API

Shared utility for generating embeddings for any taxonomy.
Used by country-specific scripts to generate national taxonomy embeddings.

Usage:
    from scripts.generate_embeddings import generate_embeddings_for_texts

    embeddings = generate_embeddings_for_texts(
        texts=["occupation 1", "occupation 2"],
        api_key=os.environ.get('GEMINI_API_KEY')
    )
"""

import time
from typing import List, Optional
from tqdm import tqdm

# Model configuration
MODEL_NAME = 'models/gemini-embedding-001'
BATCH_SIZE = 100
TASK_TYPE = 'SEMANTIC_SIMILARITY'
OUTPUT_DIMENSIONALITY = 768


def configure_gemini(api_key: str):
    """Configure Gemini API with the provided key."""
    import google.generativeai as genai
    if not api_key:
        raise ValueError(
            "API key not provided. Set GEMINI_API_KEY or GOOGLE_API_KEY environment variable."
        )
    genai.configure(api_key=api_key)


def generate_embeddings_for_texts(
    texts: List[str],
    api_key: str,
    batch_size: int = BATCH_SIZE,
    show_progress: bool = True
) -> List[List[float]]:
    """
    Generate embeddings for a list of texts using Gemini API.

    Args:
        texts: List of text strings to embed
        api_key: Gemini API key
        batch_size: Number of texts per API call (max 100)
        show_progress: Whether to show progress bar

    Returns:
        List of embedding vectors (each is a list of floats)
    """
    import google.generativeai as genai

    configure_gemini(api_key)

    all_embeddings = []
    num_batches = (len(texts) + batch_size - 1) // batch_size

    iterator = range(0, len(texts), batch_size)
    if show_progress:
        iterator = tqdm(iterator, total=num_batches, desc="Generating embeddings")

    for i in iterator:
        batch_texts = texts[i:i + batch_size]

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
                    print(f"\nRate limit hit, waiting {wait_time}s (attempt {attempt+1}/{max_retries})...")
                    time.sleep(wait_time)
                else:
                    print(f"\nError: {e}")
                    time.sleep(5)

                if attempt == max_retries - 1:
                    raise

        # Rate limit delay between batches
        time.sleep(1.5)

    return all_embeddings


def generate_esco_embeddings(
    esco_csv_path: str,
    output_path: str,
    api_key: str,
    language: str = 'English'
) -> dict:
    """
    Generate embeddings for ESCO occupations from CSV file.

    Creates separate embeddings for preferred labels and alt labels.

    Args:
        esco_csv_path: Path to ESCO occupations.csv
        output_path: Path to save output JSON
        api_key: Gemini API key
        language: Language label for metadata

    Returns:
        Dictionary with metadata and embeddings
    """
    import pandas as pd
    import json
    from pathlib import Path

    print(f"Loading ESCO occupations from {esco_csv_path}...")
    df = pd.read_csv(esco_csv_path)

    # Filter out ISCO groups and special codes for English ESCO
    if language == 'English':
        df = df[
            ~df['CODE'].astype(str).str.startswith('I') &
            ~df['CODE'].astype(str).str.contains('5221_2', na=False)
        ]

    print(f"Loaded {len(df)} occupations")

    # Create embedding items
    embedding_items = []
    seen = set()

    for _, row in df.iterrows():
        esco_code = str(row['CODE']) if pd.notna(row['CODE']) else ''
        description = str(row.get('DESCRIPTION', ''))[:200] if pd.notna(row.get('DESCRIPTION')) else ''

        # Preferred label
        preferred = str(row['PREFERREDLABEL']) if pd.notna(row['PREFERREDLABEL']) else ''
        if preferred and (esco_code, preferred.lower()) not in seen:
            seen.add((esco_code, preferred.lower()))
            embedding_items.append({
                'esco_code': esco_code,
                'label': preferred,
                'label_type': 'preferred',
                'description': description
            })

        # Alt labels
        altlabels = str(row.get('ALTLABELS', ''))
        if altlabels and altlabels != 'nan':
            for alt in altlabels.split('\n'):
                alt = alt.strip()
                if alt and (esco_code, alt.lower()) not in seen:
                    seen.add((esco_code, alt.lower()))
                    embedding_items.append({
                        'esco_code': esco_code,
                        'label': alt,
                        'label_type': 'alternative',
                        'description': description
                    })

    print(f"Created {len(embedding_items)} label items")

    # Generate embeddings
    texts = [item['label'] for item in embedding_items]
    embeddings = generate_embeddings_for_texts(texts, api_key)

    for i, item in enumerate(embedding_items):
        item['embedding'] = embeddings[i]

    # Save
    output = {
        'metadata': {
            'model': MODEL_NAME,
            'language': language,
            'num_occupations': len(df),
            'num_embeddings': len(embedding_items),
            'embedding_dim': len(embeddings[0]),
            'task_type': TASK_TYPE
        },
        'embeddings': embedding_items
    }

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Saved {len(embedding_items)} embeddings to {output_path}")
    return output


def generate_taxonomy_embeddings(
    items: List[dict],
    text_field: str,
    api_key: str,
    output_path: Optional[str] = None,
    metadata: Optional[dict] = None
) -> List[dict]:
    """
    Generate embeddings for a list of taxonomy items.

    Args:
        items: List of dicts, each must have the text_field
        text_field: Key name for the text to embed (e.g., 'occupation_en')
        api_key: Gemini API key
        output_path: Optional path to save JSON output
        metadata: Optional metadata to include in output

    Returns:
        Items with 'embedding' field added
    """
    import json
    from pathlib import Path

    texts = [item[text_field] for item in items]
    embeddings = generate_embeddings_for_texts(texts, api_key)

    for i, item in enumerate(items):
        item['embedding'] = embeddings[i]

    if output_path:
        output = {
            'metadata': metadata or {},
            'occupations': items
        }
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"Saved {len(items)} embeddings to {output_path}")

    return items
