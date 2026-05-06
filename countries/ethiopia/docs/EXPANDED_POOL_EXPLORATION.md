# Ethiopia ELMIS — Stage-2 No-Match Retry With Expanded Candidate Pool (Exploration)

**Date:** 2026-05-05
**Status:** Exploration. Results are recorded for reference; **the canonical stage-2 result remains the unfiltered output of `00_run_stage2.py`** (top-5 NEL candidates only). This experiment is not promoted into the active pipeline.

---

## 1. Purpose

The canonical stage-2 LLM matcher (`scripts/00_run_stage2.py`) only sees the 5 ESCO candidates produced by the stage-1 NEL classifier per ELMIS title. We tested whether some of the 783 stage-2 `no_match` decisions are an artefact of the right ESCO occupation being absent from the top-5, rather than a genuine "no ESCO equivalent" case.

The test is also a sanity check on whether the previously parked sub-sector → ISCO 4-digit mapping carries useful signal when used for **candidate expansion** instead of as a hard filter.

---

## 2. Methodology

### Inputs
- `outputs/stage2_results.csv` — canonical stage-2 output, filtered to `stage2_decision == 'no_match'` (783 rows).
- `outputs/subsector_isco_map.csv` — sub-sector → ISCO 4-digit mapping (216 rows; 96 `map`, 120 `no_map`).
- `outputs/matches_minilm.csv` — original stage-1 NEL top-5 per title.
- `shared_data/esco_taxonomy/occupations.csv` — for ESCO occupations within an ISCO 4-digit group.

### In-scope rows
A title was retried only if its source `(sector, sub-sector)` had a `mapping_decision == 'map'` in `subsector_isco_map.csv` and a non-empty `isco_code`. **285 of the 783 stage-2 no_match titles met this condition.** The remaining 498 sit in `no_map` sub-sectors and are not addressed by this experiment.

### Candidate pool per retried title
1. The 5 NEL candidates from stage 1.
2. **Every** ESCO occupation whose `OCCUPATIONGROUPCODE` equals the sub-sector's mapped ISCO 4-digit code. No cap. No 3-digit fallback.
3. Deduplicated by ESCO `ORIGINURI`. Each candidate carries a source tag: `[stage-1 classifier]` or `[sub-sector ISCO group]`.

The pool size ranged from 6 to ~50 candidates per title, with most rows in the 11–20 range (NEL has 5; ISCO 4-digit groups in ESCO typically contain 6–15 occupations).

### Prompt
Same task as the canonical stage-2 prompt: pick the candidate that best describes the same work or return `no_match`. The expanded prompt presents source tags neutrally:

> The candidate list comes from two retrieval methods, neither of which is more authoritative than the other - judge each candidate on its own merits, not by source.

(See Appendix A for the full prompt.)

### LLM
Gemini 3 Flash (`gemini-3-flash-preview`), same as canonical stage 2. JSON output schema: `{decision, selected_index, confidence, rationale}`.

---

## 3. Results

### 3.1 Decision flips on the 285 retried titles

| Retry decision | Count | % of 285 |
|---|---:|---:|
| `match` (flipped from no_match) | 156 | 54.7% |
| `no_match` (still no match) | 129 | 45.3% |
| Errors | 0 | 0% |

### 3.2 Where the new picks came from

| Source of picked candidate | Count | % of 156 flips |
|---|---:|---:|
| `[sub-sector ISCO group]` (new candidate, not in stage-1 NEL top-5) | 143 | 91.7% |
| `[stage-1 classifier]` (was already in NEL top-5; LLM changed its mind) | 13 | 8.3% |

### 3.3 Confidence on the 156 flipped matches

| LLM confidence | Count |
|---|---:|
| high | 116 |
| medium | 38 |
| low | 2 |

### 3.4 Effect on the full pipeline if these flips were promoted to canonical

| Outcome bucket | Canonical (kept) | If flips merged |
|---|---:|---:|
| Stage-1 auto-pass | 1,613 | 1,613 |
| Stage-2 match | 1,738 | 1,738 + 156 = 1,894 |
| No_match (→ new_local pile) | 783 | 783 − 156 = 627 |
| **ESCO-matched total** | **3,351 (81.0%)** | **3,507 (84.8%)** |

### 3.5 Untouched cohort

