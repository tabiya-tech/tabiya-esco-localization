# Country Activity Log

High-level updates across all localization efforts. For detailed session context, see each country's `docs/SESSION_CONTEXT.md`.

---

## Argentina (CNO-2017)

### 2024-12-17 - Argentina
- Completed Approach 5: Gemini embeddings with 95.9% high-confidence matches
- Began Phase 2 categorization (exact/alt_label/sibling/child)
- Status: In Progress

### 2025-01-22 - Argentina
- Framework documentation setup, multi-country folder structure established
- Migrated all Argentina files to countries/argentina_cno2017/
- Status: In Progress

### 2025-12-17 - Argentina
- Fixed categorization logic (replaced word-count approach with hybrid rules + LLM)
- Created categorize_matches_v2.py with deputy prefix detection, unit clustering
- Sample test: 47% rule-categorized, 53% need LLM
- Status: In Progress

### 2025-12-18 - Argentina
- Raised crosswalk fallback threshold 0.5 to 0.85, reran Phase 1 (99.7% high-confidence)
- Full Phase 2A run: 2,347 (41.1%) rule-categorized, 3,369 (58.9%) NEEDS_LLM
- Added Spanish ESCO to Supabase (3,074 occupations)
- Built Phase 2B with Gemini function calling + Supabase taxonomy search tools
- Status: In Progress - Ready to run Phase 2B sample test

### 2025-12-22 - Argentina
- Fixed crosswalk key building (8.9% -> 92.6% coverage)
- Ran full Phase 2B on 3,369 NEEDS_LLM: 71.1% matched, 28.9% new_local
- Status: Milestone Reached - Phase 2B complete, pending pipeline review

### 2025-12-25 - Argentina
- Ran full matching pipeline: Phase 1 + Phase 1B + Phase 2 + Phase 3 (hybrid candidate search)
- Phase 3 used hybrid candidates (semantic + ISCO-constrained) with LLM selection
- Final result: 89.6% ESCO-matched (5,101), 10.4% new_local (589)
- Status: Milestone Reached - Matching pipeline complete, ready for skill assignment

### 2025-12-27 - Argentina
- Completed Review Tool UI with Tabiya Design System (Oxford Blue, Tabiya Green, DM Mono/Inter)
- Added CNO hierarchy context (minor code + English title) to review items
- Implemented tree interaction: single-click toggle, double-click select, auto-close descendants
- Added auto-hide for ES labels when same as EN (multi-language support)
- Status: Milestone Reached - Review tool UI complete, ready for deployment

---

## Kenya (KESCO)

### 2025-12-24 - Kenya
- Implemented constrained semantic matching v2 (hierarchical ISCO + multi-embedding)
- Full run on 5,917 occupations: 26.7% high confidence, 63.5% need review
- Completed LLM evaluation (constrained): 42% confirmed good, 54.5% need different match
- Started unconstrained LLM evaluation for ISCO crosswalk mismatches (needs optimization)
- Status: In Progress

### 2025-12-26 - Kenya
- Switched from sentence-transformers to Gemini embeddings (93.5% high-quality vs 26.7% before)
- Created shared English ESCO embeddings in shared_data/ for reuse
- Ran Argentina-style pipeline (Step 1A + 1B): 383 need LLM review, 884 crosswalk mismatches
- Status: Milestone Reached - Phase 1 complete, ready for Phase 2 LLM validation

### 2025-12-26 - Kenya (Session 2)
- Completed full matching pipeline: Step 1A, 1B, 2A, 2B
- Expanded Step 2B scope to include matches <90% similarity (not just rejected)
- Final result: 97.4% ESCO-matched (5,761), 2.6% new_local (156)
- Created final output and combined pipeline script for documentation
- Status: Milestone Reached - Matching pipeline complete, ready for skill assignment

---

## Ethiopia

*No activity yet.*

---

## Zambia

*No activity yet.*

---

## Ukraine

*No activity yet.*

---

## Bosnia & Herzegovina

*No activity yet.*

---

## Framework

### 2025-12-17 - Framework
- Set up session continuity commands (start_session, close_session)
- Reorganized docs structure for multi-country support
- Status: In Progress

### 2025-12-28 - Framework
- Documented actual 4-step pipeline (1A, 1B, 2A, 2B) in new LOCALIZATION_PIPELINE.md
- Removed outdated docs: ARCHITECTURE.md, PIPELINE_SPECIFICATION.md, DECISIONS_LOG.md
- Updated all references across CLAUDE.md, README.md, session commands
- Status: Milestone Reached - Framework docs reflect actual implementation

---

## Entry Template

```markdown
### [YYYY-MM-DD] - [Country/Framework]
- [Brief summary of work done]
- Status: [In Progress / Milestone Reached / Blocked / Complete]
```
