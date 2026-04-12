"""
Extract skill phrases from Zambia NOS (National Occupational Standards) PDFs.

Reads all NOS PDF documents across sector folders, extracts structured data
including performance criteria (skills), technical knowledge, organisational
knowledge, regulatory knowledge, core skills, and professional skills.

Outputs:
- nos_extractions.json: Full structured extraction per occupation
- nos_skill_phrases.csv: Flat file of all extracted skill/knowledge phrases
"""

import json
import csv
import re
import sys
import io
import pdfplumber
from pathlib import Path
from typing import Optional

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

NOS_DIR = Path(__file__).parent.parent / "data" / "NOS"
OUTPUT_DIR = Path(__file__).parent.parent / "outputs"


def extract_text_from_pdf(pdf_path: Path) -> str:
    """Extract all text from a PDF file."""
    text_parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                text_parts.append(text)
    return "\n".join(text_parts)


def extract_overview(text: str) -> dict:
    """Extract overview fields from the NOS document."""
    overview = {}

    # NOS Code
    match = re.search(r"NOS\s+Code\s+(NOS[.\s]*[\w.]+)", text, re.IGNORECASE)
    if match:
        overview["nos_code"] = match.group(1).strip()

    # Job Title
    match = re.search(r"Job\s+Title\s+(.+?)(?:\n|Job\s+Description)", text, re.IGNORECASE | re.DOTALL)
    if match:
        overview["job_title"] = clean_text(match.group(1))

    # Job Description
    match = re.search(r"Job\s+Description\s+(.+?)(?:\n(?:Job\s+Purpose|ZQF\s+Level))", text, re.IGNORECASE | re.DOTALL)
    if match:
        overview["job_description"] = clean_text(match.group(1))

    # Job Purpose
    match = re.search(r"Job\s+Purpose\s+(.+?)(?:\n(?:ZQF\s+Level|Sector))", text, re.IGNORECASE | re.DOTALL)
    if match:
        overview["job_purpose"] = clean_text(match.group(1))

    # ZQF Level
    match = re.search(r"ZQF\s+Level\s+(\d+)", text, re.IGNORECASE)
    if match:
        overview["zqf_level"] = int(match.group(1))

    # Sector
    match = re.search(r"(?:^|\n)\s*Sector\s+(\w[\w\s,]*?)(?:\n|Sub)", text, re.IGNORECASE)
    if match:
        overview["sector"] = clean_text(match.group(1))

    # Occupation
    match = re.search(r"Occupation\s+(.+?)(?:\n|Job\s+Title)", text, re.IGNORECASE | re.DOTALL)
    if match:
        overview["occupation"] = clean_text(match.group(1))

    return overview


def clean_text(text: str) -> str:
    """Clean extracted text: remove extra whitespace, newlines."""
    text = re.sub(r"\s+", " ", text).strip()
    # Remove trailing periods if present
    text = text.rstrip(".")
    return text


def extract_coded_items(text: str, prefix: str) -> list[dict]:
    """Extract items with codes like PC1, TK1, OK1, RK1, CS1, PS1.

    Uses a two-pass approach: first find all code positions, then extract
    text between consecutive codes to avoid truncation.

    Returns list of dicts with 'code' and 'text' keys.
    """
    # All prefixes that can act as boundaries
    all_prefixes = r"(?:PC|TK|OK|RK|CS|PS)\s*\d+"
    section_headers = (
        r"Knowledge\s+and\s+Understanding|"
        r"Skills\s+\(S\)|"
        r"UNIT\s+\d|"
        r"(?:^|\n)\s*\d+\.\s+[A-Z][A-Z]+|"
        r"Performance\s+Criteria\s+\(PC\)|"
        r"(?:A\.\s+)?(?:Organisational|Core\s+Skills|Professional\s+Skills)|"
        r"(?:B\.\s+)?(?:Technical\s+Knowledge|Professional)|"
        r"(?:C\.\s+)?Regulatory|"
        r"To\s+be\s+competent,?\s+the\s+individual|"
        r"The\s+individual\s+on\s+the\s+job|"
        r"(?:Writing|Reading|Oral\s+Communication|Decision|Plan\s+and|Customer|Problem|Analytical|Critical)\s+(?:Skills|Thinking|Making|Organise|Centricity|Solving)"
    )

    items = []
    # Find all occurrences of this prefix's codes
    code_pattern = rf"({prefix}\s*\d+)[.\s:)]+"
    code_positions = [(m.start(), m.end(), re.sub(r"\s+", "", m.group(1)).upper())
                      for m in re.finditer(code_pattern, text)]

    if not code_positions:
        return items

    for i, (start, text_start, code) in enumerate(code_positions):
        # Determine end boundary: next code of ANY type, section header, or end
        if i + 1 < len(code_positions):
            end = code_positions[i + 1][0]
        else:
            # Last item - find next section boundary or use remaining text
            end = len(text)

        raw = text[text_start:end]

        # Trim at any other prefix code or section header that appears
        boundary_match = re.search(
            rf"(?:{all_prefixes})[.\s:)]|{section_headers}",
            raw, re.IGNORECASE
        )
        # Only use boundary if it's not our own prefix continuing
        if boundary_match:
            candidate = raw[:boundary_match.start()]
            # Only trim if we actually got content before the boundary
            if len(candidate.strip()) > 3:
                raw = candidate

        item_text = clean_text(raw)
        if item_text and len(item_text) > 3:
            items.append({"code": code, "text": item_text})

    return items


