# Skill Definitions and Contextualization in ESCO

## Purpose

This document provides conceptual clarity on how ESCO defines skills, knowledge, and competences, and how to distinguish skills from tasks. It serves as a shared reference for anyone creating or evaluating skill concepts during country localizations.

---

## 1. Core Definitions (from European Qualifications Framework)

### Skill

"The ability to apply knowledge and use know-how to complete tasks and solve problems." Skills can be cognitive (logical, intuitive, creative thinking) or practical (manual dexterity, use of methods/materials/tools).

### Knowledge

"The outcome of the assimilation of information through learning. The body of facts, principles, theories and practices related to a field of work or study."

### Competence

"The proven ability to use knowledge, skills and personal, social and/or methodological abilities, in work or study situations and in professional and personal development." Described in terms of responsibility and autonomy.

**Note:** In ESCO's data model, skills and competences are not distinguished. Both are recorded as "skill/competence" type. The only type distinction is between "skill/competence" and "knowledge".

---

## 2. Skills vs Tasks

This is a critical distinction. ESCO intentionally does NOT include a task layer in its taxonomy.

### What is a task?

A task is the smallest unit of work activity that produces a specific output. Tasks are discrete, observable work steps.

Examples of tasks:
- "Develop study briefs and desk reviews of similar projects"
- "Perform site reconnaissance surveys"
- "Prepare bills of quantities"
- "Adjudicate tenders"

### What is a skill?

A skill is the underlying ability/capability that enables a worker to perform tasks. Skills are transferable and reusable across contexts.

Examples of skills:
- "conduct feasibility studies" (encompasses multiple task steps)
- "apply engineering design principles"
- "manage procurement processes"

### The test

Ask: "Is this describing a specific work activity (task) or a capability that enables multiple activities (skill)?"

Multiple tasks often map to a single skill. For example:

| Tasks (discrete work activities) | Underlying skill |
|---|---|
| Develop study briefs and desk reviews | conduct feasibility studies |
| Perform site reconnaissance surveys | |
| Undertake topographical surveys and geotechnical investigations | |
| Assess risks and economic feasibility | |

### Why this matters

From the Acemoglu-Autor framework: technology impacts tasks, not skills directly. Workers are endowed with skills (capabilities) that they apply to tasks. Occupations are bundles of tasks. There is a many-to-many mapping between skills and tasks.

ESCO was set up with two pillars (occupations and skills) without an explicit task layer. Tasks are implicitly present -- the EQF definition of skill explicitly references them ("the ability to apply knowledge and use know-how to complete **tasks** and solve problems") -- but ESCO captures the ability, not the task itself.

When localizing ESCO, we must be careful not to inadvertently add tasks disguised as skills to the taxonomy. Adding granularity is appropriate where it represents a genuine skill or knowledge concept; adding task-level specificity is not.

---

## 3. ESCO Skill Phrasing Conventions

### Skills and Competences

- Always phrased as **verb phrases** in infinitive form (without "to")
- Pattern: **verb + object [+ qualifier]**
- Use lowercase throughout (no initial capitals unless proper nouns)
- Use the simplest, most direct verb possible
- Keep labels concise but unambiguous (typically 2-6 words)
- No articles unless needed for clarity
- Plural nouns for objects referring to general categories

Examples:
- "manage budgets"
- "operate forklift"
- "advise customers on hearing aids"
- "conduct feasibility studies"

Common starting verbs: manage, operate, maintain, perform, use, develop, monitor, provide, apply, prepare

### Knowledge Concepts

- Always phrased as **noun phrases** (never verbs)
- Do NOT use "know" or "knowledge of" in the label
- Pattern: **[qualifier +] noun**

Examples:
- "fermentation process" (not "knowledge of fermentation process")
- "labour law" (not "know labour law")
- "environmental management"
- "engineering design principles"

### Descriptions

- 50-300 characters
- Explain what the skill is about, in line with the action verb used in the label
- Do not limit to a reformulation of the label
- Avoid national references in the description where possible
- Use the same wording patterns for related concepts

---

## 4. Skill Reusability Levels

ESCO classifies skills by how broadly they can be applied:

### Transversal

