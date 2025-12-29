"""
Populate CNO hierarchy (major + minor) for review_items from Excel.

Usage:
    python populate_cno_hierarchy.py
"""

import os
import pandas as pd
from pathlib import Path
from supabase import create_client
from dotenv import load_dotenv

# Load env from project root
load_dotenv(Path(__file__).parent.parent.parent / '.env')

SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")

EXCEL_PATH = Path(__file__).parent.parent.parent / "countries" / "argentina_cno2017" / "data" / "cno2017_extracted.xlsx"


def extract_minor_code(occupation_code: str) -> str:
    """Extract minor code (XX.X.X) from occupation code (XX.X.X.X.XX.XXX)."""
    parts = occupation_code.split(".")
    if len(parts) >= 3:
        return f"{parts[0]}.{parts[1]}.{parts[2]}"
    return ""


def main():
    print(f"Reading CNO hierarchy from: {EXCEL_PATH}")

    # Read Excel
    df = pd.read_excel(EXCEL_PATH)
    print(f"Loaded {len(df)} occupation records")

    # Build lookup maps
    # Major: occupation_code -> (major_code, major_title)
    # Minor: occupation_code -> (minor_code, minor_title)
    occupation_to_major = {}
    occupation_to_minor = {}

    for _, row in df.iterrows():
        occ_code = str(row["occupation_code"])
        major_code = str(row["major_code"]).zfill(2)  # Pad to 2 digits
        major_title = str(row["major_title_es"])
        minor_code = str(row["minor_code"])
        minor_title = str(row["minor_title_es"])

        occupation_to_major[occ_code] = (major_code, major_title)
        occupation_to_minor[occ_code] = (minor_code, minor_title)

    print(f"Built lookup for {len(occupation_to_major)} occupations")

    # Connect to Supabase
    db = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Get all review items
    result = db.table("review_items").select("id, local_code").execute()
    items = result.data
    print(f"Found {len(items)} review items")

    # Update each item
    updated = 0
    not_found = 0
    for item in items:
        local_code = item["local_code"]

        if local_code in occupation_to_major:
            major_code, major_title = occupation_to_major[local_code]
            minor_code, minor_title = occupation_to_minor[local_code]

            db.table("review_items").update({
                "cno_major_code": major_code,
                "cno_major_title": major_title,
                "cno_minor_code": minor_code,
                "cno_minor_title": minor_title
            }).eq("id", item["id"]).execute()
            updated += 1
        else:
            not_found += 1
            print(f"  No CNO hierarchy for: {local_code}")

    print(f"\nDone! Updated {updated} items, {not_found} not found in CNO hierarchy")


if __name__ == "__main__":
    main()
