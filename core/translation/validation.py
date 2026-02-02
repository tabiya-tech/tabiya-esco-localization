"""
Validation and error fixing utilities for translated taxonomy files.
"""

import logging
from typing import Any

import pandas as pd


# Error constants
ERROR_BATCH_SPLIT = "BATCH_SPLIT_ERROR"
ERROR_JSON_PARSE_SMALL_BATCH = "JSON_PARSE_ERROR_SMALL_BATCH"
ERROR_GEMINI_EMPTY = "GEMINI_EMPTY_RESPONSE"
ERROR_TIMEOUT_MAX_RETRIES = "TIMEOUT_ERROR_MAX_RETRIES"
ERROR_QUOTA = "QUOTA_ERROR"
ERROR_GEMINI = "GEMINI_ERROR"
ERROR_PATTERNS = ['ERROR', 'JSON_', 'PARSE_', 'GEMINI_', 'TIMEOUT_']


class ValidationFixes:
    """
    Modular validation and error fixing system for translated taxonomy files.
    Add new validation rules and fixes here as they're identified.
    """

    @staticmethod
    def replace_empty_markers(df: pd.DataFrame, marker: str = "[EMPTY]") -> int:
        """
        Replace all instances of empty markers with empty strings.

        Args:
            df: DataFrame to process
            marker: The marker string to replace (default: [EMPTY])

        Returns:
            Count of replacements made
        """
        replacement_count = 0
        marker_pattern = marker.replace('[', r'\[').replace(']', r'\]')

        for col in df.columns:
            if df[col].dtype == 'object':
                mask = df[col].astype(str).str.contains(marker_pattern, case=False, na=False, regex=True)
                count = mask.sum()
                if count > 0:
                    df.loc[mask, col] = df.loc[mask, col].astype(str).str.replace(
                        marker_pattern, '', case=False, regex=True
                    )
                    replacement_count += count
                    logging.info(f"  Replaced {marker} in {count} cells in column {col}")

        return replacement_count

    @staticmethod
    def flag_duplicate_altlabels(df: pd.DataFrame, lang_code: str) -> int:
        """
        Flag rows with duplicate lines in ALTLABELS_[LANG].

        Args:
            df: DataFrame to process
            lang_code: Language code (e.g., 'sw', 'es')

        Returns:
            Count of rows flagged
        """
        altlabels_col = f'ALTLABELS_{lang_code.upper()}'
        flag_col = f'HAS_DUPLICATE_ALTLABELS_{lang_code.upper()}'

        if altlabels_col not in df.columns:
            logging.info(f"  No {altlabels_col} column found")
            return 0

        if flag_col not in df.columns:
            df[flag_col] = False

        duplicate_count = 0

        for idx, row in df.iterrows():
            altlabels = row.get(altlabels_col, '')

            if pd.notna(altlabels) and str(altlabels).strip():
                labels = [label.strip() for label in str(altlabels).split('\n') if label.strip()]
                unique_labels = list(set(labels))

                if len(labels) != len(unique_labels):
                    df.at[idx, flag_col] = True
                    duplicate_count += 1

        logging.info(f"  Flagged {duplicate_count} rows with duplicate ALTLABELS")
        return duplicate_count

    @staticmethod
    def fix_duplicate_altlabels(df: pd.DataFrame, lang_code: str) -> int:
        """
        Remove duplicate lines from ALTLABELS_[LANG], preserving order.

        Args:
            df: DataFrame to process (modified in place)
            lang_code: Language code (e.g., 'sw', 'es')

        Returns:
            Count of rows fixed
        """
        altlabels_col = f'ALTLABELS_{lang_code.upper()}'

        if altlabels_col not in df.columns:
            logging.info(f"  No {altlabels_col} column found")
            return 0

        fixed_count = 0

        for idx, row in df.iterrows():
            altlabels = row.get(altlabels_col, '')

            if pd.notna(altlabels) and str(altlabels).strip():
                labels = str(altlabels).split('\n')
                seen = set()
                unique_labels = []

                for label in labels:
                    label_clean = label.strip()
                    label_lower = label_clean.lower()
                    if label_clean and label_lower not in seen:
                        seen.add(label_lower)
                        unique_labels.append(label_clean)

                if len(labels) != len(unique_labels):
                    df.at[idx, altlabels_col] = '\n'.join(unique_labels)
                    fixed_count += 1

        if fixed_count > 0:
            logging.info(f"  Deduplicated ALTLABELS in {fixed_count} rows")

        return fixed_count

    @staticmethod
    def check_batch_errors(df: pd.DataFrame, lang_code: str) -> list[str]:
        """
        Identify rows with batch processing errors.

        Args:
            df: DataFrame to check
            lang_code: Language code

        Returns:
            List of IDs with errors
        """
        error_ids = []
        lang_suffix = lang_code.upper()

        for idx, row in df.iterrows():
            for col in df.columns:
                if col.endswith(f'_{lang_suffix}'):
                    value = str(row[col])
                    if 'BATCH_SPLIT_ERROR' in value or any(err in value for err in ERROR_PATTERNS):
                        error_ids.append(row.get('ORIGINURI', idx))
                        break

        if error_ids:
            logging.warning(f"  Found {len(error_ids)} rows with batch errors")

        return error_ids

    @staticmethod
    def check_preferredlabel_in_altlabels(df: pd.DataFrame, lang_code: str) -> int:
        """
        Flag when PREFERREDLABEL doesn't appear in ALTLABELS.
        This validates the consistency requirement from the prompt.

        Args:
            df: DataFrame to check
            lang_code: Language code

        Returns:
            Count of inconsistencies found
        """
        preferred_col = f'PREFERREDLABEL_{lang_code.upper()}'
        altlabels_col = f'ALTLABELS_{lang_code.upper()}'
        flag_col = f'PREFERREDLABEL_NOT_IN_ALTLABELS_{lang_code.upper()}'

        if preferred_col not in df.columns or altlabels_col not in df.columns:
            return 0

        if flag_col not in df.columns:
            df[flag_col] = False

        inconsistency_count = 0

        for idx, row in df.iterrows():
            preferred = row.get(preferred_col, '')
            altlabels = row.get(altlabels_col, '')

            if pd.notna(preferred) and pd.notna(altlabels) and str(preferred).strip() and str(altlabels).strip():
                preferred_lower = str(preferred).lower().strip()
                altlabels_list = [label.strip().lower() for label in str(altlabels).split('\n') if label.strip()]

                if preferred_lower not in altlabels_list:
                    df.at[idx, flag_col] = True
                    inconsistency_count += 1
                    logging.debug(f"  ORIGINURI {row.get('ORIGINURI', idx)}: PREFERREDLABEL not in ALTLABELS")

        if inconsistency_count > 0:
            logging.warning(f"  Flagged {inconsistency_count} rows where PREFERREDLABEL not in ALTLABELS")

        return inconsistency_count

    @staticmethod
    def fix_preferred_in_altlabels(df: pd.DataFrame, lang_code: str) -> int:
        """
        Ensure PREFERREDLABEL appears in ALTLABELS by prepending if missing.

        Args:
            df: DataFrame to process (modified in place)
            lang_code: Language code

        Returns:
            Count of rows fixed
        """
        preferred_col = f'PREFERREDLABEL_{lang_code.upper()}'
        altlabels_col = f'ALTLABELS_{lang_code.upper()}'

        if preferred_col not in df.columns or altlabels_col not in df.columns:
            return 0

        fixed_count = 0

        for idx, row in df.iterrows():
            preferred = row.get(preferred_col, '')
            altlabels = row.get(altlabels_col, '')

            if pd.isna(preferred) or not str(preferred).strip():
                continue

            preferred_clean = str(preferred).strip()
            preferred_lower = preferred_clean.lower()

            if pd.isna(altlabels) or not str(altlabels).strip():
                # No altlabels - set to preferred
                df.at[idx, altlabels_col] = preferred_clean
                fixed_count += 1
            else:
                altlabels_str = str(altlabels)
                alt_list_lower = [a.strip().lower() for a in altlabels_str.split('\n') if a.strip()]

                if preferred_lower not in alt_list_lower:
                    # Prepend preferred to altlabels
                    df.at[idx, altlabels_col] = preferred_clean + '\n' + altlabels_str
                    fixed_count += 1

        if fixed_count > 0:
            logging.info(f"  Added PREFERREDLABEL to ALTLABELS in {fixed_count} rows")

        return fixed_count

    @staticmethod
    def check_truncated_translations(df: pd.DataFrame, lang_code: str, min_ratio: float = 0.3) -> int:
        """
        Flag translations that appear truncated (much shorter than source).

        Args:
            df: DataFrame to check
            lang_code: Language code
            min_ratio: Minimum acceptable length ratio (translated/source)

        Returns:
            Count of potentially truncated translations
        """
        flag_col = f'POSSIBLY_TRUNCATED_{lang_code.upper()}'
        if flag_col not in df.columns:
            df[flag_col] = False

        truncated_count = 0
        fields_to_check = ['DESCRIPTION', 'DEFINITION', 'SCOPENOTE']

        for field in fields_to_check:
            source_col = field
            translated_col = f'{field}_{lang_code.upper()}'

            if source_col not in df.columns or translated_col not in df.columns:
                continue

            for idx, row in df.iterrows():
                source = str(row.get(source_col, ''))
                translated = str(row.get(translated_col, ''))

                if len(source) > 100 and len(translated) > 0:
                    ratio = len(translated) / len(source)
                    if ratio < min_ratio:
                        df.at[idx, flag_col] = True
                        truncated_count += 1
                        logging.debug(f"  ORIGINURI {row.get('ORIGINURI', idx)}: {field} may be truncated (ratio: {ratio:.2f})")

        if truncated_count > 0:
            logging.warning(f"  Flagged {truncated_count} potentially truncated translations")

        return truncated_count

    @classmethod
    def apply_all_validations(
        cls,
        df: pd.DataFrame,
        lang_code: str,
        fix_issues: bool = True,
    ) -> dict[str, int]:
        """
        Apply all validation fixes to a dataframe.

        Args:
            df: DataFrame to validate
            lang_code: Language code
            fix_issues: If True, auto-fix issues. If False, only flag them.

        Returns:
            Dictionary of validation names and counts
        """
        logging.info(f"\nApplying validation for {lang_code.upper()} (fix_issues={fix_issues})...")

        results = {}

        # Fix #1: Replace empty markers
        results['empty_markers_replaced'] = cls.replace_empty_markers(df)

        # Fix #2: Handle duplicate ALTLABELS
        if fix_issues:
            results['duplicates_fixed'] = cls.fix_duplicate_altlabels(df, lang_code)
        else:
            results['duplicates_flagged'] = cls.flag_duplicate_altlabels(df, lang_code)

        # Fix #3: Check for batch errors (always report, cannot auto-fix)
        error_ids = cls.check_batch_errors(df, lang_code)
        results['batch_errors_found'] = len(error_ids)

        # Fix #4: Handle PREFERREDLABEL in ALTLABELS
        if fix_issues:
            results['preferredlabel_fixed'] = cls.fix_preferred_in_altlabels(df, lang_code)
        else:
            results['preferredlabel_inconsistencies'] = cls.check_preferredlabel_in_altlabels(df, lang_code)

        # Log summary
        total_issues = sum(results.values())
        if total_issues > 0:
            logging.info(f"Validation complete: {total_issues} issues found/fixed")
            for fix_name, count in results.items():
                if count > 0:
                    logging.info(f"  - {fix_name}: {count}")
        else:
            logging.info("Validation complete: No issues found")

        return results
