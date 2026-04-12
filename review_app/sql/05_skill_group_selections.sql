-- Skill group selections for new local occupations
-- Run this migration in Supabase SQL Editor

CREATE TABLE IF NOT EXISTS skill_group_selections (
    id BIGSERIAL PRIMARY KEY,
    project_id BIGINT REFERENCES review_projects(id) ON DELETE CASCADE,
    occupation_code TEXT NOT NULL,
    skill_group_code TEXT NOT NULL,
    selected_by TEXT NOT NULL,
    selected_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(project_id, occupation_code, skill_group_code)
);

-- Index for fast lookups by project and occupation
CREATE INDEX IF NOT EXISTS idx_skill_group_selections_project
    ON skill_group_selections(project_id);
CREATE INDEX IF NOT EXISTS idx_skill_group_selections_occupation
    ON skill_group_selections(project_id, occupation_code);

-- Enable RLS
ALTER TABLE skill_group_selections ENABLE ROW LEVEL SECURITY;

-- Allow all operations for authenticated and anonymous users (same as review_items)
CREATE POLICY "Allow all operations on skill_group_selections"
    ON skill_group_selections FOR ALL
    USING (true)
    WITH CHECK (true);

-- Grant permissions
GRANT ALL ON skill_group_selections TO anon;
GRANT ALL ON skill_group_selections TO authenticated;
GRANT USAGE, SELECT ON SEQUENCE skill_group_selections_id_seq TO anon;
GRANT USAGE, SELECT ON SEQUENCE skill_group_selections_id_seq TO authenticated;
