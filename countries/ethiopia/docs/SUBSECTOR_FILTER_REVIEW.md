# Ethiopia ELMIS — Sub-sector Filter Methodology and Results

**Date:** 2026-04-30
**Batch:** 4,135 ELMIS occupational titles
**Companion file:** `outputs/ethiopia_subsector_filter_review.xlsx`

---

## 1. Purpose

This document records a methodology variant tested on top of the stage-1 NEL classifier output for the Ethiopia ELMIS occupational title list. The variant aims to refine the stage-1 ESCO matches by constraining each ELMIS title's candidate matches to ESCO occupations within the same ISCO 2-digit Sub-major Group as the title's source sub-sector.

This document is a factual record of what was run and what the numbers show. It does not draw conclusions about whether to apply the filter to the final pipeline.

---

## 2. Inputs

| Item | Value |
|---|---|
| ELMIS titles in this batch | 4,135 |
| Distinct sectors in source data | 17 |
| Distinct sub-sectors in source data | 210 |
| Distinct (sector, sub-sector) pairs | 216 |
| ESCO baseline taxonomy | Tabiya v2.0.1-rc.1, model id `68933862382aab4c7de13ec6` |
| Stage-1 classifier | NEL v2 service at `https://dev.classifier.tabiya.tech` |
| Stage-1 NEL embedding model | `all-MiniLM-L6-v2-occupation-fine-tuned` |
| Sub-sector mapping LLM | Gemini 3 Flash (`gemini-3-flash-preview`) |
| ISCO group reference | `shared_data/esco_taxonomy/occupation_groups.csv` (438 four-digit Unit Groups) |

Confidence labels follow the existing thresholds:

| Label | Score range |
|---|---|
| `exact` | score ≥ 0.95 |
| `high_confidence` | 0.85 ≤ score < 0.95 |
| `low_similarity` | 0.50 ≤ score < 0.85 |

---

## 3. Methodology

### Step 1 — LLM mapping of sub-sectors to ISCO 4-digit Unit Groups

For each of the 216 unique (sector, sub-sector) pairs, a single Gemini 3 Flash call was made with the prompt in **Appendix A**. The model returns a structured JSON object with:

- `mapping_decision`: `"map"` or `"no_map"`
- `isco_code`: the 4-digit Unit Group code, or `null`
- `isco_label`: the label of that group, or `null`
- `confidence`: `"high"`, `"medium"`, or `"low"`
- `rationale`: one-sentence explanation
- `fallback_isco_3digit`: the 3-digit parent of `isco_code`, or `null`

Empty or "None" sub-sector strings are short-circuited locally to `no_map` without an LLM call.

A post-processing step in `scripts/00_build_subsector_isco_map.py` validates that any `isco_code` returned exists in ISCO-08; if not, the row is downgraded to `no_map`.

### Step 2 — Apply ISCO 2-digit filter to stage-1 top-5 matches

`scripts/01_apply_subsector_filter.py` reads the stage-1 output (`matches_minilm.csv`, 4,135 rows × 5 ESCO matches each) and applies the following per-row rule:

1. Look up the ELMIS row's `(sector, sub_sector)` in the mapping.
2. If `mapping_decision == "no_map"`: leave all 5 stage-1 matches untouched.
3. If `mapping_decision == "map"`: take the first 2 digits of `isco_code`. For each of the 5 stage-1 matches, look up the ESCO occupation's `OCCUPATIONGROUPCODE` (a 4-digit ISCO code) in `shared_data/esco_taxonomy/occupations.csv`. Keep the match if its first 2 digits equal the sub-sector's first 2 digits; drop it otherwise.
4. Repack survivors into positions m1..mN; recompute `best_score` and `best_confidence`.

Output: `matches_minilm_subsector_filtered.csv` (same shape as the stage-1 file, plus `subsector_isco4`, `filter_applied`, `n_dropped`, `dropped_labels` columns).

---

## 4. Results

### 4.1 Sub-sector mapping outcomes

| Decision | Count | % of pairs |
|---|---:|---:|
| map | 96 | 44.4% |
| no_map | 120 | 55.6% |
| **Total** | **216** | **100.0%** |

By LLM-reported confidence on the mapped subset:

| Confidence | Count |
|---|---:|
| high | 88 |
| medium | 8 |
| low | 0 |
| **Total mapped** | **96** |

By LLM-reported confidence on the no-map subset:

| Confidence | Count |
|---|---:|
| high | 77 |
| medium | 17 |
| low | 26 |
| **Total no_map** | **120** |

### 4.2 Per-row outcome of applying the filter

| Outcome flag | Count | % of 4,135 |
|---|---:|---:|
| `no_filter` (sub-sector mapped to no_map) | 2,595 | 62.8% |
| `unchanged` (filter applied, no top-5 entry dropped) | 96 | 2.3% |
| `best_kept` (filter applied, dropped some entries but original top-1 survived) | 479 | 11.6% |
| `best_changed` (filter applied, original top-1 dropped, different surviving match now top-1) | 463 | 11.2% |
| `lost_all` (filter applied, every top-5 entry dropped) | 502 | 12.1% |
| **Total** | **4,135** | **100.0%** |

### 4.3 Best-confidence distribution per ELMIS title

| Best-confidence label | Before filter | After filter | Δ |
|---|---:|---:|---:|
| exact | 96 | 85 | −11 |
| high_confidence | 1,516 | 1,268 | −248 |
| low_similarity | 2,523 | 2,280 | −243 |
| (no matches) | 0 | 502 | +502 |
| **Total** | **4,135** | **4,135** | — |

