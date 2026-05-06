# Taxonomy Review Tool

A lightweight web app for reviewing occupation matches across ESCO localizations.

## Features

- Multi-project support (auto-discovers countries from config.json)
- Concurrent reviewers with item locking (30-minute timeout)
- Embedded ESCO taxonomy search
- No login required - just enter your name

## Setup

### 1. Create Database Tables

Run the SQL files in `sql/` in order, in Supabase's SQL Editor:

1. Go to your [Supabase Dashboard](https://supabase.com/dashboard) -> **SQL Editor**
2. Run `sql/01_create_tables.sql` (base schema: `review_projects`, `review_items`, `review_locks`)
3. Run later migrations as needed (e.g. `sql/04_add_cno_hierarchy.sql`, `sql/05_skill_group_selections.sql`, `sql/06_add_sector_columns.sql`)

The migrations are idempotent (`IF NOT EXISTS` / `CREATE OR REPLACE` style) so re-running is safe.

### 2. Configure Environment

Add to your root `.env` file:

```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your_service_role_key
SUPABASE_ANON_KEY=your_anon_key
```

### 3. Load Project Data

```bash
# From project root
python review_app/scripts/load_project_data.py

# Or with dry-run to preview
python review_app/scripts/load_project_data.py --dry-run
```

The script auto-discovers countries with `config.json` files and prompts for selection.

### 4. Deploy Web Interface

**Option A: Local Testing**
Open `index.html` in a browser - it connects directly to Supabase.

**Option B: Vercel**
```bash
npm i -g vercel
cd review_app
vercel
```

## Usage

1. Open the deployed URL (or index.html locally)
2. Select a project (e.g., "Argentina CNO-2017")
3. Enter your name
4. Review items:
   - **Match**: Select an ESCO occupation from search results
   - **New Local**: Country-specific occupation with no ESCO equivalent
   - **Skip**: Unsure, leave for someone else

## Exporting Results

After human review is complete:

```bash
# From project root
python review_app/scripts/export_review_results.py

# Or with dry-run to preview
python review_app/scripts/export_review_results.py --dry-run
```

This merges decisions back into the country's `matches_final.json/xlsx` files.

## Scripts

| Script | Purpose |
|--------|---------|
| `load_project_data.py` | Load review items into Supabase |
| `export_review_results.py` | Export decisions back to country outputs |
| `clear_project.py` | Delete a project from Supabase |

## Architecture

```
Browser (index.html)
    |
    v
Supabase
    - review_projects (project definitions)
    - review_items (items to review)
    - review_locks (concurrent editing prevention)
    - occupations (ESCO taxonomy for search)
```

## Adding New Countries

Countries are auto-discovered from `countries/*/config.json`. To add a new country:

1. Create the country folder with `config.json`
2. Run the matching pipeline to produce `*_review_items.json`
3. Run `load_project_data.py` - it will find the new country

## Database Queries

Query reviewed items directly:

```sql
SELECT
  ri.local_code,
  ri.local_label,
  ri.decision,
  ri.selected_esco_code,
  ri.selected_esco_label,
  ri.reviewer_name,
  ri.notes
FROM review_items ri
JOIN review_projects rp ON ri.project_id = rp.id
WHERE rp.country_code = 'AR'
  AND ri.decision IS NOT NULL
ORDER BY ri.local_code;
```
