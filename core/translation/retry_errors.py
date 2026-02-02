#!/usr/bin/env python3
"""
Retry script for failed translation records.

Usage:
    python -m core.translation.retry_errors --input output/kenya_sw/sw/occupations_translated_sw_20260122_191458.csv
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from .config import TAXONOMY_FILES, LanguageConfig
from .providers import GeminiTranslator
from .validation import ERROR_PATTERNS


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


def find_error_records(df: pd.DataFrame, lang_code: str) -> pd.DataFrame:
    """Find records with translation errors."""
    lang_suffix = lang_code.upper()
    error_mask = pd.Series([False] * len(df), index=df.index)

    for col in df.columns:
        if col.endswith(f'_{lang_suffix}'):
            col_has_error = df[col].astype(str).str.contains('|'.join(ERROR_PATTERNS), na=False, regex=True)
            error_mask = error_mask | col_has_error

    return df[error_mask].copy()


def translate_single_record(
    translator: GeminiTranslator,
    row: pd.Series,
    file_config: dict,
    lang_code: str,
) -> dict[str, str] | None:
    """Translate a single record."""
    # Create a single-row DataFrame
    single_df = pd.DataFrame([row])

    try:
        result = translator.translate_batch(single_df, file_config, "occupations.csv")
        if result:
            record_id = row[file_config['id_field']]
            return result.get(record_id)
    except Exception as e:
        logging.error(f"Error translating record: {e}")

    return None


def retry_errors(
    input_file: str,
    lang_code: str = "sw",
    batch_size: int = 3,
    model: str = "gemini-3-flash-preview",
    delay: float = 1.0,
) -> dict:
    """
    Retry translation for error records.

    Args:
        input_file: Path to the translated CSV with errors
        lang_code: Target language code
        batch_size: Records per batch (smaller = more reliable)
        model: Model to use
        delay: Delay between batches in seconds

    Returns:
        Dictionary with retry statistics
    """
    setup_logging()

    # Load the translated file
    logging.info(f"Loading {input_file}")
    df = pd.read_csv(input_file)
    logging.info(f"Total records: {len(df)}")

    # Find error records
    error_df = find_error_records(df, lang_code)
    error_count = len(error_df)
    logging.info(f"Found {error_count} records with errors")

    if error_count == 0:
        logging.info("No errors to retry")
        return {'total': len(df), 'errors': 0, 'retried': 0, 'success': 0}

    # Get API key and initialize translator
    api_key = get_api_key()
    lang_config = LanguageConfig.get_language_info(lang_code)
    translator = GeminiTranslator(api_key, model, lang_code, lang_config)

    # Get file config
    file_config = TAXONOMY_FILES['occupations.csv']
    lang_suffix = lang_code.upper()

    # Process in small batches
    success_count = 0
    failed_ids = []

    total_batches = (error_count + batch_size - 1) // batch_size
    logging.info(f"Processing {error_count} records in {total_batches} batches of {batch_size}")

    for batch_num in range(total_batches):
        start_idx = batch_num * batch_size
        end_idx = min(start_idx + batch_size, error_count)
        batch_df = error_df.iloc[start_idx:end_idx]

        logging.info(f"Batch {batch_num + 1}/{total_batches} ({len(batch_df)} records)")

        try:
            result = translator.translate_batch(batch_df, file_config, "occupations.csv")

            if result:
                # Update the main DataFrame with successful translations
                for record_id, translations in result.items():
                    # Find the row in the original DataFrame
                    mask = df[file_config['id_field']] == record_id
                    if mask.any():
                        for field, value in translations.items():
                            if field in df.columns:
                                # Only update if no error pattern in new value
                                if not any(err in str(value) for err in ERROR_PATTERNS):
                                    df.loc[mask, field] = value
                                    success_count += 1

                logging.info(f"  Batch {batch_num + 1}: {len(result)} translations received")
            else:
                logging.warning(f"  Batch {batch_num + 1}: No translations returned")
                for _, row in batch_df.iterrows():
                    failed_ids.append(row[file_config['id_field']])

        except Exception as e:
            logging.error(f"  Batch {batch_num + 1} failed: {e}")
            for _, row in batch_df.iterrows():
                failed_ids.append(row[file_config['id_field']])

        # Delay between batches
        if batch_num < total_batches - 1:
            time.sleep(delay)

    # Save updated file
    output_file = input_file.replace('.csv', '_retried.csv')
    df.to_csv(output_file, index=False)
    logging.info(f"Saved updated file to: {output_file}")

    # Check remaining errors
    remaining_errors = find_error_records(df, lang_code)
    logging.info(f"Remaining errors after retry: {len(remaining_errors)}")

    # Print summary
    print("\n" + "=" * 60)
    print("RETRY SUMMARY")
    print("=" * 60)
    print(f"  Original errors: {error_count}")
    print(f"  Successfully retried: {error_count - len(remaining_errors)}")
    print(f"  Still failing: {len(remaining_errors)}")
    print(f"  Output file: {output_file}")
    print("=" * 60)

    return {
        'total': len(df),
        'original_errors': error_count,
        'retried_success': error_count - len(remaining_errors),
        'remaining_errors': len(remaining_errors),
        'output_file': output_file,
    }


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Retry translation for error records',
    )
    parser.add_argument(
        '--input', '-i',
        required=True,
        help='Path to the translated CSV file with errors',
    )
    parser.add_argument(
        '--lang', '-l',
        default='sw',
        help='Target language code (default: sw)',
    )
    parser.add_argument(
        '--batch-size', '-b',
        type=int,
        default=3,
        help='Records per batch (default: 3, smaller = more reliable)',
    )
    parser.add_argument(
        '--model', '-m',
        default='gemini-3-flash-preview',
        help='Model to use (default: gemini-3-flash-preview)',
    )
    parser.add_argument(
        '--delay', '-d',
        type=float,
        default=1.0,
        help='Delay between batches in seconds (default: 1.0)',
    )
    parser.add_argument(
        '--yes', '-y',
        action='store_true',
        help='Skip confirmation prompt',
    )
    return parser.parse_args()


def main() -> int:
    """Main entry point."""
    args = parse_args()

    print("=" * 60)
    print("TRANSLATION ERROR RETRY")
    print("=" * 60)
    print(f"  Input file: {args.input}")
    print(f"  Language: {args.lang}")
    print(f"  Batch size: {args.batch_size}")
    print(f"  Model: {args.model}")
    print("=" * 60)

    if not args.yes:
        confirm = input("\nStart retry? (yes/no): ").strip().lower()
        if confirm != 'yes':
            print("Cancelled.")
            return 0

    try:
        result = retry_errors(
            input_file=args.input,
            lang_code=args.lang,
            batch_size=args.batch_size,
            model=args.model,
            delay=args.delay,
        )
        return 0 if result['remaining_errors'] == 0 else 1

    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        return 130
    except Exception as e:
        logging.exception("Retry failed")
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
