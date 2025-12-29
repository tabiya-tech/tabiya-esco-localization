"""Clear project data from Supabase."""

import os
from pathlib import Path
from supabase import create_client
from dotenv import load_dotenv

# Load env from project root
load_dotenv(Path(__file__).parent.parent.parent / '.env')

SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Delete all review items for Argentina (country_code = AR)
result = supabase.table("review_items").delete().neq("id", 0).execute()
print(f"Cleared {len(result.data)} items")

# Delete Argentina project
result = supabase.table("review_projects").delete().eq("country_code", "AR").execute()
print(f"Cleared {len(result.data)} projects")
