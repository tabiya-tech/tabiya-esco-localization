"""Generate Kenya KESCO Localization documentation."""

from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT


def add_table(doc, headers, rows):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Light Grid Accent 1"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = h
        for p in cell.paragraphs:
            for r in p.runs:
                r.bold = True
    for ri, row in enumerate(rows):
        for ci, val in enumerate(row):
            table.rows[ri + 1].cells[ci].text = str(val)
    doc.add_paragraph()


doc = Document()

style = doc.styles["Normal"]
font = style.font
font.name = "Calibri"
font.size = Pt(11)
font.color.rgb = RGBColor(0x33, 0x33, 0x33)

for level in range(1, 4):
    h = doc.styles[f"Heading {level}"]
    h.font.color.rgb = RGBColor(0x1A, 0x2A, 0x3A)

# Title
title = doc.add_heading("Kenya KESCO Localization", level=0)
title.alignment = WD_ALIGN_PARAGRAPH.LEFT

doc.add_paragraph(
    "Kenya's national occupational classification (KESCO) contains 5,917 occupations. "
    "This document describes the process of mapping KESCO to the Tabiya ESCO taxonomy, "
    "producing a localized taxonomy where each KESCO occupation either links to an existing "
    "ESCO occupation or is established as a new local occupation with its own skill set."
)

# Overview table
doc.add_heading("Overview", level=1)
add_table(doc,
    ["Metric", "Value"],
    [
        ["Source classification", "KESCO (Kenya Standard Classification of Occupations)"],
        ["Total KESCO occupations", "5,917"],
        ["Base taxonomy", "Tabiya ESCO v2.0.1"],
        ["Matched to ESCO", "5,701 (96.4%)"],
        ["New local occupations created", "69"],
        ["Alternative labels added", "2,760"],
    ]
)

# Matching
doc.add_heading("Matching", level=1)
doc.add_paragraph(
    "The matching pipeline worked in stages, resolving the easiest cases first. "
    "Exact string matching caught 2,919 occupations where the KESCO title matched an ESCO "
    "label directly. Next, Gemini embeddings were generated for all KESCO and ESCO occupations, "
    "and cosine similarity identified high-confidence semantic matches. An LLM validated these "
    "matches, confirming or rejecting each one, covering another 1,952 occupations."
)
doc.add_paragraph(
    "The remaining 975 low-confidence and unmatched items went through human review in a "
    "custom review tool. Reviewers could approve the suggested match, select a different ESCO "
    "occupation from a searchable tree, or flag the item as genuinely new to ESCO. This produced "
    "830 additional matches and identified 216 items as new local. Of those 216, many shared the "
    "same underlying role, so they consolidated into 69 distinct new occupations."
)

add_table(doc,
    ["Stage", "Method", "Occupations Resolved"],
    [
        ["1. Exact match", "String matching against ESCO labels", "2,919 (49%)"],
        ["2. Semantic match", "Gemini embeddings + cosine similarity", "1,539 (26%)"],
        ["3. LLM validation", "Gemini confirms/rejects semantic matches", "413 (7%)"],
        ["4. Human review", "Manual review of 975 remaining items", "830 (14%)"],
        ["New local", "No ESCO equivalent exists", "216 (3.6%)"],
    ]
)

# Taxonomy Construction
doc.add_heading("Taxonomy Construction", level=1)
doc.add_paragraph(
    "Matched occupations had their KESCO titles added as alternative labels on the corresponding "
    "ESCO occupation, adding 2,760 alt labels across 955 ESCO occupations. This means someone "
    "searching for a Kenyan job title will find the correct ESCO occupation."
)
doc.add_paragraph(
    "The 69 new local occupations were created with LLM-generated descriptions, assigned unique "
    "codes following the ISCO group of their closest ESCO parent, and inserted into the "
    "occupation hierarchy."
)

# Skill Assignment
doc.add_heading("Skill Assignment", level=1)
doc.add_paragraph(
    "New local occupations needed skills since they don't inherit them from ESCO. "
    "A combined approach was developed that draws candidate skills from two complementary sources."
)

doc.add_heading("Source 1: ISCO Group Pooling", level=2)
doc.add_paragraph(
    "For each new local occupation, an LLM selected 2-6 ISCO 4-digit groups whose occupations "
    "share relevant skills. This goes beyond the occupation's own ISCO group to capture related "
    "domains. For example, an auditor general (ISCO 1112 - Senior government officials) also draws "
    "skills from group 2411 (Accountants) and 2422 (Policy administration professionals). "
    "All ESCO skills assigned to occupations in the selected groups form the ISCO candidate pool."
)

doc.add_heading("Source 2: O*NET Task Crosswalk", level=2)
doc.add_paragraph(
    "Each new local occupation's embedding was compared against 1,016 pre-embedded O*NET "
    "occupations to find the 5 closest matches by cosine similarity. Those O*NET occupations' "
    "task statements were then mapped to ESCO skills via a validated crosswalk at the task level, "
    "forming the O*NET candidate pool."
)

doc.add_heading("Combined Filtering", level=2)
doc.add_paragraph(
    "The two candidate pools were merged and deduplicated. Skills appearing in both pools "
    "received stronger signal. Gemini 3 Flash then filtered the combined pool with a prompt "
    "that accounts for the occupation's seniority level, professional values, domain knowledge "
    "needs, and the Kenyan context. The prompt distinguishes between leadership roles (which need "
    "strategic and oversight skills) and practitioner roles (which need hands-on working skills)."
)

add_table(doc,
    ["Metric", "Value"],
    [
        ["Total skill relations assigned", "3,964"],
        ["Average skills per occupation", "57"],
        ["Range", "46 - 63"],
        ["Skills from both pools", "~65%"],
        ["Skills from ISCO only", "~20%"],
        ["Skills from O*NET only", "~15%"],
        ["LLM for skill selection", "Gemini 3 Flash"],
    ]
)

# Final Output
doc.add_heading("Final Output", level=1)
doc.add_paragraph(
    "The final taxonomy extends Tabiya ESCO v2.0.1 with Kenya-specific content, "
    "delivered in the standard 9-file CSV format."
)

add_table(doc,
    ["File", "Records", "Kenya Changes"],
    [
        ["occupations.csv", "3,143", "+69 new local occupations, +2,760 alt labels"],
        ["occupation_hierarchy.csv", "3,777", "+69 parent links for new occupations"],
        ["occupation_to_skill_relations.csv", "134,786", "+3,964 skill relations for new occupations"],
        ["skills.csv", "13,896", "Unchanged"],
        ["skill_hierarchy.csv", "20,649", "Unchanged"],
        ["skill_groups.csv", "640", "Unchanged"],
        ["skill_to_skill_relations.csv", "5,898", "Unchanged"],
        ["occupation_groups.csv", "647", "Unchanged"],
        ["model_info.csv", "1", "Updated metadata"],
    ]
)

output = "countries/kenya_kesco/docs/Kenya_KESCO_Localization_v2.docx"
doc.save(output)
print(f"Saved: {output}")
