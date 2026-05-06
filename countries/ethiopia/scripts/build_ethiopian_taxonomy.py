"""
Build a localised occupations taxonomy dataset.

Downloads the full taxonomy export from the Taxonomy API, then enriches
occupations.csv using a list of local job titles linked via the NEL v2 service:
  - Each matched title is appended as an extra alt-label on the matched occupation.
  - A CONFIDENCE column is added recording the best match confidence per occupation.

All other taxonomy files (skills, relations, hierarchy, etc.) are written
unchanged from the export.

Resumable: progress is saved after each batch. If interrupted (e.g. by a rate
limit), just re-run the same command to pick up where it left off.

Requirements:
    pip install requests

Input CSV format (columns):
    "informal work in eng"   — English job title  (required)
    "Profession in Amharic"  — Amharic title       (optional)

Usage:
    python build_ethiopian_taxonomy.py --input <job_titles.csv> [--nel-api-key KEY]

    --input PATH              CSV of job titles  (required)
    --taxonomy-model-id ID    Taxonomy model ID (default: $TAXONOMY_MODEL_ID)
    --nel-api-key KEY         API key for the NEL service — required when using the
                        deployed endpoint; not needed for local.
                        Can also be set via the NEL_API_KEY environment variable.
    --output-dir DIR    Where to write the output files
                        (default: ./ethiopian_taxonomy/ next to this script)
    --nel-url URL       NEL v2 base URL  (default: http://localhost:5003)
                        Override to point at a deployed endpoint, e.g.
                        https://dev.classifier.tabiya.tech
"""

import argparse
import csv
import io
import json
import os
import sys
import time
import zipfile
from collections import defaultdict

import requests

# ── Confidence thresholds ─────────────────────────────────────────────────────
EXACT_THRESHOLD = 0.95
HIGH_CONF_THRESHOLD = 0.85
MIN_SIMILARITY = 0.50

CONFIDENCE_RANK = {"exact": 3, "high_confidence": 2, "low_similarity": 1}

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_NEL_URL = "http://localhost:5003"
DEFAULT_TAXONOMY_URL = "https://taxonomy.tabiya.tech"
NEL_BATCH_SIZE = 100

# Retry config for 429 / transient errors
_MAX_RETRIES = 6
_RETRY_BASE_DELAY = 10.0  # seconds; doubles each attempt


# ── Confidence helper ─────────────────────────────────────────────────────────

def confidence_level(score: float) -> str:
    if score >= EXACT_THRESHOLD:
        return "exact"
    if score >= HIGH_CONF_THRESHOLD:
        return "high_confidence"
    return "low_similarity"


# ── Taxonomy download ─────────────────────────────────────────────────────────

def fetch_taxonomy_zip(taxonomy_url: str, taxonomy_key: str, model_id: str) -> zipfile.ZipFile:
    """
    Fetches the pre-built CSV export ZIP for the given model from the Taxonomy API.
    Returns an in-memory ZipFile ready to read.
    """
    base = taxonomy_url.rstrip("/") + "/api/app"
    headers = {"X-API-Key": taxonomy_key} if taxonomy_key else {}

    print(f"Fetching taxonomy model {model_id} from {taxonomy_url}...")
    resp = requests.get(f"{base}/models", headers=headers, timeout=30)
    resp.raise_for_status()
    models = resp.json()

    model = next((m for m in models if m["id"] == model_id), None)
    if model is None:
        print(f"[ERROR] Model {model_id!r} not found.", file=sys.stderr)
        print(f"  Available: {[m['id'] for m in models]}", file=sys.stderr)
        sys.exit(1)

    completed = [
        e for e in (model.get("exportProcessState") or [])
        if e.get("status") == "completed" and e.get("downloadUrl", "").startswith("https://")
    ]
    if not completed:
        print(f"[ERROR] No completed export found for model {model_id}.", file=sys.stderr)
        sys.exit(1)

    export = sorted(completed, key=lambda e: e.get("updatedAt", ""), reverse=True)[0]
    download_url = export["downloadUrl"]

    print(f"  {model.get('name', '')} {model.get('version', '')}  (export: {export.get('updatedAt', '')[:10]})")
    print(f"  Downloading...", end=" ", flush=True)

    zip_resp = requests.get(download_url, timeout=120)
    zip_resp.raise_for_status()
    print(f"{len(zip_resp.content) // 1024} KB")

    return zipfile.ZipFile(io.BytesIO(zip_resp.content))


