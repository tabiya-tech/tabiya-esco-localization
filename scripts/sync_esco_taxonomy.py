"""
Sync Tabiya ESCO Taxonomy CSVs from GitHub

Downloads the latest base model CSV files from the Tabiya taxonomy-model-application
repository and saves them to the shared_data/esco_taxonomy folder.

Usage:
    python scripts/sync_esco_taxonomy.py [--version VERSION]

Arguments:
    --version VERSION    ESCO version to download (default: esco-v1.1.2)
                        Options: esco-v1.1.2, esco-v1.1.2(fr), tabiya-esco-1.1.1/v1.0.0, etc.

Examples:
    python scripts/sync_esco_taxonomy.py
    python scripts/sync_esco_taxonomy.py --version esco-v1.1.2
    python scripts/sync_esco_taxonomy.py --version tabiya-esco-1.1.1/v2.0.1
"""

import argparse
import os
import sys
from pathlib import Path
from urllib import request
from urllib.error import URLError
from urllib.parse import quote
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Default ESCO version (latest Tabiya customized with unseen economy)
DEFAULT_VERSION = "tabiya-esco-1.1.1 v2.0.1"

# GitHub raw content base URL
GITHUB_RAW_BASE = "https://raw.githubusercontent.com/tabiya-tech/taxonomy-model-application/main/data-sets/csv"

# Required CSV files for base model (9-file structure)
REQUIRED_FILES = [
    "model_info.csv",
    "occupation_groups.csv",
    "occupations.csv",
    "occupation_hierarchy.csv",
    "occupation_to_skill_relations.csv",
    "skill_groups.csv",
    "skills.csv",
    "skill_hierarchy.csv",
    "skill_to_skill_relations.csv",
]

# Target directory
PROJECT_ROOT = Path(__file__).parent.parent
TARGET_DIR = PROJECT_ROOT / "shared_data" / "esco_taxonomy"


def download_file(url: str, destination: Path) -> bool:
    """
    Download a file from URL to destination.

    :param url: Source URL
    :param destination: Destination file path
    :return: True if successful, False otherwise
    """
    try:
        logger.info(f"Downloading {destination.name}...")

        # Download file
        with request.urlopen(url, timeout=30) as response:
            content = response.read()

        # Write to destination
        with open(destination, 'wb') as f:
            f.write(content)

        # Verify file size
        file_size_kb = len(content) / 1024
        logger.info(f"✓ Downloaded {destination.name} ({file_size_kb:.1f} KB)")
        return True

    except URLError as e:
        logger.error(f"✗ Failed to download {destination.name}: {e}")
        return False
    except Exception as e:
        logger.error(f"✗ Error saving {destination.name}: {e}")
        return False


def sync_esco_taxonomy(version: str = DEFAULT_VERSION) -> int:
    """
    Sync all ESCO taxonomy CSV files from GitHub.

    :param version: ESCO version directory (e.g., "esco-v1.1.2", "tabiya-esco-1.1.1 v2.0.1")
    :return: 0 if successful, 1 if any errors occurred
    """
    # URL-encode the version (handles spaces and special characters)
    version_encoded = quote(version, safe='')

    # Construct full GitHub URL
    base_url = f"{GITHUB_RAW_BASE}/{version_encoded}"

    # Create target directory if it doesn't exist
    TARGET_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info(f"Syncing ESCO Taxonomy: {version}")
    logger.info(f"Source: {base_url}")
    logger.info(f"Target: {TARGET_DIR}")
    logger.info("=" * 60)

    # Download each file
    success_count = 0
    failed_files = []

    for filename in REQUIRED_FILES:
        url = f"{base_url}/{filename}"
        destination = TARGET_DIR / filename

        if download_file(url, destination):
            success_count += 1
        else:
            failed_files.append(filename)

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info(f"Sync complete: {success_count}/{len(REQUIRED_FILES)} files downloaded")

    if failed_files:
        logger.warning(f"Failed files: {', '.join(failed_files)}")
        logger.warning("\nNote: If files are missing from GitHub, check:")
        logger.warning(f"  {base_url}")
        return 1
    else:
        logger.info("✓ All ESCO taxonomy files successfully synced!")
        logger.info(f"\nFiles saved to: {TARGET_DIR}")

        # Create version marker file
        version_file = TARGET_DIR / "VERSION.txt"
        with open(version_file, 'w') as f:
            f.write(f"{version}\n")
        logger.info(f"Version marker created: {version_file}")

        return 0


def main():
    """Main entry point with argument parsing."""
    parser = argparse.ArgumentParser(
        description="Sync Tabiya ESCO Taxonomy CSVs from GitHub",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Download base ESCO v1.1.2 (default)
  python scripts/sync_esco_taxonomy.py

  # Download French ESCO
  python scripts/sync_esco_taxonomy.py --version esco-v1.1.2(fr)

  # Download Tabiya customized version
  python scripts/sync_esco_taxonomy.py --version tabiya-esco-1.1.1/v2.0.1

Available versions in GitHub:
  - esco-v1.1.2 (base ESCO, English)
  - esco-v1.1.2(fr) (base ESCO, French)
  - tabiya-esco-1.1.1 v1.0.0, v1.0.1, v2.0.0, v2.0.1 (note: space in name)
  - tabiya-sa v1.0.0, v1.0.1
        """
    )

    parser.add_argument(
        '--version',
        type=str,
        default=DEFAULT_VERSION,
        help=f'ESCO version to download (default: {DEFAULT_VERSION})'
    )

    args = parser.parse_args()

    exit_code = sync_esco_taxonomy(args.version)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
