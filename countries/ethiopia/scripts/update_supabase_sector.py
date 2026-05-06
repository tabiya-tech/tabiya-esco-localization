"""
One-shot: update sector + sub_sector on existing Ethiopia review_items in Supabase.

Use after running review_app/sql/06_add_sector_columns.sql once.
Reads the canonical JSON and writes sector/sub_sector to matching rows by local_code.
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

ROOT = Path(__file__).parent.parent.parent.parent
load_dotenv(ROOT / ".env")

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
COUNTRY_CODE = "ET"
JSON_PATH = ROOT / "countries" / "ethiopia" / "outputs" / "ethiopia_elmis_review_items.json"


def main():
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    proj = sb.table("review_projects").select("id, name").eq("country_code", COUNTRY_CODE).execute()
    if not proj.data:
        raise SystemExit(f"No project with country_code={COUNTRY_CODE}")
    project_id = proj.data[0]["id"]
    print(f"Project: id={project_id} ({proj.data[0]['name']})")

    with open(JSON_PATH, encoding="utf-8") as f:
        items = json.load(f)["items"]
    print(f"Loaded {len(items)} items from JSON")

    updated = 0
    for it in items:
        sb.table("review_items").update({
            "sector": it.get("sector") or None,
            "sub_sector": it.get("sub_sector") or None,
        }).eq("project_id", project_id).eq("local_code", it["elmis_code"]).execute()
        updated += 1
        if updated % 100 == 0:
            print(f"  Updated {updated}/{len(items)}")
    print(f"Done. Updated {updated} rows.")


if __name__ == "__main__":
    main()
