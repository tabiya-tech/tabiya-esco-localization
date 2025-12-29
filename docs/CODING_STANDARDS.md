# Coding Standards - Tabiya ESCO Localization Framework

**Version:** 1.0.0
**Last Updated:** 2025-01-22
**Based On:** Tabiya compass and taxonomy-model-application repositories

---

## OVERVIEW

This document defines the code quality standards for the Tabiya ESCO Localization Framework. These standards are derived from Tabiya's existing codebases and ensure consistency, maintainability, and professional quality suitable for open-source distribution.

---

## GUIDING PRINCIPLES

### 1. Professional Quality
- No emojis in code, comments, or commit messages
- No irresponsible refactoring (change only what's necessary)
- Code must be organized, simple, and easy to follow
- Self-documenting code with clear variable names
- Suitable for handoff to other developers

### 2. Simplicity Over Cleverness
- Write clear, straightforward code
- Avoid premature optimization
- Prefer explicit over implicit
- Don't over-engineer solutions

### 3. Test-Driven Development
- Write tests before implementation (TDD approach)
- Follow BDD patterns (GIVEN/WHEN/THEN)
- Maintain high test coverage
- Test both happy paths and edge cases

### 4. Documentation Balance
- Comprehensive docstrings for all public functions/classes
- Inline comments only where logic isn't self-evident
- Focus on "why" not "what"
- Maintain up-to-date README files

---

## PYTHON STYLE GUIDE

### Environment & Tools

**Python Version**: 3.11+

**Dependency Management**: Poetry
```bash
poetry install
poetry add <package>
poetry run <command>
```

**Linting & Formatting**:
- **pylint**: Code quality and style checking
- **bandit**: Security vulnerability scanning
- **black** or **autopep8**: Auto-formatting (optional, manual formatting acceptable)

**Configuration** (pyproject.toml):
```toml
[tool.poetry]
python = "^3.11"

[tool.poetry.dependencies]
# List dependencies

[tool.poetry.dev-dependencies]
pytest = "^7.0"
pylint = "^2.17"
bandit = "^1.7"
```

**Configuration** (.pylintrc):
```ini
[FORMAT]
max-line-length=160

[MESSAGES CONTROL]
disable=missing-module-docstring

[DESIGN]
disable=R0903  # Too few public methods (acceptable for data classes)
```

### Naming Conventions

**Files & Directories**:
- snake_case for Python files: `semantic_matcher.py`, `gemini_validator.py`
- Test files: `test_*.py` prefix (e.g., `test_semantic_matcher.py`)
- Private modules: leading underscore `_types.py`, `_utils.py`
- Test data directories: `_test_data/`
- Utility directories: `_test_utilities/`

**Variables**:
- snake_case for variables and functions: `cno_occupation`, `parse_embeddings()`
- UPPER_CASE for constants: `BATCH_SIZE = 5000`, `MAX_RETRIES = 3`
- Private variables/functions: leading underscore `_internal_helper()`

**Classes**:
- PascalCase: `CNOOccupation`, `SemanticMatcher`, `ExperienceNotFoundError`
- Abstract interfaces: prefix with `I` (e.g., `IExperienceService`)

### Type Hints

**Required** for all function signatures:

```python
def parse_embeddings(
    file_path: str,
    model_id: str,
    batch_size: int = 1000
) -> dict[str, list[float]]:
    """
    Parse embeddings from file.

    :param file_path: Path to embeddings file
    :param model_id: Model identifier
    :param batch_size: Number of items per batch
    :return: Dictionary mapping IDs to embedding vectors
    :raises FileNotFoundError: If file doesn't exist
    """
    pass
```

**Type hints for complex types**:
```python
from typing import Optional, Union, Callable

def validate_mapping(
    mapping: dict[str, str],
    validator_fn: Optional[Callable[[str], bool]] = None
) -> tuple[bool, list[str]]:
    pass
```

### Docstrings

**All public functions and classes** must have docstrings:

```python
class ExperienceNotFoundError(Exception):
    """
    Exception raised when an experience is not found in the conversation state.
    """

    def __init__(self, experience_uuid: str):
        super().__init__(f"Experience with uuid {experience_uuid} not found")


async def get_experiences_by_session_id(
    session_id: int
) -> list[tuple[ExperienceEntity, DiveInPhase]]:
    """
    Get all the experiences on the given conversation session.

    :param session_id: int - id for the conversation session
    :return: List[Tuple[ExperienceEntity, DiveInPhase]] - an array containing tuples
    :raises Exception: if any error occurs
    """
    pass
```

### Error Handling

**Use custom exceptions for domain errors**:

```python
class MappingValidationError(Exception):
    """Raised when a mapping fails validation."""
    def __init__(self, occupation_id: str, reason: str):
        super().__init__(f"Mapping validation failed for {occupation_id}: {reason}")
        self.occupation_id = occupation_id
        self.reason = reason
```

**Document exceptions in docstrings**:

```python
def validate_cno_mapping(cno_id: str) -> ESCOMapping:
    """
    Validate CNO to ESCO mapping.

    :param cno_id: CNO occupation identifier
    :return: Validated ESCO mapping
    :raises MappingValidationError: If validation fails
    :raises ValueError: If cno_id format is invalid
    """
    pass
```

**Log warnings for recoverable errors**:

```python
import logging

logger = logging.getLogger(__name__)

def process_row(row: dict) -> Optional[Occupation]:
    if not row.get('TITLE'):
        logger.warning(f"Missing title for occupation ID {row.get('ID')}")
        return None  # Skip invalid row, continue processing

    # Continue processing...
```

### Code Organization

**File Structure**:
```
scripts/
├── 0_data_preparation/
│   ├── arg_cno_translation.py
│   └── _utils.py
├── 1_crosswalk/
│   ├── manual_crosswalk_builder.py
│   └── esco_hierarchy_builder.py
├── 2_embeddings/
│   ├── generate_cno_embeddings.py
│   ├── generate_esco_embeddings.py
│   └── _embedding_utils.py
└── 3_matching/
    ├── phase1_semantic_matching.py
    ├── phase2_gemini_validator.py
    └── _test_utilities/
```

**Imports Organization**:

```python
# Standard library imports
import os
import sys
from pathlib import Path
from typing import Optional, List

# Third-party imports
import pandas as pd
import numpy as np
from sentence_transformers import SentenceTransformer

# Local imports
from _utils import load_config
from _embedding_utils import normalize_embeddings
```

---

## TESTING STANDARDS

### BDD Testing Pattern

Follow **Behavior-Driven Development** with Gherkin-style comments:

```python
import pytest

def test_parse_cno_occupations_from_csv():
    """Should create CNO Occupations from csv file"""

    # GIVEN a model id
    given_model_id = "arg-cno-model-id"
    # AND a CSV file with CNO occupations
    given_csv_file = "_test_data/cno_occupations.csv"
    # AND an occupation repository
    given_repository = MockCNORepository()

    # WHEN the occupations are parsed
    actual_stats = parse_cno_occupations(
        given_csv_file,
        given_model_id,
        given_repository
    )

    # THEN expect all rows to have been processed
    expected_processed = 100
    assert actual_stats.rows_processed == expected_processed
    # AND expect 98 successful imports
    expected_success = 98
    assert actual_stats.rows_success == expected_success
    # AND expect 2 failed imports
    expected_failed = 2
    assert actual_stats.rows_failed == expected_failed
```

### Variable Naming in Tests

- **GIVEN section**: Prefix with `given_`
  - `given_model_id`, `given_csv_file`, `given_repository`
- **WHEN section**: Prefix with `actual_`
  - `actual_stats`, `actual_response`, `actual_mappings`
- **THEN section**: Prefix with `expected_`
  - `expected_processed`, `expected_success`, `expected_mappings`

### Test Description Format

```python
# Good examples:
def test_should_return_valid_mapping_for_exact_match():
    pass

def test_should_raise_error_when_occupation_not_found():
    pass

def test_should_skip_invalid_rows_and_continue_processing():
    pass

# Bad examples (avoid):
def test_mapping():  # Too vague
    pass

def test_function_works():  # Not descriptive
    pass
```

### Test Organization

```python
# Use fixtures for common setup
@pytest.fixture
def mock_gemini_client():
    """Mock Gemini API client for testing."""
    client = AsyncMock()
    client.validate_mapping = AsyncMock()
    return client

@pytest.fixture
def sample_cno_occupation():
    """Factory for creating test CNO occupations."""
    return CNOOccupation(
        id="111",
        title="Director general de empresa",
        description="Sample description"
    )

# Parametrized tests for multiple scenarios
@pytest.mark.parametrize("confidence,should_flag", [
    ("HIGH", False),
    ("MEDIUM", False),
    ("LOW", True),
])
def test_mapping_review_flagging(confidence, should_flag):
    # GIVEN a mapping with specified confidence
    given_mapping = create_mapping(confidence=confidence)

    # WHEN checking if review is needed
    actual_needs_review = requires_manual_review(given_mapping)

    # THEN expect correct flagging
    assert actual_needs_review == should_flag
```

### Test Execution

```bash
# Run all tests
poetry run pytest -v

# Run specific test file
poetry run pytest -v tests/test_semantic_matcher.py

# Run tests with coverage
poetry run pytest --cov=scripts --cov-report=html

# Run tests excluding slow integration tests
poetry run pytest -v -m "not integration"
```

### Test Markers

```python
# pytest.ini
[pytest]
markers =
    integration: marks tests as integration tests (slow)
    unit: marks tests as unit tests (fast)
    requires_api: marks tests requiring external API access

# Usage in test files
@pytest.mark.unit
def test_parse_cno_code():
    pass

@pytest.mark.integration
@pytest.mark.requires_api
async def test_gemini_validation_end_to_end():
    pass
```

---

## DATA PROCESSING STANDARDS

### CSV/File Processing

**Batch Processing Pattern**:

```python
BATCH_SIZE = 5000

def process_csv_in_batches(
    file_path: str,
    process_fn: Callable[[pd.DataFrame], None],
    batch_size: int = BATCH_SIZE
) -> ProcessingStats:
    """
    Process large CSV files in batches.

    :param file_path: Path to CSV file
    :param process_fn: Function to process each batch
    :param batch_size: Number of rows per batch
    :return: Processing statistics
    """
    stats = ProcessingStats()

    for chunk in pd.read_csv(file_path, chunksize=batch_size):
        try:
            process_fn(chunk)
            stats.rows_processed += len(chunk)
        except Exception as e:
            logger.error(f"Batch processing failed: {e}")
            stats.rows_failed += len(chunk)

    return stats
```

**Validation Pattern**:

```python
def validate_row(row: dict) -> Optional[CNOOccupation]:
    """
    Validate and transform a CSV row.

    Returns None for invalid rows (graceful degradation).
    """
    # Validate required fields
    if not row.get('CNO_CODE') or not row.get('TITLE'):
        logger.warning(f"Missing required fields for row ID {row.get('ID')}")
        return None

    # Validate format
    if not re.match(r'^\d{3}$', row['CNO_CODE']):
        logger.warning(f"Invalid CNO code format: {row['CNO_CODE']}")
        return None

    # Transform and return
    return CNOOccupation(
        cno_code=row['CNO_CODE'],
        title=row['TITLE'],
        description=row.get('DESCRIPTION', ''),
    )
```

### Parallel Processing

**Use ThreadPoolExecutor for I/O-bound tasks** (API calls):

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

MAX_WORKERS = 50
RATE_LIMIT = 850  # requests per minute

checkpoint_lock = Lock()

def process_with_parallelism(
    items: list,
    process_fn: Callable,
    max_workers: int = MAX_WORKERS
) -> list:
    """
    Process items in parallel with thread pool.

    :param items: Items to process
    :param process_fn: Function to process each item
    :param max_workers: Maximum concurrent workers
    :return: List of processed results
    """
    results = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(process_fn, item): item
            for item in items
        }

        for future in tqdm(as_completed(futures), total=len(futures)):
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                item = futures[future]
                logger.error(f"Failed to process {item}: {e}")

    return results