498 stage-2 no_match titles sit in sub-sectors with `mapping_decision == 'no_map'` (sub-sector too broad or generic to bind to a single ISCO 4-digit). This experiment does not address them.

---

## 4. Caveats

- The retry uses the same LLM model as canonical stage 2. Larger candidate pools may carry a different error profile; spot-checks of the 156 flips are recommended before any future promotion.
- The 13 cases where the LLM picked a NEL candidate after originally rejecting all 5 indicate model variance, not just pool composition; this is a small fraction (~5% of retried titles).
- "Flip rate" is computed only over the 285 retried titles. The flip rate against the full 783 no_match pool is 156 / 783 = 19.9%.

---

## 5. Decision

The canonical stage-2 output (top-5 NEL candidates only) remains the active pipeline result. This experiment is preserved for partner reference and to inform any future decision on whether to incorporate sub-sector-driven candidate expansion as a stage-2.5 step.

The 156 flipped rows are **not** merged into `stage2_results.csv`. They live separately in `outputs/stage2_no_match_retry.csv`.

---

## 6. Output Files

| File | Contents |
|---|---|
| `outputs/stage2_no_match_retry.csv` | One row per retried title (285 rows). Columns include the retry decision, the picked candidate, the source of the pick (`nel` or `isco_group`), confidence, rationale, and pool sizes. |
| `outputs/subsector_isco_map.csv` | The sub-sector → ISCO 4-digit mapping used to build expanded pools (also used by the parked filter experiment). |

---

## 7. Reproducing the run

```
python countries/ethiopia/scripts/01_no_match_retry_expanded_pool.py
python countries/ethiopia/scripts/01_no_match_retry_expanded_pool.py --workers 10
python countries/ethiopia/scripts/01_no_match_retry_expanded_pool.py --dry-run     # preview prompt
python countries/ethiopia/scripts/01_no_match_retry_expanded_pool.py --limit 5     # smoke test
```

Requires `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) in the project-root `.env`.

---

## Appendix A — Expanded-pool LLM prompt (verbatim)

The same prompt is filled per retried title with `{elmis_title}`, `{amharic}`, `{sector}`, `{sub_sector}`, `{pf}`, and `{cand_text}` (the numbered candidate list with per-candidate source tag, label, ISCO 4-digit code, group label, optional similarity score, and ESCO description).

```
You are matching an Ethiopia ELMIS occupational title to its best European ESCO equivalent.

ELMIS TITLE
- English title:     {elmis_title}
- Amharic title:     {amharic}
- Sector:            {sector}
- Sub-sector:        {sub_sector}
- Profession class:  {pf}    (P = professional, F = formal informal)

CANDIDATE ESCO OCCUPATIONS
The candidate list comes from two retrieval methods, neither of which is more authoritative than the other - judge each candidate on its own merits, not by source:
  - "[stage-1 classifier]" : top-5 from a semantic similarity classifier
  - "[sub-sector ISCO group]" : every ESCO occupation in the ISCO 4-digit group implied by the ELMIS sub-sector

{cand_text}

YOUR JOB
Pick the candidate that best describes the same work as the ELMIS title.

Guidelines:
- The ELMIS title may use Ethiopian or African phrasing; treat it as a plausible local variant of the ESCO occupation if the underlying work overlaps clearly.
- Use the sector and sub-sector to disambiguate when several candidates have similar labels but sit in different work domains.
- Pay attention to seniority cues in the ELMIS title (manager, technician, assistant, designer, engineer): the right ESCO match should be at the same seniority level, not just the same field.
- Prefer a less-than-perfect but domain-correct match over a label-similar match in the wrong domain.
- Do NOT favor candidates by source. Both sources can yield right or wrong matches.
- If no candidate describes the same work, choose "no_match" - the title will go to human review.

OUTPUT - return ONLY valid JSON, no prose:
{
  "decision": "match" | "no_match",
  "selected_index": <integer 1..N> or null,
  "confidence": "high" | "medium" | "low",
  "rationale": "<one short sentence>"
}

Rules:
- decision = "match" requires selected_index to be the rank (1..{N}) of the chosen candidate.
- decision = "no_match" requires selected_index = null.
- confidence reflects how clearly the chosen candidate (or no_match decision) is the right answer.
```
