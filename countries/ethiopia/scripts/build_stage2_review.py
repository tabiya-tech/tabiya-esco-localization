"""
Build the stage-2 review Excel for ELMIS partner review.

Combines:
  - Stage-1 auto-passes (best_score >= 0.85)  - 1,613 ELMIS titles
  - Stage-2 LLM picks                         - 1,737 matched, 783 no_match
into a single workbook with sheets for the partner team to inspect.

Output:
  outputs/ethiopia_stage2_review.xlsx

Sheets:
  README                  - sheet guide
  Summary                 - headline counts
  All_Titles              - all 4,135 ELMIS titles, final pipeline outcome
  Stage1_Auto_Passes      - 1,613 high-confidence stage-1 picks (no LLM call)
  Stage2_Matches          - 1,737 LLM-picked matches with rationale and confidence
  Stage2_No_Match         - 783 LLM-rejected -> new_local pile
  Stage2_Low_Confidence   - LLM picks where confidence = low (audit list)
"""

from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

BASE_DIR = Path(__file__).parent.parent
ROOT_DIR = BASE_DIR.parent.parent
SHARED = ROOT_DIR / "shared_data" / "esco_taxonomy"
MATCHES_CSV = BASE_DIR / "outputs" / "matches_minilm.csv"
STAGE2_CSV = BASE_DIR / "outputs" / "stage2_results.csv"
OUT = BASE_DIR / "outputs" / "ethiopia_stage2_review.xlsx"

THRESHOLD = 0.85  # stage-1 auto-pass


def load_uri_to_isco4() -> dict:
    o = pd.read_csv(SHARED / "occupations.csv", low_memory=False)
    return dict(zip(o["ORIGINURI"], o["OCCUPATIONGROUPCODE"].astype(str)))