def read_csv_from_zip(zf: zipfile.ZipFile, filename: str) -> list[dict]:
    with zf.open(filename) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8")
        return list(csv.DictReader(text))


# ── Checkpoint helpers ────────────────────────────────────────────────────────

def load_checkpoint(checkpoint_path: str) -> dict:
    if os.path.exists(checkpoint_path):
        with open(checkpoint_path, encoding="utf-8") as f:
            return json.load(f)
    return {"matched": [], "unmatched": [], "next_index": 0}


def save_checkpoint(checkpoint_path: str, matched: list[dict], unmatched: list[dict], next_index: int) -> None:
    tmp = checkpoint_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"matched": matched, "unmatched": unmatched, "next_index": next_index}, f)
    os.replace(tmp, checkpoint_path)  # atomic on POSIX


# ── NEL v2 linking ────────────────────────────────────────────────────────────

def nel_link_batch(session: requests.Session, nel_url: str, titles: list[str], nel_api_key: str = "") -> list[dict]:
    payload = {
        "entities": [{"text": title, "entity_type": "occupation"} for title in titles],
        "top_k": 1,
        "min_similarity": MIN_SIMILARITY,
    }
    headers = {"X-API-Key": nel_api_key} if nel_api_key else {}
    delay = _RETRY_BASE_DELAY
    for attempt in range(1, _MAX_RETRIES + 1):
        resp = session.post(nel_url, json=payload, headers=headers, timeout=120)
        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt == _MAX_RETRIES:
                resp.raise_for_status()
            print(f"\n  [{resp.status_code}] Retrying in {delay:.0f}s ({attempt}/{_MAX_RETRIES})...", end="", flush=True)
            time.sleep(delay)
            delay *= 2
            continue
        resp.raise_for_status()
        return resp.json()["linked_entities"]
    raise RuntimeError("NEL batch failed after all retries")


def link_titles(
    input_rows: list[dict],
    title_column: str,
    amharic_column: str,
    nel_url: str,
    nel_api_key: str,
    checkpoint_path: str,
) -> tuple[list[dict], list[dict]]:
    """
    Links job titles to ESCO occupations via NEL v2. Checkpoints after each batch.

    Returns:
        matched   — [{title_en, title_am, origin_uri, preferred_label, similarity_score, confidence}]
        unmatched — [{title_en, title_am, similarity_score, ...any extra columns}]
    """
    checkpoint = load_checkpoint(checkpoint_path)
    matched: list[dict] = checkpoint["matched"]
    unmatched: list[dict] = checkpoint["unmatched"]
    start_index: int = checkpoint["next_index"]
    total = len(input_rows)

    if start_index > 0:
        print(f"  Resuming from row {start_index}/{total}")

    session = requests.Session()

    for batch_start in range(start_index, total, NEL_BATCH_SIZE):
        batch = input_rows[batch_start : batch_start + NEL_BATCH_SIZE]
        titles = [row[title_column].strip() for row in batch]

        try:
            linked_entities = nel_link_batch(session, nel_url, titles, nel_api_key)
        except requests.RequestException as err:
            print(f"\n[ERROR] NEL request failed: {err}", file=sys.stderr)
            print(f"  Progress saved — re-run to resume from row {batch_start}.", file=sys.stderr)
            sys.exit(1)

        for row, entity in zip(batch, linked_entities):
            title_en = row[title_column].strip()
            title_am = row.get(amharic_column, "").strip()
            if entity["matches"]:
                top = entity["matches"][0]
                score = top["similarity_score"]
                matched.append({
                    "title_en": title_en,
                    "title_am": title_am,
                    "origin_uri": top["entity"]["origin_uri"],
                    "preferred_label": top["entity"]["preferred_label"],
                    "similarity_score": score,
                    "confidence": confidence_level(score),
                })
            else:
                unmatched.append({
                    "title_en": title_en,
                    "title_am": title_am,
                    "similarity_score": 0.0,
                })

        next_index = min(batch_start + NEL_BATCH_SIZE, total)
        save_checkpoint(checkpoint_path, matched, unmatched, next_index)
        print(f"  {next_index}/{total} titles processed...", end="\r", flush=True)
        time.sleep(0.05)

    print()
    return matched, unmatched


