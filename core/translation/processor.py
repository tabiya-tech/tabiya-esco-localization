"""
Main translation processor for ESCO taxonomy files.
"""

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import pandas as pd

from .config import TAXONOMY_FILES, LanguageConfig
from .file_processor import FileProcessor
from .performance import PerformanceTracker
from .progress import ProgressManager
from .providers import GeminiTranslator
from .validation import ERROR_BATCH_SPLIT, ERROR_JSON_PARSE_SMALL_BATCH


class TranslationProcessor:
    """Main processor for translating ESCO taxonomy files."""

    # Processing configuration
    DEFAULT_BATCH_SIZE = 15
    DEFAULT_PARALLEL_WORKERS = 3
    PARALLEL_BATCH_GROUP_SIZE = 6

    def __init__(
        self,
        api_key: str,
        lang_code: str,
        source_dir: str,
        output_dir: str,
        model: str = "gemini-3-flash",
        batch_size: int = DEFAULT_BATCH_SIZE,
        parallel_workers: int = DEFAULT_PARALLEL_WORKERS,
    ):
        """
        Initialize the translation processor.

        Args:
            api_key: API key for the translation provider
            lang_code: Target language code (e.g., 'sw', 'es')
            source_dir: Directory containing source taxonomy files
            output_dir: Directory for output files
            model: Model to use for translation
            batch_size: Number of records per batch
            parallel_workers: Number of parallel workers
        """
        self.lang_code = lang_code
        self.lang_config = LanguageConfig.get_language_info(lang_code)

        if not self.lang_config:
            raise ValueError(f"Unsupported language code: {lang_code}")

        self.batch_size = batch_size
        self.parallel_workers = parallel_workers

        # Initialize components
        self.translator = GeminiTranslator(api_key, model, lang_code, self.lang_config)
        self.file_processor = FileProcessor(lang_code, output_dir, source_dir)
        self.progress_manager = ProgressManager(lang_code, output_dir)
        self.performance_tracker = PerformanceTracker()

    def translate_batch(
        self,
        batch_rows: pd.DataFrame,
        file_config: dict[str, Any],
        file_name: str,
        context: str = "",
    ) -> dict[str, dict[str, str]] | None:
        """
        Translate a single batch of records.

        Args:
            batch_rows: DataFrame containing records to translate
            file_config: Configuration for the taxonomy file
            file_name: Source file name
            context: Context string for logging

        Returns:
            Dictionary mapping record IDs to translated fields, or None on failure
        """
        batch_size = len(batch_rows)
        entity_type = file_config['type']

        logging.info(f"Processing {batch_size} {entity_type.lower()} records - {context}")

        # Estimate tokens and record API call
        prompt_estimate = batch_size * 500  # Rough estimate
        self.performance_tracker.record_api_call(prompt_estimate)

        # Call translator
        result = self.translator.translate_batch(batch_rows, file_config, file_name)

        if result:
            logging.info(f"Successfully processed {len(result)} translations - {context}")
        else:
            logging.warning(f"No translations returned for {context}")
            self.performance_tracker.record_error("TRANSLATION_FAILED", context)

        return result

    def translate_with_batch_splitting(
        self,
        batch_rows: pd.DataFrame,
        file_config: dict[str, Any],
        file_name: str,
        context: str = "",
    ) -> dict[str, dict[str, str]]:
        """
        Translate batch with automatic splitting on errors.

        Args:
            batch_rows: DataFrame containing records to translate
            file_config: Configuration for the taxonomy file
            file_name: Source file name
            context: Context string for logging

        Returns:
            Dictionary mapping record IDs to translated fields
        """
        result = self.translate_batch(batch_rows, file_config, file_name, context)

        if result is not None:
            return result

        # Try splitting if batch is large enough
        if len(batch_rows) > 5:
            logging.info(f"Splitting batch of {len(batch_rows)} records into smaller batches")

            split_size = max(5, len(batch_rows) // 3)
            all_translations = {}

            for i in range(0, len(batch_rows), split_size):
                end_idx = min(i + split_size, len(batch_rows))
                sub_batch = batch_rows.iloc[i:end_idx]
                sub_context = f"{context}-split-{i // split_size + 1}"

                logging.info(f"Processing sub-batch {i // split_size + 1} ({len(sub_batch)} records)")
                sub_result = self.translate_batch(sub_batch, file_config, file_name, sub_context)

                if sub_result:
                    all_translations.update(sub_result)
                else:
                    logging.error(f"Sub-batch {i // split_size + 1} also failed")
                    # Mark as errors
                    for _, row in sub_batch.iterrows():
                        record_id = row[file_config['id_field']]
                        error_dict = {
                            f"{field}_{self.lang_code.upper()}": ERROR_BATCH_SPLIT
                            for field in file_config['translation_fields']
                        }
                        all_translations[record_id] = error_dict

                time.sleep(0.5)

            return all_translations

        else:
            logging.error(f"Batch too small to split ({len(batch_rows)} records)")
            error_translations = {}
            for _, row in batch_rows.iterrows():
                record_id = row[file_config['id_field']]
                error_dict = {
                    f"{field}_{self.lang_code.upper()}": ERROR_JSON_PARSE_SMALL_BATCH
                    for field in file_config['translation_fields']
                }
                error_translations[record_id] = error_dict
            return error_translations

    def process_batches_parallel(
        self,
        batch_infos: list[tuple],
        max_workers: int | None = None,
    ) -> dict[int, dict[str, dict[str, str]]]:
        """
        Process multiple batches in parallel.

        Args:
            batch_infos: List of (batch_rows, file_config, file_name, batch_num) tuples
            max_workers: Maximum parallel workers (defaults to self.parallel_workers)

        Returns:
            Dictionary mapping batch numbers to translation results
        """
        if max_workers is None:
            max_workers = min(self.parallel_workers, len(batch_infos))

        logging.info(f"Processing {len(batch_infos)} batches with {max_workers} parallel workers")

        all_results = {}

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_batch = {
                executor.submit(self._parallel_worker, batch_info): batch_info
                for batch_info in batch_infos
            }

            for future in as_completed(future_to_batch):
                batch_info = future_to_batch[future]
                _, _, _, batch_num = batch_info

                try:
                    batch_result = future.result()
                    if batch_result:
                        all_results[batch_num] = batch_result
                        logging.info(f"Parallel batch {batch_num} completed ({len(batch_result)} translations)")
                    else:
                        logging.error(f"Parallel batch {batch_num} failed")
                        all_results[batch_num] = {}

                except Exception as e:
                    logging.error(f"Parallel batch {batch_num} exception: {e}")
                    self.performance_tracker.record_error("PARALLEL_EXCEPTION", f"batch {batch_num}", str(e))
                    all_results[batch_num] = {}

        return all_results

    def _parallel_worker(self, batch_info: tuple) -> dict[str, dict[str, str]]:
        """Worker function for parallel batch processing."""
        batch_rows, file_config, file_name, batch_num = batch_info
        context = f"{file_name} batch {batch_num}"
        return self.translate_with_batch_splitting(batch_rows, file_config, file_name, context)

    def translate_file(
        self,
        df: pd.DataFrame,
        file_config: dict[str, Any],
        file_name: str,
    ) -> dict[str, Any]:
        """
        Process a single taxonomy file.

        Args:
            df: DataFrame containing source data
            file_config: Configuration for the taxonomy file
            file_name: Source file name

        Returns:
            Dictionary with processing results
        """
        logging.info(f"Processing {file_name}: {len(df):,} records")

        # Check for previous progress
        previous_progress = self.progress_manager.load_progress(file_name)

        all_translations: dict[str, dict[str, str]] = {}
        completed_batches = 0
        total_batches = (len(df) + self.batch_size - 1) // self.batch_size

        if previous_progress:
            all_translations = previous_progress.get('translations', {})
            completed_batches = previous_progress['completed_batches']
            logging.info(f"Resuming from batch {completed_batches + 1}")

        # Initialize output file if starting fresh
        output_file = None
        if completed_batches == 0:
            output_file = self.file_processor.save_batch_translations(
                {}, df, file_config, file_name, is_initial_save=True
            )

        # Determine processing mode
        use_parallel = len(df) >= 100 and self.parallel_workers > 1

        if use_parallel:
            self._process_parallel_batches(
                df, file_config, file_name, completed_batches, total_batches, all_translations
            )
        else:
            self._process_sequential_batches(
                df, file_config, file_name, completed_batches, total_batches, all_translations
            )

        # Get final completed batch count
        completed_batches = total_batches  # Assuming completion

        # Apply validation to completed file
        output_file = self.file_processor.find_latest_output_file(file_name)
        review_excel = None
        localized_file = None

        if output_file:
            validation_results = self.file_processor.apply_validation(output_file, file_config)
            self.performance_tracker.record_validation_stats(validation_results)

            # Generate review Excel for human review
            logging.info("Generating review Excel...")
            review_excel = self.file_processor.generate_review_excel(output_file, file_config)

            # Generate localized taxonomy file
            logging.info("Generating localized taxonomy file...")
            localized_file = self.file_processor.generate_localized_files(output_file, file_config, file_name)

        # Cleanup progress file
        self.progress_manager.cleanup_progress(file_name)

        return {
            'file_name': file_name,
            'completed_batches': completed_batches,
            'total_batches': total_batches,
            'completion_rate': (completed_batches / total_batches * 100) if total_batches > 0 else 0,
            'translation_count': len(all_translations),
            'output_file': output_file,
            'review_excel': review_excel,
            'localized_file': localized_file,
        }

    def _process_parallel_batches(
        self,
        df: pd.DataFrame,
        file_config: dict[str, Any],
        file_name: str,
        completed_batches: int,
        total_batches: int,
        all_translations: dict[str, dict[str, str]],
    ) -> None:
        """Process batches using parallel execution."""
        logging.info(f"Using parallel processing ({self.parallel_workers} workers)")

        parallel_groups = []
        batch_group = []

        for batch_num in range(completed_batches, total_batches):
            start_idx = batch_num * self.batch_size
            end_idx = min(start_idx + self.batch_size, len(df))
            batch_rows = df.iloc[start_idx:end_idx]

            batch_info = (batch_rows, file_config, file_name, batch_num + 1)
            batch_group.append(batch_info)

            if len(batch_group) >= self.PARALLEL_BATCH_GROUP_SIZE or batch_num == total_batches - 1:
                parallel_groups.append(batch_group)
                batch_group = []

        for group_idx, batch_group in enumerate(parallel_groups):
            logging.info(f"Processing parallel group {group_idx + 1}/{len(parallel_groups)} ({len(batch_group)} batches)")

            parallel_results = self.process_batches_parallel(batch_group)

            for batch_num, batch_translations in parallel_results.items():
                if batch_translations:
                    self.file_processor.save_batch_translations(
                        batch_translations, df, file_config, file_name, is_initial_save=False
                    )
                    all_translations.update(batch_translations)
                    self.progress_manager.save_progress(
                        file_name, batch_num, total_batches,
                        all_translations, self.performance_tracker.api_calls
                    )
                else:
                    logging.error(f"Batch {batch_num} in parallel group failed")

            logging.info(f"Parallel group {group_idx + 1} completed")
            time.sleep(1)

    def _process_sequential_batches(
        self,
        df: pd.DataFrame,
        file_config: dict[str, Any],
        file_name: str,
        completed_batches: int,
        total_batches: int,
        all_translations: dict[str, dict[str, str]],
    ) -> None:
        """Process batches sequentially."""
        logging.info("Using sequential processing")

        for batch_num in range(completed_batches, total_batches):
            start_idx = batch_num * self.batch_size
            end_idx = min(start_idx + self.batch_size, len(df))
            batch_rows = df.iloc[start_idx:end_idx]

            logging.info(f"Batch {batch_num + 1}/{total_batches} (records {start_idx + 1}-{end_idx})")

            batch_translations = self.translate_with_batch_splitting(
                batch_rows, file_config, file_name, f"sequential {batch_num + 1}"
            )

            if batch_translations:
                self.file_processor.save_batch_translations(
                    batch_translations, df, file_config, file_name, is_initial_save=False
                )
                all_translations.update(batch_translations)
                completed_batches = batch_num + 1

                self.progress_manager.save_progress(
                    file_name, completed_batches, total_batches,
                    all_translations, self.performance_tracker.api_calls
                )

                logging.info(f"Batch {batch_num + 1} completed and saved")
            else:
                logging.error(f"Batch {batch_num + 1} failed - stopping processing")
                self.performance_tracker.record_error("BATCH_FAILED", f"batch {batch_num + 1} of {file_name}")
                break

            if batch_num < total_batches - 1:
                time.sleep(0.2)

    def translate_taxonomy(self, file_filter: str | None = None) -> dict[str, Any]:
        """
        Execute complete taxonomy translation workflow.

        Args:
            file_filter: Optional filter to process specific files

        Returns:
            Dictionary with results for each processed file
        """
        lang_name = self.lang_config['name']
        logging.info(f"Starting complete taxonomy translation to {lang_name}")

        # Load taxonomy files
        loaded_files = self.file_processor.load_taxonomy_files(file_filter)

        if not loaded_files:
            logging.error("No taxonomy files found")
            return {}

        # Calculate workload
        total_records = sum(len(df) for df in loaded_files.values())
        estimated_batches = sum(
            (len(df) + self.batch_size - 1) // self.batch_size
            for df in loaded_files.values()
        )

        logging.info(f"Translation workload: {len(loaded_files)} files, {total_records:,} records, {estimated_batches} batches")

        # Process each file
        results = {}
        for file_name, df in loaded_files.items():
            file_config = TAXONOMY_FILES[file_name]
            results[file_name] = self.translate_file(df, file_config, file_name)

        return results

    def print_summary(self, results: dict[str, Any]) -> None:
        """
        Print comprehensive completion summary.

        Args:
            results: Dictionary of results from translate_taxonomy
        """
        lang_name = self.lang_config['name']
        self.performance_tracker.print_summary(lang_name)

        print("\nTRANSLATION RESULTS:")
        for file_name, file_results in results.items():
            completion_rate = file_results.get('completion_rate', 0)
            completed_batches = file_results.get('completed_batches', 0)
            total_batches = file_results.get('total_batches', 0)

            status = "Complete" if completion_rate == 100 else f"{completion_rate:.1f}% complete"
            print(f"  {file_name}: {status} ({completed_batches}/{total_batches} batches)")

            # Show generated output files
            review_excel = file_results.get('review_excel')
            localized_file = file_results.get('localized_file')
            if review_excel:
                print(f"    -> Review Excel: {os.path.basename(review_excel)}")
            if localized_file:
                print(f"    -> Localized CSV: {os.path.basename(localized_file)}")

        print(f"\nSUMMARY:")
        print(f"  Target language: {lang_name} ({self.lang_code})")
        print(f"  Total files processed: {len(results)}")
        print(f"  Output location: {self.file_processor.output_dir}")
        print(f"  Localized taxonomy: {os.path.join(self.file_processor.output_dir, 'localized')}")
        print(f"  Backup location: {self.file_processor.backup_dir}")
        print(f"  Column suffix: _{self.lang_code.upper()}")
        print("=" * 70)