def load_isco4_labels() -> dict:
    g = pd.read_csv(SHARED / "occupation_groups.csv")
    g4 = g[g["CODE"].astype(str).str.len() == 4]
    return dict(zip(g4["CODE"].astype(str), g4["PREFERREDLABEL"]))


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
    matches = pd.read_csv(MATCHES_CSV).fillna("")
    stage2 = pd.read_csv(STAGE2_CSV).fillna("")
    uri_to_isco4 = load_uri_to_isco4()
    isco4_labels = load_isco4_labels()

    matches["best_score"] = pd.to_numeric(matches["best_score"], errors="coerce").fillna(0.0)

    # Stage-1 auto-passes
    auto = matches[matches["best_score"] >= THRESHOLD].copy()
    auto["pipeline_outcome"] = "stage1_auto_pass"
    auto["selected_label"] = auto["m1_label"]
    auto["selected_uri"] = auto["m1_uri"]
    auto["selected_score"] = auto["best_score"]
    auto["selected_isco4"] = auto["selected_uri"].map(lambda u: str(uri_to_isco4.get(u, "")))
    auto["selected_isco_label"] = auto["selected_isco4"].map(lambda c: isco4_labels.get(c, ""))
    auto["stage2_decision"] = ""
    auto["stage2_selected_index"] = ""
    auto["stage2_confidence"] = ""
    auto["stage2_rationale"] = ""

    # Stage-2 results
    stage2_keyed = stage2.set_index("elmis_title", drop=False)

    rows = []
    # Auto-pass rows
    for _, r in auto.iterrows():
        rows.append({
            "ELMIS title": r["informal work in eng"],
            "Profession in Amharic": r["Profession in Amharic"],
            "sector": r["sector"],
            "sub sector": r["sub sector"],
            "professional/formal": r["professional/ formal"],
            "pipeline_outcome": "stage1_auto_pass",
            "stage1_best_score": r["best_score"],
            "selected_label": r["m1_label"],
            "selected_uri": r["m1_uri"],
            "selected_isco4": str(uri_to_isco4.get(r["m1_uri"], "")),
            "selected_isco_label": isco4_labels.get(str(uri_to_isco4.get(r["m1_uri"], "")), ""),
            "stage2_decision": "",
            "stage2_selected_index": "",
            "stage2_confidence": "",
            "stage2_rationale": "",
        })

    # Stage-2 rows
    sub_threshold = matches[matches["best_score"] < THRESHOLD]
    for _, r in sub_threshold.iterrows():
        title = r["informal work in eng"]
        if title not in stage2_keyed.index:
            continue
        sr = stage2_keyed.loc[title]
        if isinstance(sr, pd.DataFrame):
            sr = sr.iloc[0]

        decision = sr["stage2_decision"]
        if decision == "match":
            outcome = "stage2_match"
            sel_label = sr["stage2_selected_label"]
            sel_uri = sr["stage2_selected_uri"]
            sel_isco4 = sr["stage2_selected_isco4"]
        elif decision == "no_match":
            outcome = "stage2_no_match"
            sel_label = ""
            sel_uri = ""
            sel_isco4 = ""
        else:
            outcome = "stage2_error"
            sel_label = ""
            sel_uri = ""
            sel_isco4 = ""

        rows.append({
            "ELMIS title": title,
            "Profession in Amharic": r["Profession in Amharic"],
            "sector": r["sector"],
            "sub sector": r["sub sector"],
            "professional/formal": r["professional/ formal"],
            "pipeline_outcome": outcome,
            "stage1_best_score": r["best_score"],
            "selected_label": sel_label,
            "selected_uri": sel_uri,
            "selected_isco4": str(sel_isco4) if sel_isco4 else "",
            "selected_isco_label": isco4_labels.get(str(sel_isco4), "") if sel_isco4 else "",
            "stage2_decision": decision,
            "stage2_selected_index": sr["stage2_selected_index"],
            "stage2_confidence": sr["stage2_confidence"],
            "stage2_rationale": sr["stage2_rationale"],
        })

    all_df = pd.DataFrame(rows)
    print(f"  Combined rows: {len(all_df)}")

    # Subset sheets
    stage1_auto = all_df[all_df["pipeline_outcome"] == "stage1_auto_pass"].drop(
        columns=["stage2_decision", "stage2_selected_index", "stage2_confidence", "stage2_rationale"]
    )
    stage2_match = all_df[all_df["pipeline_outcome"] == "stage2_match"].copy()
    stage2_no_match = all_df[all_df["pipeline_outcome"] == "stage2_no_match"].drop(
        columns=["selected_label", "selected_uri", "selected_isco4", "selected_isco_label"]
    )
    stage2_low_conf = all_df[
        (all_df["pipeline_outcome"] == "stage2_match") & (all_df["stage2_confidence"] == "low")
    ].copy()

    # Stage-2 match: also include the 5 stage-1 candidate labels for context
    stage1_lookup = matches.set_index("informal work in eng", drop=False)
    def candidates_text(title: str) -> str:
        if title not in stage1_lookup.index:
            return ""
        r = stage1_lookup.loc[title]
        if isinstance(r, pd.DataFrame):
            r = r.iloc[0]
        parts = []
        for k in range(1, 6):
            label = r.get(f"m{k}_label", "")
            score = r.get(f"m{k}_score", "")
            if label:
                parts.append(f"{k}. {label} ({score})")
        return " | ".join(parts)

    stage2_match["stage1_candidates"] = stage2_match["ELMIS title"].map(candidates_text)
    stage2_low_conf["stage1_candidates"] = stage2_low_conf["ELMIS title"].map(candidates_text)

    # Summary
    total = len(all_df)
    counts = all_df["pipeline_outcome"].value_counts()
    summary = [
        ("PIPELINE OUTCOME", "Count", "% of total"),
        ("Total ELMIS titles", total, "100%"),
        ("", "", ""),
        ("Stage-1 auto-pass (best_score >= 0.85)", int(counts.get("stage1_auto_pass", 0)),
         f"{100 * counts.get('stage1_auto_pass', 0) / total:.1f}%"),
        ("Stage-2 LLM match", int(counts.get("stage2_match", 0)),
         f"{100 * counts.get('stage2_match', 0) / total:.1f}%"),
        ("Stage-2 no_match (-> new_local)", int(counts.get("stage2_no_match", 0)),
         f"{100 * counts.get('stage2_no_match', 0) / total:.1f}%"),
        ("Stage-2 errors (re-run needed)", int(counts.get("stage2_error", 0)),
         f"{100 * counts.get('stage2_error', 0) / total:.1f}%" if counts.get('stage2_error', 0) else "0%"),
        ("", "", ""),
        ("ESCO-MATCHED (auto + LLM match)",
         int(counts.get("stage1_auto_pass", 0) + counts.get("stage2_match", 0)),
         f"{100 * (counts.get('stage1_auto_pass', 0) + counts.get('stage2_match', 0)) / total:.1f}%"),
        ("", "", ""),
        ("STAGE-2 LLM CONFIDENCE", "match", "no_match"),
    ]
    s2_conf_match = all_df[all_df["pipeline_outcome"] == "stage2_match"]["stage2_confidence"].value_counts()
    s2_conf_no = all_df[all_df["pipeline_outcome"] == "stage2_no_match"]["stage2_confidence"].value_counts()
    for lvl in ["high", "medium", "low"]:
        summary.append((f"  {lvl}", int(s2_conf_match.get(lvl, 0)), int(s2_conf_no.get(lvl, 0))))

    readme = [
        ("Sheet", "Contents"),
        ("README", "This sheet."),
        ("Summary", "Headline counts: per-stage outcomes and stage-2 confidence breakdown."),
        ("All_Titles", "All 4,135 ELMIS titles with their final pipeline outcome and matched ESCO occupation."),
        ("Stage1_Auto_Passes", f"Titles where stage-1 NEL classifier scored >= {THRESHOLD}; auto-accepted, no LLM call."),
        ("Stage2_Matches", "Titles sent to stage-2 LLM that the LLM mapped to one of the 5 stage-1 candidates. Includes rationale, confidence, and the original 5 candidates for review."),
        ("Stage2_No_Match", "Titles the LLM rejected as not matching any of the 5 candidates. These go to stage-4 new_local promotion."),
        ("Stage2_Low_Confidence", "Subset of Stage2_Matches where the LLM marked the pick as 'low' confidence. Audit list."),
        ("", ""),
        ("Pipeline outcomes", ""),
        ("  stage1_auto_pass", f"Stage-1 best_score >= {THRESHOLD}"),
        ("  stage2_match", "Stage-2 LLM picked one of the 5 candidates"),
        ("  stage2_no_match", "Stage-2 LLM said no candidate matches; route to new_local"),
        ("  stage2_error", "Stage-2 LLM call failed (none expected after retry)"),
        ("", ""),
        ("Stage-1 thresholds", ""),
        ("  exact", "score >= 0.95"),
        ("  high_confidence", "0.85 <= score < 0.95 (auto-passed)"),
        ("  low_similarity", "score < 0.85 (sent to stage-2 LLM)"),
        ("", ""),
        ("LLM provider", "Gemini 3 Flash (gemini-3-flash-preview). Configurable via config.json llm.provider."),
    ]

    print(f"Writing {OUT}")
    with pd.ExcelWriter(OUT, engine="openpyxl") as writer:
        pd.DataFrame(readme[1:], columns=readme[0]).to_excel(writer, sheet_name="README", index=False)
        pd.DataFrame(summary, columns=["Metric", "Value", "Detail"]).to_excel(writer, sheet_name="Summary", index=False)
        all_df.to_excel(writer, sheet_name="All_Titles", index=False)
        stage1_auto.to_excel(writer, sheet_name="Stage1_Auto_Passes", index=False)
        stage2_match.to_excel(writer, sheet_name="Stage2_Matches", index=False)
        stage2_no_match.to_excel(writer, sheet_name="Stage2_No_Match", index=False)
        stage2_low_conf.to_excel(writer, sheet_name="Stage2_Low_Confidence", index=False)

        # Styling
        for sheet_name in writer.sheets:
            ws = writer.sheets[sheet_name]
            for cell in ws[1]:
                cell.font = Font(bold=True)
                cell.alignment = Alignment(vertical="center", wrap_text=True)
            ws.freeze_panes = "A2"
            autosize(ws)

        # Color the pipeline_outcome column on All_Titles
        ws = writer.sheets["All_Titles"]
        headers = [c.value for c in ws[1]]
        if "pipeline_outcome" in headers:
            col = headers.index("pipeline_outcome") + 1
            green = PatternFill("solid", fgColor="C6EFCE")
            yellow = PatternFill("solid", fgColor="FFF2CC")
            red = PatternFill("solid", fgColor="F8CBAD")
            for row_i in range(2, ws.max_row + 1):
                cell = ws.cell(row=row_i, column=col)
                v = cell.value
                if v == "stage1_auto_pass":
                    cell.fill = green
                elif v == "stage2_match":
                    cell.fill = yellow
                elif v == "stage2_no_match":
                    cell.fill = red

    size_mb = OUT.stat().st_size / (1024 * 1024)
    print(f"Done. {size_mb:.2f} MB")


if __name__ == "__main__":
    main()
