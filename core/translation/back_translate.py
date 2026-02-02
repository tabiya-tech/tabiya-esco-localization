#!/usr/bin/env python3
"""
Back-translation QA tool for validating translation quality.

Samples records from a translated file and back-translates to English
for comparison with the original.

Usage:
    python -m core.translation.back_translate \
        --country kenya_kesco \
        --lang sw \
        --sample 50
"""

import argparse
import logging
import os
import random
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from .config import LanguageConfig
from .providers import GeminiTranslator


def setup_logging(level: str = "INFO") -> None:
    """Configure logging."""
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler()],
    )


def get_api_key() -> str:
    """Retrieve API key from environment variables."""
    env_paths = [
        Path.cwd() / '.env',
        Path.cwd().parent / '.env',
        Path(__file__).parent.parent.parent / '.env',
    ]

    for env_path in env_paths:
        if env_path.exists():
            load_dotenv(env_path)
            break
    else:
        load_dotenv()

    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        raise ValueError("GEMINI_API_KEY not found in environment variables.")
    return api_key


def back_translate_batch(
    translator: GeminiTranslator,
    records: list[dict],
    source_lang: str,
) -> dict[str, dict]:
    """
    Back-translate a batch of records from source language to English.

    Args:
        translator: Initialized translator instance
        records: List of record dicts with translated fields
        source_lang: Source language code (e.g., 'sw')

    Returns:
        Dict mapping record ID to back-translated fields
    """
    lang_suffix = source_lang.upper()
    lang_info = LanguageConfig.get_language_info(source_lang)

    # Build prompt for back-translation
    prompt = f"""You are translating {lang_info['name']} text back to English.

For each record, translate the {lang_info['name']} fields back to natural English.
This is for quality assurance - we want to see if the meaning was preserved.

Return JSON with this structure:
{{
  "translations": {{
    "<id>": {{
      "PREFERREDLABEL_BACK_EN": "back-translated preferred label",
      "DESCRIPTION_BACK_EN": "back-translated description"
    }},
    ...
  }}
}}

Records to back-translate:
"""

    for rec in records:
        prompt += f"\n---\nID: {rec['ID']}\n"
        prompt += f"PREFERREDLABEL_{lang_suffix}: {rec.get(f'PREFERREDLABEL_{lang_suffix}', '')}\n"
        prompt += f"DESCRIPTION_{lang_suffix}: {rec.get(f'DESCRIPTION_{lang_suffix}', '')}\n"

    # Use translator's model directly
    try:
        import google.generativeai as genai
        genai.configure(api_key=translator.api_key)
        model = genai.GenerativeModel(translator.model)

        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                temperature=0.1,
            ),
        )

        import json
        result = json.loads(response.text)
        return result.get('translations', {})

    except Exception as e:
        logging.error(f"Back-translation failed: {e}")
        return {}


