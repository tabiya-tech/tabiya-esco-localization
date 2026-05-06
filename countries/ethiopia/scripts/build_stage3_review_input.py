"""
Build the human-review (stage 3) input file for Ethiopia ELMIS.

Pulls every ELMIS title that needs human attention:
  - Stage-2 no_match (will become new_local unless reviewer overrides)
  - Stage-2 match with confidence = low  or  confidence = medium

Each row is enriched with:
  - The full top-5 NEL candidates (label, ISCO, score, description) for context
  - The stage-2 LLM's pick (if any) and its rationale
  - The exploratory expanded-pool retry pick (if available) as a side-channel hint
  - A blank `reviewer_decision` column with controlled vocabulary

Output:
  outputs/stage3_review_input.xlsx

Sheets:
  README             - reviewer instructions
  Review_Items       - the working sheet (one row per title)
  Lookups            - reference tables (ISCO, decision values)
"""

from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

BASE_DIR = Path(__file__).parent.parent
ROOT_DIR = BASE_DIR.parent.parent
SHARED = ROOT_DIR / "shared_data" / "esco_taxonomy"
STAGE2 = BASE_DIR / "outputs" / "stage2_results.csv"
RETRY = BASE_DIR / "outputs" / "stage2_no_match_retry.csv"
MATCHES = BASE_DIR / "outputs" / "matches_minilm.csv"
OUT = BASE_DIR / "outputs" / "stage3_review_input.xlsx"

DECISION_VALUES = [
    "APPROVE_LLM_PICK",
    "USE_DIFFERENT_ESCO",
    "NEW_LOCAL",
    "SKIP",
]


def load_uri_to_isco4_label() -> tuple[dict, dict]:
    o = pd.read_csv(SHARED / "occupations.csv", low_memory=False)
    uri_isco4 = dict(zip(o["ORIGINURI"], o["OCCUPATIONGROUPCODE"].astype(str)))
    g = pd.read_csv(SHARED / "occupation_groups.csv")
    g4 = g[g["CODE"].astype(str).str.len() == 4]
    isco4_labels = dict(zip(g4["CODE"].astype(str), g4["PREFERREDLABEL"]))
    return uri_isco4, isco4_labels


def autosize(ws, max_w: int = 60):
    for col in ws.columns:
        letter = get_column_letter(col[0].column)
        try:
            longest = max(len(str(c.value)) if c.value is not None else 0 for c in col)
        except Exception:
            longest = 12
        ws.column_dimensions[letter].width = min(max(longest + 2, 10), max_w)


