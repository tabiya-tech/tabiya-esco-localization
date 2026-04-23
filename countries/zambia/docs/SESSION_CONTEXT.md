# Zambia - Session Context

## Current Phase
**Phase 1: NOS-based localization complete (pending human review)**

## Last Session (2026-04-21)

### Accomplished
- Switched new local occupation code format from `{ISCO}.ZM.{suffix}` to Kenya-style sequential `{ISCO}_{seq}` in script 09
- Placed new local occupations in occupation hierarchy under their ISCO unit group (was previously skipped, leaving locals top-level)
- Regenerated 9-file taxonomy output with updated codes and hierarchy entries

## Previous Session (2026-04-09 to 2026-04-11)

### Accomplished
- Set up Zambia project structure
- Imported 73 NOS PDFs from Zambia Qualifications Authority (8 sectors)
- Extracted 19,872 skill phrases from NOS documents (script 01)
- Matched 72 NOS occupations to ESCO: 56 MATCH, 16 NEW_LOCAL (scripts 02-03)
- Generated descriptions and alt labels for 16 new local occupations (script 03b)
- Tier 1 knowledge matching (TK+RK): 30 accept, 2,439 contextualize, 212 new (script 04)
- Tier 2 skill matching (CS+PS): 16 accept, 2,426 contextualize, 57 new (script 05)
- PC gap analysis: 416 skill gaps across 56 occupations (script 06)
- OK assessment: skipped (58% company-generic, remainder covered by TK/RK)
- Consolidated 683 new skills with descriptions and hierarchy placement (scripts 07-08)
- Built occupation-to-skill mapping: 8,341 total (3,676 ESCO existing + 4,665 Zambia localized)
- Generated Tabiya 9-file taxonomy output (script 09)
- Created shared doc: docs/SKILL_DEFINITIONS_AND_CONTEXTUALIZATION.md

### Key Decisions
- No national taxonomy exists; adapting Tabiya ESCO base using NOS as source
- English only (no translation)
- Tasks vs skills distinction: PCs are tasks, used as context for gap analysis not direct matching
- ESCO broader than NOS = OK to match; NOS broader than ESCO = NEW_LOCAL
- Skill hierarchy placement: LLM-driven (embedding-based was 71% wrong)
- Auto-accept thresholds: >=98% exact = ACCEPT; 94-98% = CONTEXTUALIZE; <94% = LLM review
- OK (Organisational Knowledge) skipped - 58% generic company items

### 16 NEW_LOCAL Occupations
Agriculture: Agricultural Marketing Officer, Fisheries Officer, Agricultural Extension Officer,
Animal Breeder-Geneticist, Aquacultural Economist, Scuba Diver (aquaculture),
Livestock Slaughter Supervisor, Aquaculture Farmer, Fisheries Extension Assistant,
Senior Agriculture Officer
Construction: Heavy Duty Machine Operator
Manufacturing: Metal Fabricator, Workshop Machines Operator
Mining: Winding Engine Operator (mining)
Transport: Professional Driver, Transport Manager (Transportant)

## Current State
- 9-file taxonomy output generated at outputs/taxonomy/ with Kenya-style codes and hierarchy placement
- New occupation-skill relations have empty RELATIONTYPE/SIGNALLINGVALUE (to be assigned later)
- 3 new skills missing hierarchy placement (out of 683)

## Next Steps
1. Human review of Excel outputs (new skills, alt labels, occupation matches)
2. Assign RELATIONTYPE/SIGNALLINGVALUE for new occupation-skill relations
3. Import testing with Tabiya platform

## Pipeline Scripts
| # | Script | Purpose |
|---|---|---|
| 01 | 01_extract_nos_skills.py | Extract skill phrases from NOS PDFs |
| 02 | 02_match_occupations.py | Embedding match occupations to ESCO |
| 03 | 03_validate_occupation_matches.py | LLM validate occupation matches |
| 03b | 03b_finalize_new_occupations.py | Descriptions + alt labels + ISCO codes for NEW_LOCAL |
| 04 | 04_match_and_validate_tier1.py | Tier 1: TK+RK to ESCO knowledge |
| 05 | 05_match_and_validate_tier2.py | Tier 2: CS+PS to ESCO skills |
| 06 | 06_pc_gap_analysis.py | PC-based skill gap analysis |
| 07 | 07_consolidate_skills.py | Deduplicate and assemble |
| 08 | 08_finalize_skills.py | Describe + place + map skills |
| 09 | 09_generate_taxonomy.py | Generate Tabiya 9-file output |