def run_back_translation(
    input_file: str,
    lang_code: str,
    sample_size: int = 50,
    output_file: str | None = None,
    model: str = "gemini-2.5-flash",
    seed: int | None = None,
) -> pd.DataFrame:
    """
    Run back-translation QA on a sample of translated records.

    Args:
        input_file: Path to translated CSV file
        lang_code: Source language code (e.g., 'sw')
        sample_size: Number of records to sample
        output_file: Output path (auto-generated if None)
        model: Model to use for back-translation
        seed: Random seed for reproducibility

    Returns:
        DataFrame with original, translated, and back-translated fields
    """
    setup_logging()

    # Load translated file
    logging.info(f"Loading {input_file}")
    df = pd.read_csv(input_file)
    logging.info(f"Total records: {len(df)}")

    # Sample records
    if seed is not None:
        random.seed(seed)

    sample_size = min(sample_size, len(df))
    sample_indices = random.sample(range(len(df)), sample_size)
    sample_df = df.iloc[sample_indices].copy()
    logging.info(f"Sampled {sample_size} records (seed={seed})")

    # Initialize translator
    api_key = get_api_key()
    lang_config = LanguageConfig.get_language_info(lang_code)
    translator = GeminiTranslator(api_key, model, lang_code, lang_config)

    lang_suffix = lang_code.upper()

    # Back-translate in batches
    batch_size = 10
    all_back_translations = {}

    records = sample_df.to_dict('records')
    total_batches = (len(records) + batch_size - 1) // batch_size

    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]
        batch_num = i // batch_size + 1
        logging.info(f"Back-translating batch {batch_num}/{total_batches}")

        result = back_translate_batch(translator, batch, lang_code)
        all_back_translations.update(result)

    # Build output dataframe
    output_records = []
    for _, row in sample_df.iterrows():
        record_id = str(row['ID'])
        back_trans = all_back_translations.get(record_id, {})

        output_records.append({
            'ID': row['ID'],
            'PREFERREDLABEL_EN': row.get('PREFERREDLABEL', ''),
            f'PREFERREDLABEL_{lang_suffix}': row.get(f'PREFERREDLABEL_{lang_suffix}', ''),
            'PREFERREDLABEL_BACK_EN': back_trans.get('PREFERREDLABEL_BACK_EN', ''),
            'DESCRIPTION_EN': row.get('DESCRIPTION', ''),
            f'DESCRIPTION_{lang_suffix}': row.get(f'DESCRIPTION_{lang_suffix}', ''),
            'DESCRIPTION_BACK_EN': back_trans.get('DESCRIPTION_BACK_EN', ''),
        })

    output_df = pd.DataFrame(output_records)

    # Save output
    if output_file is None:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_dir = Path(input_file).parent
        output_file = output_dir / f'back_translation_qa_{lang_code}_{timestamp}.csv'

    output_df.to_csv(output_file, index=False)
    logging.info(f"Saved back-translation QA to: {output_file}")

    # Also save Excel for easier review
    excel_file = str(output_file).replace('.csv', '.xlsx')
    output_df.to_excel(excel_file, index=False)
    logging.info(f"Saved Excel version to: {excel_file}")

    return output_df


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Back-translate samples for QA',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Back-translate 50 random Kenya Swahili records
    python -m core.translation.back_translate --country kenya_kesco --lang sw --sample 50

    # Use explicit input file
    python -m core.translation.back_translate --input translations.csv --lang sw --sample 50

    # Set random seed for reproducibility
    python -m core.translation.back_translate --country kenya_kesco --lang sw --sample 50 --seed 42
        """,
    )

    parser.add_argument(
        '--country', '-c',
        help='Country folder name (auto-sets input path)',
    )
    parser.add_argument(
        '--input', '-i',
        help='Input translated CSV file (overrides --country)',
    )
    parser.add_argument(
        '--lang', '-l',
        required=True,
        help='Source language code (e.g., sw, es)',
    )
    parser.add_argument(
        '--sample', '-n',
        type=int,
        default=50,
        help='Number of records to sample (default: 50)',
    )
    parser.add_argument(
        '--output', '-o',
        help='Output file path (auto-generated if not specified)',
    )
    parser.add_argument(
        '--model', '-m',
        default='gemini-2.5-flash',
        help='Model to use (default: gemini-2.5-flash)',
    )
    parser.add_argument(
        '--seed', '-s',
        type=int,
        help='Random seed for reproducibility',
    )

    return parser.parse_args()


def main() -> int:
    """Main entry point."""
    args = parse_args()

    # Determine input file
    if args.input:
        input_file = args.input
    elif args.country:
        input_file = Path.cwd() / 'countries' / args.country / 'outputs' / 'translations' / args.lang / f'occupations_translated_{args.lang}_FINAL.csv'
        if not Path(input_file).exists():
            print(f"Error: Input file not found: {input_file}")
            return 1
    else:
        print("Error: Either --country or --input must be provided")
        return 1

    print("=" * 70)
    print("BACK-TRANSLATION QA")
    print("=" * 70)
    print(f"  Input: {input_file}")
    print(f"  Language: {args.lang}")
    print(f"  Sample size: {args.sample}")
    print(f"  Model: {args.model}")
    print(f"  Seed: {args.seed or 'random'}")
    print("=" * 70)

    try:
        result_df = run_back_translation(
            input_file=str(input_file),
            lang_code=args.lang,
            sample_size=args.sample,
            output_file=args.output,
            model=args.model,
            seed=args.seed,
        )

        print(f"\nBack-translated {len(result_df)} records")
        return 0

    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        return 130
    except Exception as e:
        logging.exception("Back-translation failed")
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