def main():
    print("Loading inputs...")
    stage2 = pd.read_csv(STAGE2).fillna("")
    matches = pd.read_csv(MATCHES).fillna("")
    matches_idx = matches.set_index("informal work in eng", drop=False)
    retry = pd.read_csv(RETRY).fillna("") if RETRY.exists() else pd.DataFrame()
    retry_idx = retry.set_index("elmis_title", drop=False) if not retry.empty else None
    uri_isco4, isco4_labels = load_uri_to_isco4_label()

    # Filter: stage-2 no_match OR (match AND conf in {low, medium})
    review = stage2[
        (stage2["stage2_decision"] == "no_match")
        | ((stage2["stage2_decision"] == "match") & (stage2["stage2_confidence"].isin(["low", "medium"])))
    ].copy()
    print(f"  Review pile: {len(review)}")

    rows = []
    for _, r in review.iterrows():
        title = r["elmis_title"]
        decision = r["stage2_decision"]
        conf = r["stage2_confidence"]
        if decision == "no_match":
            why = "stage2_no_match"
        elif conf == "low":
            why = "stage2_match_low_confidence"
        else:
            why = "stage2_match_medium_confidence"

        match_row = matches_idx.loc[title] if title in matches_idx.index else None
        if isinstance(match_row, pd.DataFrame):
            match_row = match_row.iloc[0]

        out = {
            "ELMIS title (EN)": title,
            "Profession in Amharic": r["amharic"],
            "sector": r["sector"],
            "sub sector": r["sub_sector"],
            "professional/formal": r["professional_formal"],
            "why_in_review": why,
            "stage2_decision": decision,
            "stage2_LLM_pick_label": r["stage2_selected_label"],
            "stage2_LLM_pick_uri": r["stage2_selected_uri"],
            "stage2_LLM_pick_isco4": r["stage2_selected_isco4"],
            "stage2_LLM_confidence": conf,
            "stage2_LLM_rationale": r["stage2_rationale"],
            "stage1_best_score": r["stage1_best_score"],
        }

        # All 5 NEL candidates (for review context)
        if match_row is not None:
            for k in range(1, 6):
                label = match_row.get(f"m{k}_label", "")
                uri = match_row.get(f"m{k}_uri", "")
                score = match_row.get(f"m{k}_score", "")
                isco4 = uri_isco4.get(uri, "") if uri else ""
                isco_lbl = isco4_labels.get(isco4, "") if isco4 else ""
                out[f"NEL_cand_{k}_label"] = label
                out[f"NEL_cand_{k}_score"] = score
                out[f"NEL_cand_{k}_isco4"] = isco4
                out[f"NEL_cand_{k}_isco_label"] = isco_lbl
        else:
            for k in range(1, 6):
                out[f"NEL_cand_{k}_label"] = ""
                out[f"NEL_cand_{k}_score"] = ""
                out[f"NEL_cand_{k}_isco4"] = ""
                out[f"NEL_cand_{k}_isco_label"] = ""

        # Exploratory expanded-pool retry (only for no_match items in mapped sub-sectors)
        if retry_idx is not None and title in retry_idx.index:
            rr = retry_idx.loc[title]
            if isinstance(rr, pd.DataFrame):
                rr = rr.iloc[0]
            out["expanded_pool_retry_decision"] = rr["retry_decision"]
            out["expanded_pool_retry_pick_label"] = rr["retry_selected_label"]
            out["expanded_pool_retry_pick_isco4"] = rr["retry_selected_isco4"]
            out["expanded_pool_retry_pick_source"] = rr["retry_pick_source"]
            out["expanded_pool_retry_confidence"] = rr["retry_confidence"]
            out["expanded_pool_retry_rationale"] = rr["retry_rationale"]
        else:
            out["expanded_pool_retry_decision"] = ""
            out["expanded_pool_retry_pick_label"] = ""
            out["expanded_pool_retry_pick_isco4"] = ""
            out["expanded_pool_retry_pick_source"] = ""
            out["expanded_pool_retry_confidence"] = ""
            out["expanded_pool_retry_rationale"] = ""

        # Reviewer columns (empty)
        out["reviewer_decision"] = ""           # APPROVE_LLM_PICK | USE_DIFFERENT_ESCO | NEW_LOCAL | SKIP
        out["reviewer_esco_label"] = ""          # if USE_DIFFERENT_ESCO, the ESCO label
        out["reviewer_esco_uri"] = ""            # if USE_DIFFERENT_ESCO, the ESCO URI
        out["reviewer_notes"] = ""

        rows.append(out)

    df = pd.DataFrame(rows)

    # Sort: no_match first (most action needed), then medium, then low
    order = {"stage2_no_match": 0, "stage2_match_low_confidence": 1, "stage2_match_medium_confidence": 2}
    df["_sort"] = df["why_in_review"].map(order)
    df = df.sort_values(["_sort", "sector", "sub sector", "ELMIS title (EN)"]).drop(columns=["_sort"]).reset_index(drop=True)

    # Counts for README/Summary
    counts = df["why_in_review"].value_counts()

    readme = [
        ("Section", "Detail"),
        ("Purpose", "Stage-3 human review of Ethiopia ELMIS titles that need a human decision."),
        ("Total items", str(len(df))),
        ("", ""),
        ("Buckets", ""),
        ("  stage2_no_match", f"{int(counts.get('stage2_no_match', 0))}  - LLM said none of the 5 NEL candidates match. If reviewer agrees: NEW_LOCAL."),
        ("  stage2_match_medium_confidence", f"{int(counts.get('stage2_match_medium_confidence', 0))}  - LLM picked a candidate but flagged medium confidence. Verify or override."),
        ("  stage2_match_low_confidence", f"{int(counts.get('stage2_match_low_confidence', 0))}  - LLM picked a candidate but flagged low confidence. Verify or override."),
        ("", ""),
        ("How to review (per row in Review_Items sheet)", ""),
        ("  1. Read the ELMIS title and sector/sub-sector context.", ""),
        ("  2. Look at the 5 NEL candidates (NEL_cand_1..5) and the stage-2 LLM's pick.", ""),
        ("  3. For no_match rows: the expanded_pool_retry_* columns may suggest an alternative ESCO match (this is exploratory, not authoritative).", ""),
        ("  4. Set reviewer_decision to one of:", ""),
        ("       APPROVE_LLM_PICK     - accept the LLM's stage-2 pick.", ""),
        ("       USE_DIFFERENT_ESCO   - pick a different ESCO occupation. Fill reviewer_esco_label and reviewer_esco_uri.", ""),
        ("       NEW_LOCAL            - no ESCO equivalent. Will become a new local occupation in the Ethiopia taxonomy.", ""),
        ("       SKIP                 - drop this title from the taxonomy entirely.", ""),
        ("  5. (Optional) Add reviewer_notes for context the next person needs.", ""),
        ("", ""),
        ("Decision rules of thumb", ""),
        ("  - If the LLM's pick looks correct, APPROVE_LLM_PICK is fine - the rationale is in stage2_LLM_rationale.", ""),
        ("  - If a NEL candidate other than the LLM's pick is clearly better, use USE_DIFFERENT_ESCO.", ""),
        ("  - If the role is genuinely Ethiopia-specific (e.g. cultural / informal-economy job not represented in ESCO), use NEW_LOCAL.", ""),
        ("", ""),
        ("Output", "After review, save this file. The next pipeline step ingests reviewer_decision and updates the canonical taxonomy outputs."),
    ]

    print(f"Writing {OUT}")
    with pd.ExcelWriter(OUT, engine="openpyxl") as writer:
        pd.DataFrame(readme[1:], columns=readme[0]).to_excel(writer, sheet_name="README", index=False)
        df.to_excel(writer, sheet_name="Review_Items", index=False)

        # Lookups sheet
        lookups = [
            ("Allowed reviewer_decision values", ""),
            ("APPROVE_LLM_PICK", "Accept the stage-2 LLM's pick as the correct ESCO match."),
            ("USE_DIFFERENT_ESCO", "Override with a different ESCO occupation (fill reviewer_esco_label/uri)."),
            ("NEW_LOCAL", "No ESCO equivalent; promote as new local occupation."),
            ("SKIP", "Exclude this title from the taxonomy."),
        ]
        pd.DataFrame(lookups[1:], columns=lookups[0]).to_excel(writer, sheet_name="Lookups", index=False)

        # Styling
        for sheet_name in writer.sheets:
            ws = writer.sheets[sheet_name]
            for cell in ws[1]:
                cell.font = Font(bold=True)
                cell.alignment = Alignment(vertical="center", wrap_text=True)
            ws.freeze_panes = "A2"
            autosize(ws)

        # Color-code the why_in_review column
        ws = writer.sheets["Review_Items"]
        headers = [c.value for c in ws[1]]
        red = PatternFill("solid", fgColor="F8CBAD")
        yellow = PatternFill("solid", fgColor="FFF2CC")
        orange = PatternFill("solid", fgColor="FCE4D6")
        if "why_in_review" in headers:
            col = headers.index("why_in_review") + 1
            for row_i in range(2, ws.max_row + 1):
                cell = ws.cell(row=row_i, column=col)
                v = cell.value
                if v == "stage2_no_match":
                    cell.fill = red
                elif v == "stage2_match_medium_confidence":
                    cell.fill = yellow
                elif v == "stage2_match_low_confidence":
                    cell.fill = orange

        # Data validation on reviewer_decision: dropdown of allowed values
        if "reviewer_decision" in headers:
            col_idx = headers.index("reviewer_decision") + 1
            col_letter = get_column_letter(col_idx)
            dv = DataValidation(type="list", formula1=f'"{",".join(DECISION_VALUES)}"', allow_blank=True)
            dv.error = "Allowed: APPROVE_LLM_PICK, USE_DIFFERENT_ESCO, NEW_LOCAL, SKIP"
            dv.errorTitle = "Invalid decision"
            ws.add_data_validation(dv)
            dv.add(f"{col_letter}2:{col_letter}{ws.max_row}")

    size_mb = OUT.stat().st_size / (1024 * 1024)
    print(f"Done. {size_mb:.2f} MB")
    print()
    print(f"Bucket counts:")
    for bucket, n in counts.items():
        print(f"  {bucket}: {n}")
    print(f"  total: {len(df)}")


if __name__ == "__main__":
    main()
