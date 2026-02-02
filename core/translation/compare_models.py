#!/usr/bin/env python3
"""
Model comparison tool for translation quality assessment.

Compares translations across multiple models for the same set of records.

Usage:
    python -m core.translation.compare_models \
        --country kenya_kesco \
        --lang sw \
        --sample 50 \
        --models gemini-2.5-pro gemini-3-pro
"""

import argparse
import logging
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from .config import TAXONOMY_FILES, LanguageConfig
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


def translate_with_model(
    api_key: str,
    model: str,
    records_df: pd.DataFrame,
    lang_code: str,
    batch_size: int = 5,
) -> dict[str, dict]:
    """
    Translate records using a specific model.

    Args:
        api_key: API key for the model
        model: Model name
        records_df: DataFrame with records to translate
        lang_code: Target language code
        batch_size: Records per batch

    Returns:
        Dict mapping record ID to translated fields
    """
    lang_config = LanguageConfig.get_language_info(lang_code)
    translator = GeminiTranslator(api_key, model, lang_code, lang_config)
    file_config = TAXONOMY_FILES['occupations.csv']

    all_translations = {}
    total_batches = (len(records_df) + batch_size - 1) // batch_size

    for i in range(0, len(records_df), batch_size):
        batch_df = records_df.iloc[i:i + batch_size]
        batch_num = i // batch_size + 1
        logging.info(f"  Batch {batch_num}/{total_batches} ({len(batch_df)} records)")

        try:
            result = translator.translate_batch(batch_df, file_config, "occupations.csv")
            if result:
                all_translations.update(result)
            time.sleep(1)  # Rate limiting
        except Exception as e:
            logging.error(f"  Batch {batch_num} failed: {e}")

    return all_translations


def run_model_comparison(
    input_file: str,
    lang_code: str,
    models: list[str],
    sample_size: int = 50,
    output_file: str | None = None,
    seed: int | None = None,
    existing_model: str = "gemini-2.5-flash",
) -> pd.DataFrame:
    """
    Compare translations across multiple models.

    Args:
        input_file: Path to existing translated CSV file
        lang_code: Target language code
        models: List of models to compare
        sample_size: Number of records to sample
        output_file: Output path
        seed: Random seed
        existing_model: Model used for existing translations

    Returns:
        DataFrame with comparison results
    """
    setup_logging()

    # Load existing translated file
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

    # Get API key
    api_key = get_api_key()
    lang_suffix = lang_code.upper()

    # Store translations by model
    model_translations = {}

    # Translate with each model
    for model in models:
        logging.info(f"\nTranslating with {model}...")
        translations = translate_with_model(
            api_key=api_key,
            model=model,
            records_df=sample_df,
            lang_code=lang_code,
            batch_size=5,
        )
        model_translations[model] = translations
        logging.info(f"  Received {len(translations)} translations")

    # Build output dataframe
    output_records = []

    for _, row in sample_df.iterrows():
        record_id = row['ORIGINURI']  # Use ORIGINURI as the key
        record = {
            'ID': row['ID'],
            'ORIGINURI': record_id,
            'PREFERREDLABEL_EN': row.get('PREFERREDLABEL', ''),
            f'PREFERREDLABEL_{lang_suffix}_{existing_model.replace("-", "_").replace(".", "_")}': row.get(f'PREFERREDLABEL_{lang_suffix}', ''),
        }

        # Add translations from each model
        for model in models:
            model_key = model.replace("-", "_").replace(".", "_")
            trans = model_translations[model].get(record_id, {})
            record[f'PREFERREDLABEL_{lang_suffix}_{model_key}'] = trans.get(f'PREFERREDLABEL_{lang_suffix}', '')
            record[f'ALTLABELS_{lang_suffix}_{model_key}'] = trans.get(f'ALTLABELS_{lang_suffix}', '')
            record[f'DESCRIPTION_{lang_suffix}_{model_key}'] = trans.get(f'DESCRIPTION_{lang_suffix}', '')

        # Add existing translations for comparison
        record[f'ALTLABELS_{lang_suffix}_{existing_model.replace("-", "_").replace(".", "_")}'] = row.get(f'ALTLABELS_{lang_suffix}', '')
        record[f'DESCRIPTION_{lang_suffix}_{existing_model.replace("-", "_").replace(".", "_")}'] = row.get(f'DESCRIPTION_{lang_suffix}', '')
        record['DESCRIPTION_EN'] = row.get('DESCRIPTION', '')

        output_records.append(record)

    output_df = pd.DataFrame(output_records)

    # Reorder columns for better comparison
    col_order = ['ID', 'ORIGINURI', 'PREFERREDLABEL_EN']
    for model in [existing_model] + models:
        model_key = model.replace("-", "_").replace(".", "_")
        col_order.append(f'PREFERREDLABEL_{lang_suffix}_{model_key}')

    col_order.append('DESCRIPTION_EN')
    for model in [existing_model] + models:
        model_key = model.replace("-", "_").replace(".", "_")
        col_order.append(f'DESCRIPTION_{lang_suffix}_{model_key}')

    # Add any remaining columns
    remaining = [c for c in output_df.columns if c not in col_order]
    col_order.extend(remaining)

    # Filter to only existing columns
    col_order = [c for c in col_order if c in output_df.columns]
    output_df = output_df[col_order]

    # Save output
    if output_file is None:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_dir = Path(input_file).parent
        output_file = output_dir / f'model_comparison_{lang_code}_{timestamp}.csv'

    output_df.to_csv(output_file, index=False)
    logging.info(f"\nSaved comparison to: {output_file}")

    # Also save Excel
    excel_file = str(output_file).replace('.csv', '.xlsx')
    output_df.to_excel(excel_file, index=False)
    logging.info(f"Saved Excel version to: {excel_file}")

    return output_df


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Compare translations across multiple models',
    )

    parser.add_argument(
        '--country', '-c',
        help='Country folder name',
    )
    parser.add_argument(
        '--input', '-i',
        help='Input translated CSV file',
    )
    parser.add_argument(
        '--lang', '-l',
        required=True,
        help='Target language code',
    )
    parser.add_argument(
        '--models', '-m',
        nargs='+',
        default=['gemini-2.5-pro', 'gemini-3-pro'],
        help='Models to compare (default: gemini-2.5-pro gemini-3-pro)',
    )
    parser.add_argument(
        '--sample', '-n',
        type=int,
        default=50,
        help='Number of records to sample (default: 50)',
    )
    parser.add_argument(
        '--output', '-o',
        help='Output file path',
    )
    parser.add_argument(
        '--seed', '-s',
        type=int,
        help='Random seed for reproducibility',
    )
    parser.add_argument(
        '--existing-model',
        default='gemini-2.5-flash',
        help='Model used for existing translations (default: gemini-2.5-flash)',
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
    print("MODEL COMPARISON")
    print("=" * 70)
    print(f"  Input: {input_file}")
    print(f"  Language: {args.lang}")
    print(f"  Sample size: {args.sample}")
    print(f"  Existing model: {args.existing_model}")
    print(f"  Models to compare: {', '.join(args.models)}")
    print(f"  Seed: {args.seed or 'random'}")
    print("=" * 70)

    try:
        result_df = run_model_comparison(
            input_file=str(input_file),
            lang_code=args.lang,
            models=args.models,
            sample_size=args.sample,
            output_file=args.output,
            seed=args.seed,
            existing_model=args.existing_model,
        )

        print(f"\nCompared {len(result_df)} records across {len(args.models) + 1} models")
        return 0

    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        return 130
    except Exception as e:
        logging.exception("Comparison failed")
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
