"""
File I/O operations for taxonomy translation.
"""

import glob
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .config import TAXONOMY_FILES, LanguageConfig
from .output_generators import LocalizedTaxonomyGenerator, ReviewExcelGenerator
from .validation import ValidationFixes


class FileProcessor:
    """Handle file I/O operations for taxonomy translation."""

    ENCODING = 'utf-8-sig'

    def __init__(self, lang_code: str, output_dir: str, source_dir: str):
        """
        Initialize file processor.

        Args:
            lang_code: Target language code
            output_dir: Base output directory
            source_dir: Directory containing source taxonomy files
        """
        self.lang_code = lang_code.upper()
        self.output_dir = str(Path(output_dir) / lang_code.lower())
        self.backup_dir = str(Path(output_dir) / lang_code.lower() / 'backup')
        self.source_dir = str(Path(source_dir))

        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        Path(self.backup_dir).mkdir(parents=True, exist_ok=True)

    def create_backup(self, file_path: str, reason: str = "validation") -> str | None:
        """
        Create a backup of a file before applying fixes.

        Args:
            file_path: Path to file to backup
            reason: Reason for backup (used in filename)

        Returns:
            Path to backup file or None on failure
        """
        if not Path(file_path).exists():
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = Path(file_path).name
        backup_name = f"{file_name.replace('.csv', '')}_{reason}_{timestamp}.csv"
        backup_path = str(Path(self.backup_dir) / backup_name)

        try:
            df = pd.read_csv(file_path, encoding=self.ENCODING)
            df.to_csv(backup_path, index=False, encoding=self.ENCODING)
            logging.info(f"Backup created: {backup_name}")
            return backup_path
        except Exception as e:
            logging.error(f"Could not create backup: {e}")
            return None

    def load_taxonomy_files(self, file_filter: str | None = None) -> dict[str, pd.DataFrame]:
        """
        Load taxonomy files from source directory.

        Args:
            file_filter: Optional filter string to match specific files

        Returns:
            Dictionary mapping file names to DataFrames
        """
        loaded_files = {}

        for file_name, config in TAXONOMY_FILES.items():
            file_path = Path(self.source_dir) / file_name

            # Apply filter if specified
            if file_filter and file_filter.lower() not in file_name.lower():
                continue

            try:
                if file_path.exists():
                    df = pd.read_csv(str(file_path), encoding=self.ENCODING)
                    loaded_files[file_name] = df
                    logging.info(f"Loaded {file_name}: {len(df):,} records")
                    self._analyze_file_structure(df, config, file_name)
                else:
                    logging.warning(f"{file_name}: File not found at {file_path}")

            except Exception as e:
                logging.error(f"Error loading {file_name}: {e}")

        return loaded_files

    def _analyze_file_structure(
        self, df: pd.DataFrame, file_config: dict[str, Any], file_name: str
    ) -> None:
        """Analyze and log file structure information."""
        total_records = len(df)
        translation_fields = file_config['translation_fields']

        for field in translation_fields:
            if field in df.columns:
                content_count = df[field].apply(lambda x: pd.notna(x) and str(x).strip() != '').sum()
                percentage = (content_count / total_records * 100) if total_records > 0 else 0
                logging.info(f"  {field}: {content_count:,} records ({percentage:.1f}%)")
            else:
                logging.info(f"  {field}: Not present in file")

    def get_output_file_path(self, source_file_name: str, timestamp: str | None = None) -> str:
        """
        Get output file path for translated file.

        Args:
            source_file_name: Original source file name
            timestamp: Optional timestamp (generated if not provided)

        Returns:
            Full path to output file
        """
        if timestamp is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        base_name = source_file_name.replace('.csv', '')
        return str(Path(self.output_dir) / f"{base_name}_translated_{self.lang_code.lower()}_{timestamp}.csv")

    def find_latest_output_file(self, source_file_name: str) -> str | None:
        """
        Find the most recent output file for a source file.

        Args:
            source_file_name: Original source file name

        Returns:
            Path to latest output file or None if not found
        """
        base_name = source_file_name.replace('.csv', '')
        pattern = str(Path(self.output_dir) / f"{base_name}_translated_{self.lang_code.lower()}_*.csv")
        existing_files = glob.glob(pattern)

        if existing_files:
            return str(Path(max(existing_files, key=os.path.getctime)))
        return None

    def save_batch_translations(
        self,
        batch_translations: dict[str, dict[str, str]],
        original_df: pd.DataFrame,
        file_config: dict[str, Any],
        file_name: str,
        is_initial_save: bool = False,
        output_file: str | None = None,
    ) -> str | None:
        """
        Save translated batch to output file.

        Args:
            batch_translations: Dictionary mapping record IDs to translated fields
            original_df: Original DataFrame with source data
            file_config: Configuration for the taxonomy file
            file_name: Source file name
            is_initial_save: Whether this is the first save (creates new file)
            output_file: Specific output file path (auto-detected if not provided)

        Returns:
            Path to output file or None on failure
        """
        if not batch_translations:
            return None

        try:
            # Determine output file
            if output_file is None:
                if is_initial_save:
                    output_file = self.get_output_file_path(file_name)
                else:
                    output_file = self.find_latest_output_file(file_name)
                    if output_file is None:
                        output_file = self.get_output_file_path(file_name)
                        is_initial_save = True

            id_field = file_config['id_field']
            translation_fields = file_config['translation_fields']

            # Get batch records from original
            batch_ids = list(batch_translations.keys())
            batch_mask = original_df[id_field].isin(batch_ids)
            batch_df = original_df[batch_mask].copy()

            # Add translated columns
            for field in translation_fields:
                target_field_name = f"{field}_{self.lang_code}"
                batch_df[target_field_name] = ''

            # Fill in translations
            for record_id, field_translations in batch_translations.items():
                mask = batch_df[id_field] == record_id
                for target_field, translation in field_translations.items():
                    if target_field in batch_df.columns:
                        batch_df.loc[mask, target_field] = translation

            # Save to file
            file_exists = os.path.exists(output_file)
            batch_df.to_csv(
                output_file,
                mode='w' if is_initial_save else 'a',
                header=True if is_initial_save or not file_exists else False,
                index=False,
                encoding=self.ENCODING,
            )

            if is_initial_save:
                logging.info(f"Created output file: {output_file}")
            else:
                logging.info(f"Appended batch to: {os.path.basename(output_file)}")

            return output_file

        except Exception as e:
            logging.error(f"Error saving batch to file: {e}")
            return None

    def apply_validation(
        self,
        output_file: str,
        file_config: dict[str, Any],
    ) -> dict[str, int]:
        """
        Apply validation fixes to completed output file.

        Args:
            output_file: Path to output file
            file_config: Configuration for the taxonomy file

        Returns:
            Dictionary of validation results
        """
        if not os.path.exists(output_file):
            logging.error(f"Output file not found: {output_file}")
            return {}

        logging.info(f"\n{'=' * 70}")
        logging.info(f"Applying validation to: {os.path.basename(output_file)}")
        logging.info(f"{'=' * 70}")

        # Create backup before validation
        self.create_backup(output_file, "pre_validation")

        # Load file
        try:
            df = pd.read_csv(output_file, encoding=self.ENCODING)
        except Exception:
            df = pd.read_csv(output_file, encoding='utf-8')

        # Apply all validation fixes
        validation_results = ValidationFixes.apply_all_validations(df, self.lang_code.lower())

        # Save updated file
        df.to_csv(output_file, index=False, encoding=self.ENCODING)
        logging.info("Validation applied and file saved")

        return validation_results

    def merge_output_files(self, source_file_name: str) -> str | None:
        """
        Merge multiple output files for same source into single file.
        Useful after parallel processing creates multiple partial files.

        Args:
            source_file_name: Original source file name

        Returns:
            Path to merged file or None if no files found
        """
        base_name = source_file_name.replace('.csv', '')
        pattern = str(Path(self.output_dir) / f"{base_name}_translated_{self.lang_code.lower()}_*.csv")
        output_files = sorted(glob.glob(pattern), key=os.path.getctime)

        if not output_files:
            return None

        if len(output_files) == 1:
            return str(Path(output_files[0]))

        # Merge all files
        dfs = []
        for file_path in output_files:
            try:
                df = pd.read_csv(file_path, encoding=self.ENCODING)
                dfs.append(df)
            except Exception as e:
                logging.warning(f"Could not read {file_path}: {e}")

        if not dfs:
            return None

        merged_df = pd.concat(dfs, ignore_index=True)

        # Remove duplicates based on ID field
        id_field = 'ORIGINURI'
        if id_field in merged_df.columns:
            merged_df = merged_df.drop_duplicates(subset=[id_field], keep='last')

        # Save merged file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        merged_path = str(Path(self.output_dir) / f"{base_name}_translated_{self.lang_code.lower()}_merged_{timestamp}.csv")
        merged_df.to_csv(merged_path, index=False, encoding=self.ENCODING)

        logging.info(f"Merged {len(output_files)} files into: {Path(merged_path).name}")
        return merged_path

    def generate_review_excel(
        self,
        translated_csv: str,
        file_config: dict[str, Any],
    ) -> str | None:
        """
        Generate review Excel file with side-by-side English and translated columns.

        Args:
            translated_csv: Path to translated CSV file
            file_config: Configuration for the taxonomy file

        Returns:
            Path to generated Excel file, or None on failure
        """
        generator = ReviewExcelGenerator(self.lang_code, self.output_dir)
        return generator.generate(translated_csv, file_config)

    def generate_localized_files(
        self,
        translated_csv: str,
        file_config: dict[str, Any],
        file_name: str,
    ) -> str | None:
        """
        Generate localized taxonomy CSV matching source structure.

        Args:
            translated_csv: Path to translated CSV file
            file_config: Configuration for the taxonomy file
            file_name: Original source file name (e.g., 'occupations.csv')

        Returns:
            Path to generated localized CSV, or None on failure
        """
        generator = LocalizedTaxonomyGenerator(self.lang_code, self.output_dir, self.source_dir)
        return generator.generate(translated_csv, file_config, file_name)
