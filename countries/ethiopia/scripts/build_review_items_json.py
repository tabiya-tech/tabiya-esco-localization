"""
Build the loader-compatible review_items.json for the Ethiopia review project.

The Tabiya review_app's loader (review_app/scripts/load_project_data.py) ingests
a JSON file matching: outputs/*_review_items.json with shape:

    {
      "metadata": {...},
      "items": [
        {
          "elmis_code":           "<5-digit zero-padded id>",
          "elmis_title":          "<English title>",
          "isco_code":            "<ISCO 4-digit or empty>",
          "esco_code":            "<ESCO occupation CODE if a stage-2 match exists>",
          "esco_label":           "<ESCO preferred label>",
          "similarity":           <stage1 best_score>,
          "category":             "<bucket>",
          "review_reason":        "<bucket>"
        }, ...
      ]
    }

Code scheme:
  ELMIS source has no codes. We mint synthetic 5-digit zero-padded ids based on
  position in the original output_with_sectors.csv (00001..04135). Extensible
  to 99,999 when ELMIS scales to the full ~23,000-title superset.

Review pile (matches stage3_review_input.xlsx contents):
  - stage-2 no_match
  - stage-2 match with confidence in {low, medium}

Output: outputs/ethiopia_elmis_review_items.json
"""

import json
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).parent.parent
ROOT_DIR = BASE_DIR.parent.parent
SHARED = ROOT_DIR / "shared_data" / "esco_taxonomy"
SOURCE_CSV = BASE_DIR / "data" / "output_with_sectors.csv"
STAGE2_CSV = BASE_DIR / "outputs" / "stage2_results.csv"
OUT = BASE_DIR / "outputs" / "ethiopia_elmis_review_items.json"


def load_uri_lookups() -> tuple[dict, dict]:
    """uri -> (esco_code, isco_code)."""
    o = pd.read_csv(SHARED / "occupations.csv", low_memory=False)
    uri_to_code = dict(zip(o["ORIGINURI"], o["CODE"]))
    uri_to_isco = dict(zip(o["ORIGINURI"], o["OCCUPATIONGROUPCODE"].astype(str)))
    return uri_to_code, uri_to_isco


def main():
    print("Loading source + stage-2 results...")
    source = pd.read_csv(SOURCE_CSV).fillna("")
    source = source.reset_index(drop=True)
    source["elmis_code"] = source.index.map(lambda i: f"{i + 1:05d}")
    title_to_code = dict(zip(source["informal work in eng"].str.strip(), source["elmis_code"]))

    stage2 = pd.read_csv(STAGE2_CSV).fillna("")

    review = stage2[
        (stage2["stage2_decision"] == "no_match")
        | ((stage2["stage2_decision"] == "match") & (stage2["stage2_confidence"].isin(["low", "medium"])))
    ].copy()
    print(f"  Review pile: {len(review)}")

    uri_to_code, uri_to_isco = load_uri_lookups()

    items = []
    skipped = 0
    for _, r in review.iterrows():
        title = str(r["elmis_title"]).strip()
        code = title_to_code.get(title)
        if not code:
            skipped += 1
            continue

        decision = r["stage2_decision"]
        conf = r["stage2_confidence"]
        if decision == "no_match":
            bucket = "stage2_no_match"
            esco_code = ""
            esco_label = ""
            isco_code = ""
        else:
            bucket = f"stage2_match_{conf}_confidence"
            uri = r["stage2_selected_uri"]
            esco_code = uri_to_code.get(uri, "")
            esco_label = r["stage2_selected_label"]
            isco_code = r["stage2_selected_isco4"] or uri_to_isco.get(uri, "")

        try:
            similarity = float(r["stage1_best_score"]) if r["stage1_best_score"] != "" else None
        except ValueError:
            similarity = None

        items.append({
            "elmis_code": code,
            "elmis_title": title,
            "sector": str(r.get("sector", "")).strip(),
            "sub_sector": str(r.get("sub_sector", "")).strip(),
            "isco_code": str(isco_code) if isco_code else "",
            "esco_code": str(esco_code) if esco_code else "",
            "esco_label": esco_label,
            "similarity": similarity,
            "category": bucket,
            "review_reason": bucket,
        })

    if skipped:
        print(f"  WARNING: {skipped} review rows could not be matched back to source by title")

    payload = {
        "metadata": {
            "country": "Ethiopia",
            "source_taxonomy": "ELMIS",
            "total_items": len(items),
            "code_scheme": "5-digit zero-padded synthetic id (00001..99999) based on row position in output_with_sectors.csv",
            "review_pile": "stage-2 no_match + stage-2 match with confidence in {low, medium}",
        },
        "items": items,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"Written: {OUT}  ({len(items)} items)")

    bucket_counts = {}
    for it in items:
        bucket_counts[it["category"]] = bucket_counts.get(it["category"], 0) + 1
    print("Bucket counts:")
    for b, n in sorted(bucket_counts.items()):
        print(f"  {b}: {n}")


if __name__ == "__main__":
    main()