### 4.4 Top-5 entries kept and dropped

| Metric | Count |
|---|---:|
| Total top-5 entries before filter | 20,675 |
| Total top-5 entries after filter | 15,437 |
| Dropped | 5,238 |

Dropped entries by their stage-1 confidence label:

| Confidence | Dropped |
|---|---:|
| exact | 14 |
| high_confidence | 738 |
| low_similarity | 4,486 |

### 4.5 Sub-sectors with the most `lost_all` rows

| Sub-sector | `lost_all` rows |
|---|---:|
| Software Design Development and Implementation Works | 82 |
| Quality Management Consulting Service | 64 |
| Consulting service around social science | 53 |
| Advertising | 32 |
| Employment agencies and recruitment agencies | 31 |
| Laboratory test | 17 |
| Equipment and machine installation and maintenance service | 16 |
| Computer network design deployment and implementation tasks | 11 |
| Manufacture of metal products, tanks, reservoirs used for structures | 10 |
| Security Service | 10 |

### 4.6 Cross-tabulation of stage-1 best-confidence × outcome flag

| Stage-1 best | no_filter | unchanged | best_kept | best_changed | lost_all | row total |
|---|---:|---:|---:|---:|---:|---:|
| exact | 65 | 2 | 17 | 6 | 6 | 96 |
| high_confidence | 978 | 24 | 206 | 154 | 154 | 1,516 |
| low_similarity | 1,552 | 70 | 256 | 303 | 342 | 2,523 |
| **column total** | **2,595** | **96** | **479** | **463** | **502** | **4,135** |

(Counts derived from `All_Rows_Comparison` in the workbook.)

---

## 5. Output Files

| File | Contents |
|---|---|
| `outputs/subsector_isco_map.csv` | All 216 sub-sector mapping decisions, codes, confidence, and LLM rationale. |
| `outputs/matches_minilm.csv` | Stage-1 NEL output; not modified by this work. |
| `outputs/matches_minilm_subsector_filtered.csv` | Stage-1 output with the filter applied. Adds columns `subsector_isco4`, `filter_applied`, `n_dropped`, `dropped_labels`. |
| `outputs/ethiopia_subsector_filter_review.xlsx` | Excel review packet (companion to this document). |

---

## 6. Reproducing the run

```
python countries/ethiopia/scripts/archive/00_build_subsector_isco_map.py
python countries/ethiopia/scripts/archive/01_apply_subsector_filter.py
python countries/ethiopia/scripts/archive/02_build_review_packet.py
```

Requires `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) in the project-root `.env` for the LLM mapping step. Steps 2 and 3 are deterministic and have no LLM dependency.

These scripts live under `scripts/archive/` because the sub-sector filter is no longer part of the active pipeline (see SESSION_CONTEXT.md). They remain available for re-running the experiment or for reference.

---

## Appendix A — Sub-sector mapping LLM prompt (verbatim)

The same prompt is filled per sub-sector with `{sector}`, `{sub_sector}`, and `{isco_4digit_list}` (438 lines, one per ISCO 4-digit Unit Group, formatted as `CODE - LABEL: short description`).

```
You are mapping a sub-sector label from the Ethiopia ELMIS occupational dataset to an ISCO-08 4-digit Unit Group, so we can constrain occupation matching to the right domain.

INPUT
- Sector:     {sector}
- Sub-sector: {sub_sector}

ISCO-08 4-DIGIT UNIT GROUPS (code - label: short description):
{isco_4digit_list}

YOUR JOB
Decide whether this sub-sector maps cleanly to ONE ISCO 4-digit Unit Group.

Pick "map" only when the sub-sector clearly identifies the work domain such that constraining occupation matches to that ISCO 4-digit group (or its 3-digit parent) would correctly include the relevant occupations and exclude unrelated ones.

Pick "no_map" when the sub-sector is:
- too broad (covers multiple unrelated ISCO domains, e.g. "Health" spans doctors, nurses, technicians, managers, support staff)
- too generic (e.g. "Other services", "None", empty, "Industry Development")
- ambiguous (could plausibly map to several distinct ISCO groups with no clear winner)

If the right granularity is the 3-digit Minor Group rather than a single 4-digit Unit, still pick the closest 4-digit and say so in the rationale - downstream code will use either the 3- or 4-digit prefix to constrain matches.

OUTPUT - return ONLY valid JSON, no prose, with these exact keys:
{
  "mapping_decision": "map" | "no_map",
  "isco_code": "<4-digit code>" or null,
  "isco_label": "<label of that group>" or null,
  "confidence": "high" | "medium" | "low",
  "rationale": "<one sentence explaining the decision>",
  "fallback_isco_3digit": "<3-digit code>" or null
}

Rules:
- mapping_decision = "no_map" -> isco_code, isco_label, fallback_isco_3digit must be null
- confidence = "low" should usually be paired with "no_map"; only use "map" + "low" when there is a single best 4-digit group but the sub-sector phrasing leaves meaningful doubt
- fallback_isco_3digit is the 3-digit parent of isco_code, useful when downstream wants to widen the constraint
```

---

## Appendix B — Code generation note

ELMIS source data contains no occupation codes. For any ELMIS title that ends up with an ESCO match, the ESCO occupation's existing identifier carries the row through downstream files. Codes are generated only for new_local titles (titles with no ESCO match) at the point they are promoted to the final taxonomy. This filter run does not generate codes.