# ── Occupation enrichment ─────────────────────────────────────────────────────

def enrich_occupations(
    source_rows: list[dict],
    output_path: str,
    matched: list[dict],
) -> int:
    """
    Write enriched occupations.csv: appends matched titles as extra alt-labels
    and adds a CONFIDENCE column. Matching is by ORIGINURI.

    Returns the number of occupations that received at least one local title.
    """
    extra_labels_en: dict[str, list[str]] = defaultdict(list)
    extra_labels_am: dict[str, list[str]] = defaultdict(list)
    best_confidence: dict[str, str] = {}

    for title_match in matched:
        uri = title_match["origin_uri"]
        conf = title_match["confidence"]

        if title_match["title_en"] not in extra_labels_en[uri]:
            extra_labels_en[uri].append(title_match["title_en"])
        if title_match["title_am"] and title_match["title_am"] not in extra_labels_am[uri]:
            extra_labels_am[uri].append(title_match["title_am"])
        if CONFIDENCE_RANK.get(conf, 0) > CONFIDENCE_RANK.get(best_confidence.get(uri, ""), 0):
            best_confidence[uri] = conf

    original_fields = list(source_rows[0].keys()) if source_rows else []
    output_fields = original_fields + ["CONFIDENCE"]
    enriched_count = 0

    with open(output_path, "w", newline="", encoding="utf-8") as out_file:
        writer = csv.DictWriter(out_file, fieldnames=output_fields, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for row in source_rows:
            uri = row.get("ORIGINURI", "")
            extra_en = extra_labels_en.get(uri, [])
            extra_am = extra_labels_am.get(uri, [])

            if extra_en or extra_am:
                existing = row.get("ALTLABELS", "")
                additions = "\n".join(extra_en + extra_am)
                row["ALTLABELS"] = (existing + "\n" + additions).strip("\n") if existing else additions
                enriched_count += 1

            row["CONFIDENCE"] = best_confidence.get(uri, "")
            writer.writerow(row)

    return enriched_count


# ── Write helpers ─────────────────────────────────────────────────────────────

def write_file_from_zip(zf: zipfile.ZipFile, filename: str, output_dir: str) -> None:
    output_path = os.path.join(output_dir, filename)
    with zf.open(filename) as src, open(output_path, "wb") as dst:
        dst.write(src.read())



# ── Args ──────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a localised occupations taxonomy by linking job titles to ESCO via NEL v2.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--input", required=True, help="CSV file of job titles to link")
    parser.add_argument(
        "--taxonomy-model-id",
        default=os.environ.get("TAXONOMY_MODEL_ID", ""),
        help="Taxonomy model ID (default: $TAXONOMY_MODEL_ID)",
    )
    parser.add_argument(
        "--nel-url",
        default=os.environ.get("NEL_API_URL", DEFAULT_NEL_URL),
        help="NEL v2 base URL (default: http://localhost:5003)",
    )
    parser.add_argument(
        "--nel-api-key",
        default=os.environ.get("NEL_API_KEY", ""),
        help="API key for the NEL service (required for deployed endpoints)",
    )
    parser.add_argument(
        "--output-dir",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "ethiopian_taxonomy"),
        help="Output directory (default: ./ethiopian_taxonomy/)",
    )
    return parser.parse_args()


