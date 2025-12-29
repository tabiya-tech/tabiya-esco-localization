-- Add CNO hierarchy columns to review_items
ALTER TABLE review_items
ADD COLUMN IF NOT EXISTS cno_major_code TEXT,
ADD COLUMN IF NOT EXISTS cno_major_title TEXT,
ADD COLUMN IF NOT EXISTS cno_minor_code TEXT,
ADD COLUMN IF NOT EXISTS cno_minor_title TEXT;
