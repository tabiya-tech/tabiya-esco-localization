# Localization Pipeline

**Version:** 3.0.0
**Last Updated:** 2025-12-27

---

## Overview

This pipeline maps national occupational taxonomies to the Tabiya ESCO taxonomy. It assumes the source country has:

1. A structured national taxonomy of occupations (any format: PDF, Excel, database)
2. An official or de facto crosswalk to ISCO-08 codes

> **Note:** For countries lacking either component, this pipeline requires adaptation. See [Adapting for Missing Components](#adapting-for-missing-components).

---

## Pipeline Phases

```
Phase 0: Data Preparation
  Extract, clean, translate (if needed), generate embeddings

Phase 1: Semantic Matching
  Step 1A: ISCO-constrained matching
  Step 1B: Unconstrained upgrade

Phase 2: LLM Validation
  Step 2A: Binary validation
  Step 2B: Hybrid candidate search

Phase 3: Human Review
  Review new_local occupations, select ESCO matches or confirm as local

Phase 4: Skill Assignment & Export
  Assign skills, generate Tabiya 9-file format
```

---

## Phase 0: Data Preparation

### Purpose
Prepare national taxonomy and reference data for semantic matching.

### Steps

**0.1 Extract National Taxonomy**
- Parse source data (PDF, Excel, database)
- Extract: occupation code, title, description, hierarchy level
- Validate hierarchy integrity

**0.2 Process ISCO Crosswalk**
- Extract national code → ISCO-08 mappings
- Resolve ISCO codes to ESCO occupation UUIDs
- Build lookup: `national_code → [esco_uuids]`

**0.3 Translate (if needed)**
- Translate titles and descriptions to English
- Preserve original text alongside translation
- Use LLM-based translation (Gemini recommended)

**0.4 Generate Embeddings**
- Generate embeddings for national occupation titles
- Use Gemini embedding model (`text-embedding-004`)
- Retrieve or generate ESCO embeddings (cached in `shared_data/`)

### Outputs
- `data/source/` - Raw and processed national taxonomy
- `data/generated/` - ISCO crosswalk, translated taxonomy
- `data/embeddings/` - National occupation embeddings

---

## Phase 1: Semantic Matching

### Purpose
Identify ESCO candidates for each national occupation using semantic similarity, constrained by ISCO crosswalk.

---

### Step 1A: ISCO-Constrained Matching

**Objective:** Find best ESCO match within the ISCO-mapped search space.

**Process:**
1. For each national occupation, get ISCO code from crosswalk
2. Retrieve all ESCO occupations under that ISCO code
3. Compute cosine similarity between national embedding and each ESCO candidate
4. Select top match with similarity score

**Thresholds:**
- `>= 0.85`: High confidence (auto-accept)
- `0.70 - 0.84`: Medium confidence (needs validation)
- `< 0.70`: Low confidence (needs LLM review)

**Output per occupation:**
- `esco_code`, `esco_uuid`, `esco_title`
- `similarity_score`
- `confidence_level` (high/medium/low)

---

### Step 1B: Unconstrained Upgrade

**Objective:** Catch ISCO crosswalk errors by checking if a better match exists outside the constrained search space.

**Process:**
1. For each 1A result, compute similarity against ALL ESCO occupations
2. Find best unconstrained match
3. If unconstrained match is significantly better (e.g., +0.05 similarity), flag as crosswalk mismatch
4. Upgrade to unconstrained match if it exceeds high-confidence threshold

**Decision logic:**
```
IF unconstrained_sim >= 0.90 AND unconstrained_sim > constrained_sim + 0.05:
    decision = "exact_crosswalk_fix"
    use unconstrained match
ELSE:
    keep constrained match
```

**Output:**
- Updated matches for crosswalk mismatches
- `decision` field: "exact" or "exact_crosswalk_fix"

---

### Phase 1 Summary

| Decision | Meaning | Action |
|----------|---------|--------|
| exact | High-confidence constrained match | Accept, skip Phase 2 |
| exact_crosswalk_fix | Better unconstrained match found | Accept with corrected ESCO |
| needs_validation | Medium confidence | Send to Step 2A |
| needs_review | Low confidence | Send to Step 2B |

---

## Phase 2: LLM Validation

### Purpose
Validate uncertain matches and find alternatives for rejected ones using LLM reasoning.

---

### Step 2A: Binary Validation

**Objective:** Quick yes/no validation of medium-confidence matches.

**Process:**
1. For each `needs_validation` occupation:
2. Present to LLM: national title/description + proposed ESCO match
3. Ask: "Is this a good match?" (binary yes/no)
4. Approved matches are finalized; rejected go to Step 2B

**Prompt structure:**
```
National occupation: [code] [title]
Proposed ESCO match: [code] [title] (similarity: X%)

Is this a semantically appropriate match? Answer YES or NO.
```

**Output:**
- `decision`: "approved" or "rejected"
- Rejected occupations proceed to Step 2B

---

### Step 2B: Hybrid Candidate Search

**Objective:** Find best match from multiple sources, or confirm as new local occupation.

**Scope:** All occupations that are:
- Rejected in Step 2A
- Below 90% similarity in Step 1
- Flagged for review

**Process:**
1. Generate candidate pool:
   - Top 5 from ISCO-constrained search
   - Top 5 from unconstrained semantic search
   - Deduplicate
2. Present candidates to LLM with national occupation context
3. LLM selects best match OR decides `new_local`

**Prompt structure:**
```
National occupation: [code] [title]
Description: [if available]

Candidates:
1. [esco_code] [title] (similarity: X%, source: constrained)
2. [esco_code] [title] (similarity: X%, source: unconstrained)
...

Select the best match (1-N) or respond NEW_LOCAL if none are appropriate.
```

**Output:**
- `decision`: "selected" or "new_local"
- `selected_esco_code`, `selected_esco_uuid` (if matched)

---

### Phase 2 Summary

| Decision | Meaning | Next Step |
|----------|---------|-----------|
| approved | LLM confirmed 2A match | Finalize |
| selected | LLM chose from 2B candidates | Finalize |
| new_local | No suitable ESCO match | Human review |

---

## Phase 3: Human Review

### Purpose
Expert review of `new_local` occupations to either find an ESCO match or confirm as truly local.

### Review Tool

Web-based interface with:
- Supabase backend (multi-reviewer support, item locking)
- ESCO taxonomy tree browser
- Local occupation context (hierarchy, description)
- Selection options: Match to ESCO or Confirm as New Local

### Reviewer Actions

1. **Match to ESCO**: Browse tree, select appropriate occupation
2. **New Local with Parent**: Select ESCO parent group for new occupation
3. **Skip**: Defer for later review

### Output
- `review_decision`: "matched" or "confirmed_new_local"
- `selected_esco_code` (if matched)
- `selected_parent_code` (if new local)
- `reviewer_notes`

---

## Phase 4: Skill Assignment & Export

### Purpose
Assign skills and export to Tabiya 9-file format.

### Skill Assignment Strategy

| Match Type | Strategy |
|------------|----------|
| ESCO matched | Inherit all skills from matched ESCO occupation |
| New local (with parent) | Inherit skills from ESCO parent, flag for review |

### Export Format

Generate Tabiya 9-file CSV package:
- `occupations.csv`
- `occupationHierarchy.csv`
- `skills.csv`
- `skillHierarchy.csv`
- `skillGroups.csv`
- `occupationToSkillRelations.csv`
- `skillToSkillRelations.csv`
- `localizedStrings.csv`
- `metadata.csv`

See `DATA_DICTIONARY.md` for schema details.

---

## Key Technical Decisions

### Embedding Model: Gemini over Sentence-Transformers

Gemini `text-embedding-004` significantly outperforms `all-MiniLM-L6-v2`:
- Kenya: 26.7% → 93.5% high-confidence matches after switching

### Similarity Thresholds

| Threshold | Meaning |
|-----------|---------|
| >= 0.90 | Very high confidence |
| >= 0.85 | High confidence (auto-accept) |
| 0.70 - 0.84 | Medium (needs LLM validation) |
| < 0.70 | Low (needs hybrid search) |

### Crosswalk as Constraint, Not Requirement

ISCO crosswalks contain errors. Step 1B catches these by checking unconstrained matches. This improved coverage significantly (Argentina: 8.9% → 92.6% after fixing crosswalk key format).

### Shared ESCO Embeddings

ESCO embeddings are generated once and cached in `shared_data/embeddings_cache/` for reuse across countries.

---

## Adapting for Missing Components

This pipeline assumes a national taxonomy with ISCO crosswalk. Adaptations needed for other contexts:

| Missing Component | Adaptation |
|-------------------|------------|
| No ISCO crosswalk | Skip Step 1A, use only unconstrained matching. Increase LLM validation scope. |
| No structured taxonomy | Extract from job postings, labor surveys, or expert knowledge. Build taxonomy first. |
| Non-ISCO-based taxonomy | Map to ISCO first, or use direct semantic matching to ESCO. |
| No English translation | Match in source language if ESCO translations available, or translate first. |

---

## Country-Specific Documentation

Each country maintains its own documentation in `countries/{country}/docs/`:
- `SESSION_CONTEXT.md` - Current state and next steps
- `METHODOLOGY.md` - Country-specific adaptations

---

## References

- `DATA_DICTIONARY.md` - Tabiya 9-file format specification
- `CODING_STANDARDS.md` - Python implementation standards
- `ESCO_SYNC_GUIDE.md` - Syncing ESCO reference data