TITLE_COLUMN = "informal work in eng"
AMHARIC_COLUMN = "Profession in Amharic"


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()

    nel_base = args.nel_url.rstrip("/")
    nel_endpoint = f"{nel_base}/v2/nel"
    nel_api_key = args.nel_api_key

    # ── Check NEL service ─────────────────────────────────────────────────────
    print(f"Checking NEL v2 service at {nel_base}...")
    try:
        health = requests.get(f"{nel_base}/v2/nel/health", timeout=10)
        health.raise_for_status()
    except requests.RequestException as err:
        print(f"[ERROR] NEL service not reachable: {err}", file=sys.stderr)
        sys.exit(1)

    # /v2/nel/user/config requires Firebase auth on deployed endpoints, so only
    # call it locally (no API key). For deployed use, fall back to TAXONOMY_MODEL_ID.
    taxonomy_model_id = args.taxonomy_model_id
    if not nel_api_key:
        try:
            config_resp = requests.get(f"{nel_base}/v2/nel/user/config", timeout=10)
            config_resp.raise_for_status()
            cfg = config_resp.json()
            print(f"  NEL model:      {cfg.get('nel_model_id', 'unknown')}")
            print(f"  Taxonomy model: {cfg.get('taxonomy_model_id', 'unknown')}")
            taxonomy_model_id = cfg.get("taxonomy_model_id", "") or taxonomy_model_id
        except requests.RequestException:
            pass  # not fatal — taxonomy_model_id may still be set via env var

    if not taxonomy_model_id:
        print("[ERROR] Could not determine taxonomy model ID.", file=sys.stderr)
        print("  Set the TAXONOMY_MODEL_ID environment variable and try again.", file=sys.stderr)
        sys.exit(1)

    # ── Download taxonomy export ──────────────────────────────────────────────
    taxonomy_api_key = os.environ.get("TAXONOMY_API_KEY", "")
    taxonomy_url = os.environ.get("TAXONOMY_API_BASE_URL", DEFAULT_TAXONOMY_URL)
    taxonomy_zip = fetch_taxonomy_zip(taxonomy_url, taxonomy_api_key, taxonomy_model_id)
    zip_names = taxonomy_zip.namelist()

    # ── Load input titles ─────────────────────────────────────────────────────
    print(f"\nLoading job titles from {args.input}...")
    with open(args.input, newline="", encoding="utf-8") as f:
        input_rows = list(csv.DictReader(f))
    if not input_rows:
        print("[ERROR] Input CSV is empty.", file=sys.stderr)
        sys.exit(1)
    if TITLE_COLUMN not in input_rows[0]:
        print(f"[ERROR] Expected column {TITLE_COLUMN!r} not found in input CSV.", file=sys.stderr)
        print(f"  Found columns: {list(input_rows[0].keys())}", file=sys.stderr)
        sys.exit(1)
    print(f"  {len(input_rows)} rows loaded")

    os.makedirs(args.output_dir, exist_ok=True)

    # ── NEL linking ───────────────────────────────────────────────────────────
    checkpoint_path = os.path.join(args.output_dir, ".nel_checkpoint.json")

    print(f"\nLinking titles to ESCO occupations (min_similarity={MIN_SIMILARITY})...")
    matched, unmatched = link_titles(
        input_rows, TITLE_COLUMN, AMHARIC_COLUMN, nel_endpoint, nel_api_key, checkpoint_path
    )
    total = len(matched) + len(unmatched)
    print(f"  {len(matched)}/{total} matched ({100 * len(matched) / total:.1f}%)")
    counts: dict[str, int] = defaultdict(int)
    for row in matched:
        counts[row["confidence"]] += 1
    for level in ["exact", "high_confidence", "low_similarity"]:
        print(f"    {level}: {counts[level]}")

    # ── Write output files ────────────────────────────────────────────────────
    print("\nWriting output files...")

    # occupations.csv — enriched
    occupation_rows = read_csv_from_zip(taxonomy_zip, "occupations.csv")
    output_occupations = os.path.join(args.output_dir, "occupations.csv")
    enriched_count = enrich_occupations(occupation_rows, output_occupations, matched)
    print(f"  occupations.csv           ({enriched_count} occupations gained local labels)")

    # everything else — written verbatim from the ZIP
    passthrough = [name for name in zip_names if name != "occupations.csv"]
    for filename in passthrough:
        write_file_from_zip(taxonomy_zip, filename, args.output_dir)
        print(f"  {filename}")

    # unmatched titles
    unmatched_path = os.path.join(args.output_dir, "unmatched_titles.csv")
    with open(unmatched_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["title_en", "title_am", "similarity_score"], quoting=csv.QUOTE_ALL
        )
        writer.writeheader()
        writer.writerows(unmatched)
    print(f"  unmatched_titles.csv      ({len(unmatched)} titles with no match)")

    # cleanup checkpoint
    if os.path.exists(checkpoint_path):
        os.remove(checkpoint_path)

    print(f"\nDone. {enriched_count}/{len(occupation_rows)} occupations enriched.")
    print(f"Output: {args.output_dir}/")


if __name__ == "__main__":
    main()
