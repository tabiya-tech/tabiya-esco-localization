-- =============================================
-- Add sector + sub_sector columns to review_items
-- Run once in Supabase SQL Editor.
-- Idempotent: uses IF NOT EXISTS.
-- =============================================

ALTER TABLE review_items
  ADD COLUMN IF NOT EXISTS sector TEXT,
  ADD COLUMN IF NOT EXISTS sub_sector TEXT;
