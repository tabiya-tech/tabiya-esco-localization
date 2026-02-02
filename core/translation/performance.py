"""
Performance tracking for translation metrics.
"""

from datetime import datetime
from threading import Lock
from typing import Any


class PerformanceTracker:
    """Track translation performance metrics including API calls, tokens, and timing."""

    def __init__(self):
        """Initialize the performance tracker."""
        self.api_calls = 0
        self.total_tokens_estimated = 0
        self.start_time = datetime.now()
        self.validation_stats: dict[str, int] = {}
        self.errors: list[dict[str, Any]] = []
        self.lock = Lock()

    def record_api_call(self, estimated_tokens: int) -> None:
        """
        Record an API call with estimated token count.

        Args:
            estimated_tokens: Estimated number of tokens in the request
        """
        with self.lock:
            self.api_calls += 1
            self.total_tokens_estimated += estimated_tokens

    def record_error(self, error_type: str, context: str, details: str = "") -> None:
        """
        Record an error that occurred during processing.

        Args:
            error_type: Type of error (e.g., 'API_ERROR', 'JSON_PARSE')
            context: Context where error occurred (e.g., 'batch 5 of occupations.csv')
            details: Additional error details
        """
        with self.lock:
            self.errors.append({
                'timestamp': datetime.now().isoformat(),
                'type': error_type,
                'context': context,
                'details': details,
            })

    def record_validation_stats(self, stats: dict[str, int]) -> None:
        """
        Record validation statistics.

        Args:
            stats: Dictionary of validation stat names to counts
        """
        with self.lock:
            for key, value in stats.items():
                self.validation_stats[key] = self.validation_stats.get(key, 0) + value

    def get_duration_seconds(self) -> float:
        """
        Get elapsed time since tracking started.

        Returns:
            Duration in seconds
        """
        return (datetime.now() - self.start_time).total_seconds()

    def get_summary(self) -> dict[str, Any]:
        """
        Get comprehensive performance summary.

        Returns:
            Dictionary containing all tracked metrics
        """
        duration = self.get_duration_seconds()
        return {
            'duration_seconds': duration,
            'duration_minutes': duration / 60,
            'api_calls': self.api_calls,
            'estimated_tokens': self.total_tokens_estimated,
            'average_call_duration': duration / max(1, self.api_calls),
            'validation_stats': self.validation_stats.copy(),
            'error_count': len(self.errors),
            'errors': self.errors.copy(),
        }

    def print_summary(self, lang_name: str = "Unknown") -> None:
        """
        Print a formatted performance summary.

        Args:
            lang_name: Name of target language for display
        """
        summary = self.get_summary()

        print(f"\nTRANSLATION TO {lang_name.upper()} COMPLETED!")
        print("=" * 70)

        print("PERFORMANCE METRICS:")
        print(f"  Processing time: {summary['duration_seconds']:.1f} seconds ({summary['duration_minutes']:.1f} minutes)")
        print(f"  API calls made: {summary['api_calls']:,}")
        print(f"  Estimated tokens: {summary['estimated_tokens']:,}")
        print(f"  Average per call: {summary['average_call_duration']:.1f}s")

        print("\nVALIDATION RESULTS:")
        if summary['validation_stats']:
            for stat_name, count in summary['validation_stats'].items():
                print(f"  {stat_name}: {count}")
        else:
            print("  No validation issues found")

        if summary['error_count'] > 0:
            print(f"\nERRORS ({summary['error_count']} total):")
            for error in summary['errors'][:5]:  # Show first 5
                print(f"  [{error['type']}] {error['context']}")
            if summary['error_count'] > 5:
                print(f"  ... and {summary['error_count'] - 5} more")

        print("=" * 70)
