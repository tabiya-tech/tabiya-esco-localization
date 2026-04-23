# Zambia - Methodology

## Approach: NOS-based ESCO Adaptation

Unlike Kenya (KESCO) and Argentina (CNO-2017), Zambia does not have a national occupational taxonomy. The approach adapts the Tabiya ESCO v2.0.1 base taxonomy using 73 National Occupational Standards (NOS) from the Zambia Qualifications Authority (ZAQA) across 8 sectors.

## Source Data

- 73 NOS PDF documents from ZAQA
- 8 sectors: Agriculture (25), Construction (12), Energy (6), Manufacturing (12), Mining (6), Transport (6), Water (6), Tourism (0 - empty)
- Each NOS contains: occupation overview, performance criteria (tasks), technical knowledge, organisational knowledge, regulatory knowledge, core skills, professional skills

## Pipeline (10 Scripts)

### Phase 0: Data Extraction
- **01**: Extract skill phrases from NOS PDFs using pdfplumber
- Output: 19,872 phrases in 6 categories (PC, TK, OK, RK, CS, PS)

### Phase 1: Occupation Matching
- **02**: Embedding match NOS occupation titles + descriptions to ESCO occupations (Gemini embeddings)
- **03**: LLM validation of matches (MATCH vs NEW_LOCAL)
- **03b**: Generate descriptions, alt labels, and ISCO codes for new local occupations
- Rule: ESCO broader than NOS = OK to match; NOS broader than ESCO = NEW_LOCAL

### Phase 2: Skill Matching
- **04**: Tier 1 - Match TK+RK (knowledge) against ESCO knowledge pool (embedding + LLM)
- **05**: Tier 2 - Match CS+PS (skills) against ESCO skill pool (embedding + LLM)
- Decisions: ACCEPT (>=98% exact), CONTEXTUALIZE (add alt labels), NEW (create new skill)
- OK (Organisational Knowledge): assessed and skipped (58% company-generic)

### Phase 3: Gap Analysis
- **06**: PC-based gap analysis - LLM identifies skills evidenced by tasks but missing from ESCO occupation profiles
- PCs are tasks, not skills - used as context, not matched directly (see docs/SKILL_DEFINITIONS_AND_CONTEXTUALIZATION.md)

### Phase 4: Assembly
- **07**: Consolidate and deduplicate all new skills across tiers
- **08**: Generate skill descriptions (LLM), place in hierarchy (LLM-driven, not embedding), map skills to occupations
- **09**: Generate Tabiya 9-file taxonomy output

## Key Design Decisions

1. **Tasks vs Skills**: NOS Performance Criteria are tasks, not skills. They inform gap analysis but are not added directly to the taxonomy.
2. **Skill Hierarchy Placement**: LLM-driven (embedding-based placement was 71% wrong).
3. **Contextualization**: NOS phrases with different wording from ESCO are added as alternative labels, rephrased in ESCO style. Compound phrases are split into individual concepts.
4. **Auto-accept Thresholds**: >=98% exact label = ACCEPT; 94-98% = CONTEXTUALIZE; <94% = LLM review.
5. **Occupation Code Format**: New local occupations use Kenya-style sequential codes `{ISCO}_{seq}` (e.g., `2611_7`), where seq counts ESCO occupations in the group plus existing locals plus one. Falls back to `ZM_{id_prefix}` when no ISCO group code is assigned.
6. **Occupation Hierarchy Placement**: New local occupations are placed under their ISCO unit group (`PARENTOBJECTTYPE=iscogroup`) in `occupation_hierarchy.csv`. Occupations without an ISCO group code remain unplaced.

## Results

- 72 NOS occupations processed: 56 matched to ESCO, 16 new local
- 683 new skills created (330 skill/competence + 353 knowledge)
- 9,772 alt labels added to 1,456 existing ESCO skills
- 4,611 new occupation-to-skill relations
- Tabiya 9-file output: 3,090 occupations, 14,579 skills, 135,433 relations

## Validation

- Human review of occupation matches (all 72 reviewed, 16 reclassified as NEW_LOCAL)
- LLM validation of all skill matches with checkpointing
- Import rule compliance checked against Kenya import findings
- Pending: human review of new skill descriptions and hierarchy placements

## Output

Standard Tabiya 9-file CSV format at `outputs/taxonomy/`:
- occupations.csv, occupation_groups.csv, occupation_hierarchy.csv
- skills.csv, skill_groups.csv, skill_hierarchy.csv
- occupation_to_skill_relations.csv, skill_to_skill_relations.csv
- model_info.csv