Relevant to a broad range of occupations and sectors. Often called core skills, basic skills, or soft skills. Building blocks for harder skills.
- Example: "work in teams", "critical thinking", "communicate orally"

### Cross-sectoral

Relevant across several economic sectors.
- Example: "animal welfare" applies in agriculture, veterinary activities, and recreation

### Sector-specific

Specific to one sector but relevant for multiple occupations within it.
- Example: "monitor livestock" is specific to the husbandry/breeding sector

### Occupation-specific

Usually applied within one occupation and its specialisms.
- Example: "milking operations" is specific to "farm milk controller"

---

## 5. Skill Contextualization

Contextualization is ESCO's mechanism for creating more specific skill concepts from abstract ones. It allows bringing transversal or cross-sector skills to a more detailed level so they can be directly used in occupational profiles.

### How it works

A transversal skill like "measure" is too abstract to link meaningfully to "shop assistant". Contextualization makes it specific:

| Level | Example |
|---|---|
| Transversal | measure |
| Cross-sector | measure the size of objects |
| Occupation-specific | measure the size of furniture |

### Two ways contextualization is expressed in ESCO

1. **Hierarchical relationships**: a specific skill is "narrower than" a generic skill
   - "measure the size of objects" is narrower than "measure"

2. **Knowledge-skill relations**: knowledge relevant to developing a skill
   - Knowledge of "furniture wood types" is optional for "advise customers on wood materials"

### Skill decontextualization (the reverse)

A method for generalising an occupation-specific skill so it can be applied across sectors:

| Occupation-specific | Cross-sector equivalent |
|---|---|
| Settle legal disputes between opposing parties | Settle disputes |
| Evaluate information to determine compliance with the law | Evaluate compliance with standards or regulations |

### Applying contextualization in country localizations

When localizing for a specific country, contextualization is the right mechanism for adding country-specific detail:

```
ESCO transversal:        "conduct feasibility studies"
Country-contextualised:  "conduct feasibility studies for water and sanitation systems"

ESCO cross-sector:       "environmental law"
Country-contextualised:  "Zambia Environmental Management Act No. 12 of 2011"
```

The key principle: contextualization adds specificity to an existing capability. It does NOT create new task-level items.

---

## 6. Practical Guidelines for Localization

### When creating new skill concepts

1. Check: Is this a skill (ability/capability) or a task (discrete work activity)?
2. If task: identify the underlying skill that enables this task
3. Phrase as verb + object [+ qualifier] for skills, noun phrase for knowledge
4. Assign appropriate reusability level
5. Place in skill hierarchy under the appropriate skill group
6. Consider: does an ESCO skill already exist that could be contextualised rather than creating something entirely new?

### When evaluating source material (e.g., National Occupational Standards)

- **Performance Criteria** are typically tasks, not skills -- use them as evidence for what skills are needed, but do not add them directly as skill concepts
- **Technical Knowledge** items are typically knowledge concepts -- good candidates for direct matching to ESCO knowledge
- **Core/Professional Skills** are typically transversal or cross-sector skills -- high ESCO match rate expected
- **Regulatory Knowledge** may contain country-specific knowledge worth adding as new localized concepts
- **Organisational Knowledge** -- assess the full pool; some items are genuine knowledge concepts (e.g., "procurement procedures"), others are too generic for a taxonomy (e.g., "company code of conduct")
- Group related tasks to identify the underlying skill they share

### Quality criteria for new skill concepts

- **Observable**: can be demonstrated or assessed
- **Distinct**: does not overlap significantly with existing concepts
- **Reusable**: applies to multiple occupations where possible
- **Appropriately granular**: not too broad and not too narrow (task-level)
- **Consistently phrased**: follows ESCO verb-phrase (skills) or noun-phrase (knowledge) conventions

---

## References

- European Qualifications Framework (EQF)
- ESCO ESCOpedia: https://esco.ec.europa.eu/en/about-esco/escopedia
- Acemoglu, D. and Autor, D. "Skills, Tasks and Technologies: Implications for Employment and Earnings"
- ESCO Skills Pillar documentation
- ESCO Skill Contextualization: https://esco.ec.europa.eu/en/about-esco/escopedia/escopedia/skill-contextualisation
