-- =============================================
-- TAXONOMY REVIEW TOOL - DATABASE SCHEMA
-- Multi-country review platform
-- Run this in Supabase SQL Editor
-- =============================================

-- Projects (one per country/taxonomy localization)
CREATE TABLE review_projects (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  country_code TEXT NOT NULL,
  source_taxonomy TEXT NOT NULL,
  description TEXT,
  status TEXT DEFAULT 'active',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Review Items (occupations to review)
CREATE TABLE review_items (
  id SERIAL PRIMARY KEY,
  project_id INTEGER REFERENCES review_projects(id) ON DELETE CASCADE,

  -- Local occupation info
  local_code TEXT NOT NULL,
  local_label TEXT NOT NULL,
  local_label_en TEXT,
  isco_code TEXT,

  -- Pipeline's automated suggestion
  suggested_esco_code TEXT,
  suggested_esco_label TEXT,
  suggested_esco_label_en TEXT,
  similarity REAL,

  -- Human review decision
  decision TEXT,                    -- 'MATCH', 'NEW_LOCAL', 'SKIP'

  -- For MATCH decisions: selected ESCO occupation
  selected_esco_code TEXT,
  selected_esco_label TEXT,

  -- For NEW_LOCAL decisions: optional parent for skill inheritance
  selected_parent_code TEXT,
  selected_parent_label TEXT,

  -- Reviewer info
  reviewer_name TEXT,
  reviewed_at TIMESTAMPTZ,
  notes TEXT,

  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(project_id, local_code)
);

-- Review Locks (prevent concurrent editing)
CREATE TABLE review_locks (
  id SERIAL PRIMARY KEY,
  item_id INTEGER REFERENCES review_items(id) ON DELETE CASCADE UNIQUE,
  reviewer_name TEXT NOT NULL,
  locked_at TIMESTAMPTZ DEFAULT NOW(),
  expires_at TIMESTAMPTZ NOT NULL
);

-- =============================================
-- INDEXES
-- =============================================

CREATE INDEX idx_review_items_project ON review_items(project_id);
CREATE INDEX idx_review_items_decision ON review_items(decision);
CREATE INDEX idx_review_locks_expires ON review_locks(expires_at);

-- =============================================
-- ROW LEVEL SECURITY
-- =============================================

ALTER TABLE review_projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE review_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE review_locks ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public access" ON review_projects FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Public access" ON review_items FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Public access" ON review_locks FOR ALL USING (true) WITH CHECK (true);

-- =============================================
-- VIEW: Project progress
-- =============================================

CREATE OR REPLACE VIEW review_progress AS
SELECT
  rp.id AS project_id,
  rp.name,
  rp.country_code,
  COUNT(*) AS total,
  COUNT(*) FILTER (WHERE ri.decision IS NOT NULL) AS reviewed,
  COUNT(*) FILTER (WHERE ri.decision = 'MATCH') AS matched,
  COUNT(*) FILTER (WHERE ri.decision = 'NEW_LOCAL') AS new_local,
  COUNT(*) FILTER (WHERE ri.decision = 'SKIP') AS skipped
FROM review_projects rp
LEFT JOIN review_items ri ON rp.id = ri.project_id
GROUP BY rp.id, rp.name, rp.country_code;
