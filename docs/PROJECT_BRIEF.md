# Tabiya ESCO Taxonomy Localization Framework

**Version:** 1.0.0
**Last Updated:** 2025-01-22
**Status:** Active Development

---

## VISION

Build a reusable, scalable framework for localizing the Tabiya ESCO taxonomy to national occupational classifications in low- and middle-income countries (LMICs). The framework combines official crosswalk data, semantic AI matching, and expert validation to create high-quality, culturally appropriate taxonomy mappings that recognize both formal employment and the unseen economy.

---

## PURPOSE

### Primary Objective
Enable skills-based labor market analysis, job matching, and policy development across diverse national contexts by creating systematic bridges between local occupational classifications and the international ESCO/ISCO standards, as extended by Tabiya's Inclusive Livelihoods Taxonomy.

### Secondary Objectives
1. **Recognize Economic Diversity**: Map not only formal occupations but also microentrepreneurship, informal work, caregiving, and volunteer activities
2. **Preserve Local Context**: Maintain culturally relevant terminology while enabling international comparability
3. **Support Evidence-Based Policy**: Provide standardized data infrastructure for labor market analysis
4. **Build Institutional Capacity**: Create reusable tools and methodologies that reduce the cost of future localizations
5. **Foster Open Knowledge**: Contribute to the global commons of labor market information through open-source, CC BY 4.0 licensed outputs

---

## SCOPE

### In Scope
- **Geographic Focus**: Low- and middle-income countries (LMICs), with opportunistic prioritization of countries having ISCO-based national taxonomies
- **Immediate Priorities**: Argentina (CNO-2017), Kenya, Ethiopia, Zambia, Ukraine, Bosnia & Herzegovina
- **Taxonomy Coverage**: National occupational classifications, skills frameworks, job descriptions where available
- **Mapping Levels**: Occupation-to-occupation primary; occupation-to-skills secondary; unseen economy integration tertiary
- **Data Sources**: Official government taxonomies (PDFs, databases, APIs), existing ISCO crosswalks, job description datasets, expert knowledge
- **Technologies**: Python-based pipelines, LLM-assisted validation, semantic embeddings, human expert review

### Out of Scope
- High-income countries with mature labor market information systems (unless specifically requested)
- Real-time job posting scraping or live labor market data
- Wage/compensation mapping (occupation focus only)
- Educational qualification mapping (separate initiative)
- Industry classification systems (focus on occupations)

### Success Criteria
1. **Accuracy**: ≥90% of high-confidence mappings validated by local subject matter experts
2. **Coverage**: ≥85% of national taxonomy occupations mapped to ESCO equivalents
3. **Usability**: Final outputs compatible with Tabiya platform (9-file CSV format, API-ready)
4. **Reusability**: Pipeline successfully reused for ≥3 countries with <50% country-specific code
5. **Transparency**: All decisions, trade-offs, and limitations documented for reproducibility

---

## WORKING PRINCIPLES

### 1. Data Quality Over Speed
- Prioritize accuracy and expert validation over rapid completion
- Track confidence levels and flag uncertainty for human review
- Document limitations and caveats transparently

### 2. Open and Transparent
- Open-source code (MIT License where applicable)
- Open data outputs (CC BY 4.0)
- Comprehensive documentation of methodology, decisions, and edge cases
- Reproducible pipelines with versioned dependencies

### 3. Local Expertise First
- Engage native speakers and local labor market experts in validation
- Preserve local terminology as alternative labels
- Recognize country-specific occupations and economic contexts
- Avoid imposing European/Western occupational categories where inappropriate

### 4. Build for Reuse
- Write modular, configurable code
- Extract common patterns into shared utilities
- Document country-specific adaptations separately
- Create templates for future localizations

### 5. Incremental and Iterative
- Complete one country fully before generalizing
- Test multiple approaches and document outcomes
- Learn from each localization to improve the next
- Maintain flexibility to adapt methodology based on findings

### 6. Tabiya Alignment
- Maintain compatibility with Tabiya platform specifications
- Include unseen economy occupations where relevant
- Follow 9-file CSV format for all outputs
- Preserve UUID-based entity tracking
- Support eventual API integration

### 7. Professional Code Standards
- Follow Tabiya's established coding conventions
- No emojis in code or comments
- Simple, focused changes (avoid over-engineering)
- Comprehensive testing (unit, integration, data validation)
- Clear documentation (README, docstrings, inline comments for complex logic)

### 8. Evidence-Based Decision Making
- Track experiments systematically
- Compare approaches quantitatively where possible
- Document reasoning for all major decisions
- Learn from failed experiments (negative results are valuable)

