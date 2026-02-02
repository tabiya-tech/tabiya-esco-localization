"""
Progress management for translation checkpointing and resumption.
"""

import json
import logging
import os
from datetime import datetime
from typing import Any


class ProgressManager:
    """Manage translation progress persistence for resumption after interruptions."""

    def __init__(self, lang_code: str, output_dir: str):
        """
        Initialize progress manager.

        Args:
            lang_code: Target language code
            output_dir: Base output directory
        """
        self.lang_code = lang_code
        self.progress_dir = os.path.join(output_dir, 'progress', lang_code)
        os.makedirs(self.progress_dir, exist_ok=True)

    def get_progress_file_path(self, file_name: str) -> str:
        """
        Get progress file path for given source file.

        Args:
            file_name: Source taxonomy file name (e.g., 'occupations.csv')

        Returns:
            Full path to progress JSON file
        """
        base_name = file_name.replace('.csv', '')
        return os.path.join(self.progress_dir, f"{base_name}_progress.json")

    def save_progress(
        self,
        file_name: str,
        completed_batches: int,
        total_batches: int,
        translations: dict[str, Any],
        api_calls: int,
    ) -> None:
        """
        Save current translation progress.

        Args:
            file_name: Source file being processed
            completed_batches: Number of completed batches
            total_batches: Total number of batches
            translations: Dictionary of completed translations
            api_calls: Number of API calls made
        """
        try:
            progress_file = self.get_progress_file_path(file_name)
            progress_data = {
                'file_name': file_name,
                'language_code': self.lang_code,
                'completed_batches': completed_batches,
                'total_batches': total_batches,
                'last_update': datetime.now().isoformat(),
                'translation_count': len(translations),
                'api_calls': api_calls,
                'translations': translations,
            }

            with open(progress_file, 'w', encoding='utf-8') as f:
                json.dump(progress_data, f, indent=2, ensure_ascii=False)

            logging.info(f"Progress saved: {completed_batches}/{total_batches} batches")

        except Exception as e:
            logging.error(f"Could not save progress: {e}")

    def load_progress(self, file_name: str) -> dict[str, Any] | None:
        """
        Load previous translation progress.

        Args:
            file_name: Source file to check for progress

        Returns:
            Progress data dictionary or None if no progress found
        """
        try:
            progress_file = self.get_progress_file_path(file_name)

            if os.path.exists(progress_file):
                with open(progress_file, 'r', encoding='utf-8') as f:
                    progress_data = json.load(f)

                logging.info(
                    f"Found previous progress: {progress_data['completed_batches']}/{progress_data['total_batches']} batches"
                )
                return progress_data

        except Exception as e:
            logging.error(f"Could not load progress: {e}")

        return None

    def cleanup_progress(self, file_name: str) -> None:
        """
        Remove progress file after successful completion.

        Args:
            file_name: Source file whose progress to clean up
        """
        try:
            progress_file = self.get_progress_file_path(file_name)
            if os.path.exists(progress_file):
                os.remove(progress_file)
                logging.info("Progress file cleaned up")
        except Exception as e:
            logging.error(f"Could not cleanup progress: {e}")

    def get_all_in_progress(self) -> list[dict[str, Any]]:
        """
        Get all files currently in progress.

        Returns:
            List of progress data for all incomplete translations
        """
        in_progress = []

        if not os.path.exists(self.progress_dir):
            return in_progress

        for filename in os.listdir(self.progress_dir):
            if filename.endswith('_progress.json'):
                try:
                    with open(os.path.join(self.progress_dir, filename), 'r', encoding='utf-8') as f:
                        progress_data = json.load(f)
                        if progress_data['completed_batches'] < progress_data['total_batches']:
                            in_progress.append(progress_data)
                except Exception as e:
                    logging.warning(f"Could not read progress file {filename}: {e}")

        return in_progress