```

### Checkpoint System

**For long-running processes**:

```python
import json
from pathlib import Path

CHECKPOINT_FILE = "outputs/intermediate/checkpoint.json"
CHECKPOINT_INTERVAL = 100

def save_checkpoint(data: dict, checkpoint_file: str = CHECKPOINT_FILE):
    """Save checkpoint data to resume processing."""
    Path(checkpoint_file).parent.mkdir(parents=True, exist_ok=True)
    with open(checkpoint_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

def load_checkpoint(checkpoint_file: str = CHECKPOINT_FILE) -> dict:
    """Load checkpoint data if exists."""
    if Path(checkpoint_file).exists():
        with open(checkpoint_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

# Usage in processing loop
checkpoint = load_checkpoint()
processed_ids = set(checkpoint.get('processed_ids', []))

for i, occupation in enumerate(occupations):
    if occupation['id'] in processed_ids:
        continue  # Skip already processed

    result = process_occupation(occupation)
    processed_ids.add(occupation['id'])

    # Save checkpoint every 100 items
    if (i + 1) % CHECKPOINT_INTERVAL == 0:
        save_checkpoint({'processed_ids': list(processed_ids)})
```

---

## CONFIGURATION MANAGEMENT

### Environment Variables

**Use .env files (never commit)**:

```python
# .env (excluded from git)
GEMINI_API_KEY=your_api_key_here
TAXONOMY_MODEL_ID=arg-cno-2017
MAX_WORKERS=50
```

**Load with python-dotenv**:

```python
from dotenv import load_dotenv
import os

load_dotenv()

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable required")
```

### Configuration Files

**Use YAML for country-specific config**:

```yaml
# countries/argentina_cno2017/config.yaml
country:
  name: "Argentina"
  code: "AR"
  taxonomy_name: "CNO-2017"
  taxonomy_version: "2017"

source_data:
  national_taxonomy_pdf: "data/source/pdfs/ARG_CNO_2017.pdf"
  crosswalk_pdf: "data/source/pdfs/correspondencias_cno2017_ciuo2008.pdf"
  translated_taxonomy: "data/source/processed/CNO_2017_Translated_Complete.xlsx"

pipeline:
  embedding_model: "all-MiniLM-L6-v2"
  embedding_dimensions: 384
  batch_size: 5000
  max_parallel_workers: 50

validation:
  llm_model: "gemini-2.5-flash"
  confidence_threshold: "HIGH"
  rate_limit_rpm: 850
```

**Load config**:

```python
import yaml

def load_config(config_path: str) -> dict:
    """Load YAML configuration file."""
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

config = load_config('countries/argentina_cno2017/config.yaml')
batch_size = config['pipeline']['batch_size']
```

---

## VERSION CONTROL STANDARDS

### Git Workflow

**Commit Message Format** (Conventional Commits):

```
<type>: <description>

[optional body]

[optional footer]
```

**Types**:
- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation changes
- `refactor:` Code restructuring without behavior change
- `test:` Adding or updating tests
- `chore:` Maintenance tasks (dependencies, configs)
- `perf:` Performance improvements

**Examples**:
```
feat: add Spanish-Spanish semantic matching

Implemented direct Spanish-to-Spanish embedding comparison
to preserve semantic nuance and reduce translation artifacts.
Results show 15% improvement in top-5 candidate relevance.

docs: update EXPERIMENT_LOG with prompt engineering results

refactor: extract common validation logic into shared module

fix: correct CNO code format validation regex

test: add edge case tests for industry-dependent mappings
```

### .gitignore Pattern

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
.pytest_cache/
.coverage
htmlcov/

# Virtual environments
venv/
.venv/
env/

# Environment variables
.env
.env.local

# API keys and credentials
**/credentials.json
**/api_keys.txt

# Local research materials
references/
**/pdfs/  # Optional: might want to version source PDFs

# Large intermediate files
data/embeddings/*.json
outputs/intermediate/*.json

# OS-specific
.DS_Store
Thumbs.db
desktop.ini

# IDE
.vscode/
.idea/
*.swp
*.swo

# Logs
*.log
logs/
```

---

## CODE REVIEW CHECKLIST

Before committing code, verify:

- [ ] No emojis in code or comments
- [ ] All functions have type hints
- [ ] Public functions have docstrings
- [ ] Tests written (GIVEN/WHEN/THEN format)
- [ ] Tests pass (`poetry run pytest`)
- [ ] No linting errors (`poetry run pylint`)
- [ ] No security issues (`poetry run bandit`)
- [ ] Configuration in .env or YAML (not hardcoded)
- [ ] Error handling with logging
- [ ] Checkpoint system for long processes
- [ ] Commit message follows Conventional Commits
- [ ] No sensitive data in commits

---

## PERFORMANCE GUIDELINES

### Do's
- Use pandas for large CSV processing
- Batch process data (default: 5000 rows)
- Implement checkpointing for resumability
- Use parallel processing for I/O-bound tasks
- Cache expensive computations
- Log progress with tqdm

### Don'ts
- Don't load entire large files into memory at once
- Don't make synchronous API calls in loops (use parallel)
- Don't ignore rate limits
- Don't skip error handling
- Don't forget to close file handles

---

## DOCUMENTATION REQUIREMENTS

### README.md Structure

Every major module/directory should have a README:

```markdown
# Module Name

## Purpose
Brief description of what this module does.

## Prerequisites
- Python 3.11+
- Required API keys

## Installation
\```bash
poetry install
\```

## Usage
\```python
from module import function
result = function(args)
\```

## Testing
\```bash
poetry run pytest
\```

## Configuration
Description of config files and environment variables.

## Known Limitations
List any caveats or constraints.
```

### Inline Documentation

```python
def complex_transformation(data: pd.DataFrame) -> pd.DataFrame:
    """
    Transform CNO occupation data for ESCO mapping.

    This function performs several transformations:
    1. Normalizes occupation titles
    2. Extracts hierarchy codes
    3. Maps industry-dependent occupations

    :param data: Raw CNO occupation data
    :return: Transformed data ready for mapping
    """
    # Normalize titles to remove extra whitespace and standardize casing
    data['title_normalized'] = data['title'].str.strip().str.title()

    # Extract major group code (first digit of CNO code)
    # CNO uses 3-digit codes where first digit = major group
    data['major_group'] = data['cno_code'].str[0]

    # Industry-dependent occupations (2*, 3*, 7*) require special handling
    # See: INDEC methodology document, Section 4.2
    data['is_industry_dependent'] = data['major_group'].isin(['2', '3', '7'])

    return data
```

---

## SUMMARY

These coding standards ensure:
1. **Professional quality** suitable for open-source distribution
2. **Maintainability** for future developers and country adaptations
3. **Testability** with comprehensive BDD-style tests
4. **Consistency** with Tabiya's existing codebases
5. **Transparency** through clear documentation and logging

Follow these standards for all code contributions to the Tabiya ESCO Localization Framework.

---

*Last updated: 2025-01-22*
*Derived from: Tabiya compass and taxonomy-model-application repositories*
