#!/usr/bin/env python3
"""
CLI entry point for ESCO taxonomy translation.

Usage:
    python -m core.translation.translate
    python core/translation/translate.py
"""

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .config import LanguageConfig, LLM_PROVIDERS
from .processor import TranslationProcessor


def setup_logging(log_file: str | None = None, level: str = "INFO") -> None:
    """Configure logging for the translation process."""
    handlers = [logging.StreamHandler()]

    if log_file:
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=handlers,
    )


def get_api_key() -> str:
    """
    Retrieve API key from environment variables.

    Returns:
        API key string

    Raises:
        ValueError: If API key not found
    """
    # Try loading from various .env locations
    env_paths = [
        Path.cwd() / '.env',
        Path.cwd().parent / '.env',
        Path(__file__).parent.parent.parent / '.env',
    ]

    for env_path in env_paths:
        if env_path.exists():
            load_dotenv(env_path)
            logging.info(f"Loaded environment from: {env_path}")
            break
    else:
        load_dotenv()

    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY not found. Please set it in your .env file or environment variables."
        )
    return api_key


def select_language_interactive() -> str | None:
    """
    Interactive language selection.

    Returns:
        Selected language code or None if cancelled
    """
    LanguageConfig.display_language_menu()

    print("\nEnter language code (e.g., 'sw' for Swahili, 'es' for Spanish)")
    print("Or type 'list' to see the menu again, 'quit' to exit")

    while True:
        choice = input("\nYour choice: ").strip().lower()

        if choice == 'quit':
            return None

        if choice == 'list':
            LanguageConfig.display_language_menu()
            continue

        lang_info = LanguageConfig.get_language_info(choice)
        if lang_info:
            print(f"\nSelected: {lang_info['name']} ({lang_info['native_name']})")

            confirm = input("Proceed with this language? (yes/no): ").strip().lower()
            if confirm == 'yes':
                return choice
        else:
            print(f"Invalid language code: '{choice}'")
            print("Please enter a valid code from the list above")


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Translate ESCO taxonomy files to target language',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Translate Kenya taxonomy to Swahili
    python -m core.translation.translate --country kenya_kesco --lang sw

    # Interactive language selection for Kenya
    python -m core.translation.translate --country kenya_kesco

    # Use explicit source/output paths (legacy mode)
    python -m core.translation.translate --lang sw --source ./taxonomy --output ./translations

    # Translate only occupations
    python -m core.translation.translate --country kenya_kesco --lang sw --filter occupations
        """,
    )

    parser.add_argument(
        '--country', '-c',
        help='Country folder name (e.g., kenya_kesco, argentina_cno2017). Sets source and output paths automatically.',
    )
    parser.add_argument(
        '--lang', '-l',
        help='Target language code (e.g., sw, es, fr). Interactive if not specified.',
    )
    parser.add_argument(
        '--source', '-s',
        help='Source directory containing taxonomy files. Auto-set if --country provided.',
    )
    parser.add_argument(
        '--output', '-o',
        help='Output directory for translated files. Auto-set if --country provided.',
    )
    parser.add_argument(
        '--filter', '-f',
        help='Filter to process specific files (e.g., "occupations", "skills")',
    )
    parser.add_argument(
        '--batch-size', '-b',
        type=int,
        default=15,
        help='Number of records per batch (default: 15)',
    )
    parser.add_argument(
        '--workers', '-w',
        type=int,
        default=3,
        help='Number of parallel workers (default: 3, max: 5)',
    )
    parser.add_argument(
        '--model', '-m',
        default='gemini-3-flash-preview',
        help='Model to use for translation (default: gemini-3-flash-preview)',
    )
    parser.add_argument(
        '--log-level',
        default='INFO',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        help='Logging level (default: INFO)',
    )
    parser.add_argument(
        '--log-file',
        help='Log file path (logs to console only if not specified)',
    )
    parser.add_argument(
        '--yes', '-y',
        action='store_true',
        help='Skip confirmation prompt',
    )

    return parser.parse_args()


def main() -> int:
    """Main execution function."""
    args = parse_args()

    # Setup logging
    log_file = args.log_file
    if not log_file and args.lang:
        log_file = f'translation_{args.lang}.log'
    setup_logging(log_file, args.log_level)

    print("=" * 70)
    print("ESCO TAXONOMY TRANSLATION SYSTEM")
    print("=" * 70)

    # Get API key
    try:
        api_key = get_api_key()
    except ValueError as e:
        print(f"Configuration Error: {e}")
        return 1

    # Get language
    lang_code = args.lang
    if not lang_code:
        lang_code = select_language_interactive()
        if not lang_code:
            print("\nTranslation cancelled.")
            return 0

    lang_info = LanguageConfig.get_language_info(lang_code)
    if not lang_info:
        print(f"Error: Unsupported language code '{lang_code}'")
        print("Use --lang with a valid code, or run without --lang for interactive selection.")
        return 1

    # Validate workers
    parallel_workers = min(max(args.workers, 1), 5)

    # Resolve paths based on --country or explicit paths
    if args.country:
        # Country-based paths
        country_dir = Path.cwd() / 'countries' / args.country
        if not country_dir.exists():
            print(f"Error: Country folder not found: {country_dir}")
            return 1

        source_dir = args.source or country_dir / 'outputs' / 'taxonomy'
        output_dir = args.output or country_dir / 'outputs' / 'translations'

        if isinstance(source_dir, str):
            source_dir = Path(source_dir)
        if isinstance(output_dir, str):
            output_dir = Path(output_dir)
    else:
        # Explicit paths (legacy mode)
        if not args.source:
            print("Error: Either --country or --source must be provided")
            return 1

        source_dir = Path(args.source)
        output_dir = Path(args.output) if args.output else Path.cwd() / 'output' / 'translations'

    # Make paths absolute
    if not source_dir.is_absolute():
        source_dir = Path.cwd() / source_dir

    if not output_dir.is_absolute():
        output_dir = Path.cwd() / output_dir

    # Check source directory exists
    if not source_dir.exists():
        print(f"Error: Source directory not found: {source_dir}")
        return 1

    # Display configuration
    print(f"\nTRANSLATION CONFIGURATION")
    print(f"{'=' * 70}")
    print(f"  Target language: {lang_info['name']} ({lang_code.upper()})")
    print(f"  Model: {args.model}")
    print(f"  Batch size: {args.batch_size}")
    print(f"  Parallel workers: {parallel_workers}")
    print(f"  File filter: {args.filter or 'None (all files)'}")
    print(f"  Source directory: {source_dir}")
    print(f"  Output directory: {output_dir}")
    print(f"{'=' * 70}")

    # Confirm
    if not args.yes:
        confirm = input("\nStart translation? (yes/no): ").strip().lower()
        if confirm != 'yes':
            print("Translation cancelled.")
            return 0

    # Initialize processor
    try:
        processor = TranslationProcessor(
            api_key=api_key,
            lang_code=lang_code,
            source_dir=str(source_dir),
            output_dir=str(output_dir),
            model=args.model,
            batch_size=args.batch_size,
            parallel_workers=parallel_workers,
        )
    except Exception as e:
        print(f"Error initializing processor: {e}")
        return 1

    # Execute translation
    try:
        results = processor.translate_taxonomy(file_filter=args.filter)

        if results:
            processor.print_summary(results)
            return 0
        else:
            print("No translation results to display")
            return 1

    except KeyboardInterrupt:
        print("\n\nTranslation interrupted by user.")
        print("Progress has been saved. Run again to resume.")
        return 130

    except Exception as e:
        logging.exception("Translation failed with error")
        print(f"\nError during translation: {e}")
        print("Check the log file for details.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
