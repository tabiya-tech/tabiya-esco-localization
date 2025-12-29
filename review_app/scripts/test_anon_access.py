"""Test anon key access to review tables."""

import os
from pathlib import Path
from supabase import create_client
from dotenv import load_dotenv

# Load env from project root
load_dotenv(Path(__file__).parent.parent.parent / '.env')

SUPABASE_URL = os.environ.get('SUPABASE_URL')
ANON_KEY = os.environ.get('SUPABASE_ANON_KEY')

if not SUPABASE_URL or not ANON_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_ANON_KEY must be set in .env")

supabase = create_client(SUPABASE_URL, ANON_KEY)

print("Testing anon key access...")

try:
    result = supabase.table("review_projects").select("*").execute()
    print(f"review_projects: {len(result.data)} rows")
    for p in result.data:
        print(f"  - {p['name']} ({p['country_code']})")
except Exception as e:
    print(f"ERROR reading review_projects: {e}")

try:
    result = supabase.table("review_items").select("id", count="exact").limit(1).execute()
    print(f"review_items: {result.count} rows")
except Exception as e:
    print(f"ERROR reading review_items: {e}")