---

## CONSTRAINTS

### Technical Constraints
- **Language Barriers**: Many national taxonomies only available in local languages; translation required
- **Data Formats**: PDFs, scanned documents, inconsistent structures require custom parsing
- **API Limits**: Rate limiting on LLM APIs (Gemini, GPT) constrains throughput
- **Computational Resources**: Embedding generation and semantic matching require significant compute
- **Data Availability**: Not all countries have official crosswalks, job descriptions, or digital taxonomies

### Resource Constraints
- **Budget**: API costs for translation and validation must be monitored
- **Time**: Argentina has a deadline; future countries subject to business priorities
- **Expertise**: Access to subject matter experts varies by country
- **Solo Development**: Initially developed by one person; code must support eventual handoff

### Methodological Constraints
- **Semantic Ambiguity**: Many occupations don't map 1:1 between taxonomies
- **Cultural Differences**: Occupation definitions vary significantly across countries
- **ESCO Limitations**: Not all national occupations have ESCO equivalents
- **Unseen Economy Gaps**: Limited precedent for mapping informal work systematically

---

## DELIVERABLES

### Per-Country Deliverables
1. **Validated Mapping Files** (3 stages):
   - Stage 1: Testing outputs (JSON/CSV for internal iteration)
   - Stage 2: Human review distribution (Excel with review interface)
   - Stage 3: Final localized taxonomy (Tabiya 9-file CSV format)

2. **Documentation**:
   - Methodology narrative (METHODOLOGY.md)
   - Experiment log (EXPERIMENT_LOG.md)
   - Validation tracker (VALIDATION_TRACKER.md)
   - Data sources and provenance
   - Known limitations and caveats

3. **Code & Configuration**:
   - Country-specific scripts
   - Configuration files (YAML/JSON)
   - Test data and validation scripts

### Framework Deliverables
1. **Reusable Pipeline**: Modularized code for extraction, embedding, matching, validation
2. **Documentation System**: Templates, guides, and playbooks for future countries
3. **Shared Resources**: ESCO embeddings cache, common utilities, data schemas
4. **Quality Standards**: Code conventions, testing requirements, CI/CD templates

---

## GOVERNANCE

### Decision Authority
- **Solo Development Phase**: Afsana has final decision authority
- **Methodology Changes**: Discussed with Tabiya team before major pivots
- **Country Prioritization**: Based on business needs and data availability

### Review Gates
1. **Pre-Human Review**: Automated quality checks, confidence thresholds
2. **Expert Review**: Local SMEs validate sample mappings
3. **Tabiya Platform Review**: Compatibility check before submission
4. **Public Release**: Final quality assurance by Tabiya dev team

### Change Management
- **Scope Changes**: Update PROJECT_BRIEF.md only for fundamental shifts
- **Pipeline Changes**: Update LOCALIZATION_PIPELINE.md when process evolves
- **Code Standards**: Update CODING_STANDARDS.md rarely, with team alignment

---

## TIMELINE PHILOSOPHY

This project follows a **milestone-based** rather than time-based approach:
- Focus on what needs to be done, not when
- Break work into concrete, actionable steps
- Let users decide scheduling based on business priorities
- Expect high and low work periods based on external needs

**Current Milestone**: Complete Argentina CNO-2017 localization to deadline
**Next Milestone**: Refactor pipeline for Kenya (KeSCO) reuse
**Future Milestones**: Ethiopia, Zambia, Ukraine, Bosnia & Herzegovina

---

## RELATED RESOURCES

- [Tabiya Inclusive Livelihoods Taxonomy Documentation](https://docs.tabiya.org/our-tech-stack/inclusive-livelihoods-taxonomy)
- [ESCO Taxonomy (v1.1.1)](https://esco.ec.europa.eu/)
- [ISCO-08 International Standard](https://www.ilo.org/public/english/bureau/stat/isco/)
- [ICATUS 2016 (Unseen Economy)](https://unstats.un.org/unsd/gender/timeuse/)
- [Tabiya Open Taxonomy Platform](https://docs.tabiya.org/our-tech-stack/inclusive-livelihoods-taxonomy/open-taxonomy-platform)

---

## CONTACT & CONTRIBUTION

**Primary Contact**: Afsana (Project Lead)
**Organization**: Tabiya
**License**: Code (MIT), Data (CC BY 4.0)
**Repository**: [To be established on GitHub]

For questions, suggestions, or collaboration inquiries, please contact the Tabiya team.

---

*This document establishes the enduring vision and principles for the Tabiya ESCO Localization Framework. Updates should be rare and reflect only fundamental changes to project direction or scope.*