def extract_unit_info(text: str) -> list[dict]:
    """Extract unit titles and descriptions."""
    units = []
    # Find UNIT headers
    pattern = r"UNIT\s+(\d+)\s*\[?[^\]]*\]?\s*(?:Unit\s+No\.\s+\d+\s+)?(?:Unit\s+Title\s+)?(.+?)(?:Description|$)"
    matches = re.finditer(pattern, text, re.DOTALL | re.IGNORECASE)
    for match in matches:
        unit_num = match.group(1)
        title_text = clean_text(match.group(2))
        if title_text:
            units.append({"unit_number": int(unit_num), "title": title_text})
    return units


def extract_all_skill_phrases(text: str) -> dict:
    """Extract all categories of skill/knowledge phrases from NOS text."""
    results = {
        "performance_criteria": [],
        "technical_knowledge": [],
        "organisational_knowledge": [],
        "regulatory_knowledge": [],
        "core_skills": [],
        "professional_skills": [],
    }

    # Performance Criteria (PC)
    results["performance_criteria"] = extract_coded_items(text, "PC")

    # Technical Knowledge (TK)
    results["technical_knowledge"] = extract_coded_items(text, "TK")

    # Organisational Knowledge (OK)
    results["organisational_knowledge"] = extract_coded_items(text, "OK")

    # Regulatory Knowledge (RK)
    results["regulatory_knowledge"] = extract_coded_items(text, "RK")

    # Core Skills (CS)
    results["core_skills"] = extract_coded_items(text, "CS")

    # Professional Skills (PS)
    results["professional_skills"] = extract_coded_items(text, "PS")

    return results


def get_sector_from_path(pdf_path: Path) -> str:
    """Get sector name from folder path."""
    folder_name = pdf_path.parent.name
    # Normalize sector names
    sector_map = {
        "Agriculture Nos": "Agriculture",
        "Construction Nos": "Construction",
        "Energy Nos": "Energy",
        "Manufacturing Nos": "Manufacturing",
        "Minining Nos": "Mining",
        "Tourism Nos": "Tourism",
        "Transport Nos": "Transport",
        "Water Nos": "Water",
    }
    return sector_map.get(folder_name, folder_name)


def get_occupation_from_filename(pdf_path: Path) -> str:
    """Derive occupation name from PDF filename."""
    name = pdf_path.stem
    # Remove common prefixes
    name = re.sub(r"^NOS[\s_-]+(?:FOR[\s_-]+)?", "", name, flags=re.IGNORECASE)
    # Remove trailing _revised, final, (1), etc.
    name = re.sub(r"[\s_-]*(?:_revised|_REVISED|revised|\s*final|\(\d+\))[\s_]*$", "", name)
    # Replace underscores/hyphens with spaces
    name = re.sub(r"[_-]+", " ", name)
    # Clean up whitespace
    name = re.sub(r"\s+", " ", name).strip()
    return name


def process_single_pdf(pdf_path: Path) -> Optional[dict]:
    """Process a single NOS PDF and return extracted data."""
    print(f"  Processing: {pdf_path.name}")
    try:
        text = extract_text_from_pdf(pdf_path)
        if not text or len(text) < 100:
            print(f"    WARNING: Very little text extracted ({len(text)} chars)")
            return None

        overview = extract_overview(text)
        skill_phrases = extract_all_skill_phrases(text)
        units = extract_unit_info(text)

        # Count extractions
        total_items = sum(len(v) for v in skill_phrases.values())

        result = {
            "file": pdf_path.name,
            "sector": get_sector_from_path(pdf_path),
            "occupation_from_filename": get_occupation_from_filename(pdf_path),
            "overview": overview,
            "units": units,
            "skill_phrases": skill_phrases,
            "extraction_stats": {
                "text_length": len(text),
                "total_items_extracted": total_items,
                "performance_criteria_count": len(skill_phrases["performance_criteria"]),
                "technical_knowledge_count": len(skill_phrases["technical_knowledge"]),
                "organisational_knowledge_count": len(skill_phrases["organisational_knowledge"]),
                "regulatory_knowledge_count": len(skill_phrases["regulatory_knowledge"]),
                "core_skills_count": len(skill_phrases["core_skills"]),
                "professional_skills_count": len(skill_phrases["professional_skills"]),
            },
        }
        print(f"    Extracted {total_items} items (PC:{len(skill_phrases['performance_criteria'])}, "
              f"TK:{len(skill_phrases['technical_knowledge'])}, OK:{len(skill_phrases['organisational_knowledge'])}, "
              f"RK:{len(skill_phrases['regulatory_knowledge'])}, CS:{len(skill_phrases['core_skills'])}, "
              f"PS:{len(skill_phrases['professional_skills'])})")
        return result

    except Exception as e:
        print(f"    ERROR: {e}")
        return None


