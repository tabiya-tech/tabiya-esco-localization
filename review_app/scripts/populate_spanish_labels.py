"""
Populate Spanish labels for occupation_groups from CSV.

Usage:
    python populate_spanish_labels.py
"""

import os
import csv
from pathlib import Path
from supabase import create_client
from dotenv import load_dotenv

# Load env from project root
load_dotenv(Path(__file__).parent.parent.parent / '.env')

SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")

CSV_PATH = Path(__file__).parent.parent.parent / "shared_data" / "esco_taxonomy_es" / "occupation_groups.csv"


def main():
    print(f"Reading Spanish labels from: {CSV_PATH}")

    # Read CSV
    spanish_labels = {}
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row.get("CODE") or row.get("code")
            label = row.get("PREFERREDLABEL") or row.get("preferredLabel") or row.get("preferred_label")
            if code and label:
                spanish_labels[code] = label

    print(f"Found {len(spanish_labels)} Spanish labels")

    # Connect to Supabase
    db = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Get all occupation groups
    result = db.table("occupation_groups").select("id, code").execute()
    groups = result.data
    print(f"Found {len(groups)} occupation groups in database")

    # Update each group
    updated = 0
    missing = 0
    for group in groups:
        code = group["code"]
        if code in spanish_labels:
            db.table("occupation_groups").update({
                "preferred_label_es": spanish_labels[code]
            }).eq("id", group["id"]).execute()
            updated += 1
        else:
            missing += 1
            print(f"  No Spanish label for: {code}")

    print(f"\nDone! Updated {updated} groups, {missing} missing Spanish labels")


if __name__ == "__main__":
    main()