def write_flat_csv(extractions: list[dict], output_path: Path) -> None:
    """Write a flat CSV with one row per skill phrase."""
    rows = []
    for ext in extractions:
        sector = ext["sector"]
        occupation = ext["overview"].get("job_title", ext["occupation_from_filename"])
        nos_code = ext["overview"].get("nos_code", "")
        zqf_level = ext["overview"].get("zqf_level", "")

        category_map = {
            "performance_criteria": ("skill/competence", "PC"),
            "technical_knowledge": ("knowledge", "TK"),
            "organisational_knowledge": ("knowledge", "OK"),
            "regulatory_knowledge": ("knowledge", "RK"),
            "core_skills": ("skill/competence", "CS"),
            "professional_skills": ("skill/competence", "PS"),
        }

        for category, items in ext["skill_phrases"].items():
            esco_type, prefix = category_map[category]
            for item in items:
                rows.append({
                    "sector": sector,
                    "occupation": occupation,
                    "nos_code": nos_code,
                    "zqf_level": zqf_level,
                    "category": category,
                    "nos_item_code": item["code"],
                    "esco_skill_type": esco_type,
                    "raw_text": item["text"],
                })

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "sector", "occupation", "nos_code", "zqf_level",
            "category", "nos_item_code", "esco_skill_type", "raw_text",
        ])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nWrote {len(rows)} skill phrases to {output_path.name}")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Find all PDF files in NOS subdirectories
    pdf_files = sorted(NOS_DIR.glob("*/*.pdf"))
    print(f"Found {len(pdf_files)} NOS PDF files\n")

    # Skip known duplicate PDFs (files with (1) suffix that duplicate originals)
    skip_files = {
        "NOS METAL FABRICATORS(1).pdf",
        "NOS-FOR-TRANSPORTANT(1).pdf",
    }
    pdf_files = [p for p in pdf_files if p.name not in skip_files]
    print(f"Processing {len(pdf_files)} PDFs (skipped {len(skip_files)} duplicates)\n")

    # Process each PDF
    extractions = []
    failed = []
    for pdf_path in pdf_files:
        result = process_single_pdf(pdf_path)
        if result:
            extractions.append(result)
        else:
            failed.append(str(pdf_path.name))

    # Summary
    print(f"\n{'='*60}")
    print(f"EXTRACTION SUMMARY")
    print(f"{'='*60}")
    print(f"Total PDFs found: {len(pdf_files)}")
    print(f"Successfully processed: {len(extractions)}")
    print(f"Failed: {len(failed)}")
    if failed:
        print(f"  Failed files: {', '.join(failed)}")

    total_pc = sum(e["extraction_stats"]["performance_criteria_count"] for e in extractions)
    total_tk = sum(e["extraction_stats"]["technical_knowledge_count"] for e in extractions)
    total_ok = sum(e["extraction_stats"]["organisational_knowledge_count"] for e in extractions)
    total_rk = sum(e["extraction_stats"]["regulatory_knowledge_count"] for e in extractions)
    total_cs = sum(e["extraction_stats"]["core_skills_count"] for e in extractions)
    total_ps = sum(e["extraction_stats"]["professional_skills_count"] for e in extractions)
    total_all = total_pc + total_tk + total_ok + total_rk + total_cs + total_ps

    print(f"\nTotal skill phrases extracted: {total_all}")
    print(f"  Performance Criteria (PC): {total_pc}")
    print(f"  Technical Knowledge (TK):  {total_tk}")
    print(f"  Organisational Knowledge (OK): {total_ok}")
    print(f"  Regulatory Knowledge (RK): {total_rk}")
    print(f"  Core Skills (CS):          {total_cs}")
    print(f"  Professional Skills (PS):  {total_ps}")

    # Sector breakdown
    print(f"\nBy sector:")
    sector_counts: dict[str, int] = {}
    for ext in extractions:
        sector = ext["sector"]
        count = ext["extraction_stats"]["total_items_extracted"]
        sector_counts[sector] = sector_counts.get(sector, 0) + count
    for sector, count in sorted(sector_counts.items()):
        occ_count = sum(1 for e in extractions if e["sector"] == sector)
        print(f"  {sector}: {count} items from {occ_count} occupations")

    # Write outputs
    json_path = OUTPUT_DIR / "nos_extractions.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(extractions, f, indent=2, ensure_ascii=False)
    print(f"\nWrote full extractions to {json_path.name}")

    csv_path = OUTPUT_DIR / "nos_skill_phrases.csv"
    write_flat_csv(extractions, csv_path)


if __name__ == "__main__":
    main()
