"""
Base class for translation providers.
"""

from abc import ABC, abstractmethod
from typing import Any
import pandas as pd


class BaseTranslator(ABC):
    """Abstract base class for LLM translation providers."""

    def __init__(self, api_key: str, model: str, lang_code: str, lang_config: dict[str, Any]):
        self.api_key = api_key
        self.model = model
        self.lang_code = lang_code
        self.lang_config = lang_config

    @abstractmethod
    def translate_batch(
        self,
        batch_rows: pd.DataFrame,
        file_config: dict[str, Any],
        file_name: str,
    ) -> dict[str, dict[str, str]] | None:
        """
        Translate a batch of records.

        Args:
            batch_rows: DataFrame containing records to translate
            file_config: Configuration for the taxonomy file
            file_name: Name of the source file

        Returns:
            Dictionary mapping record IDs to translated fields, or None on failure
        """
        pass

    def create_translation_prompt(
        self,
        batch_rows: pd.DataFrame,
        file_config: dict[str, Any],
        file_name: str,
    ) -> str:
        """Create the translation prompt for the LLM."""
        entity_type = file_config['type']
        translation_fields = file_config['translation_fields']

        lang_name = self.lang_config['name']
        lang_instructions = self.lang_config.get('instructions', '')
        special_chars = self.lang_config.get('special_chars', '')

        is_occupation = entity_type in ['OCCUPATION', 'OCCUPATION_GROUP']

        # Build field list
        fields_to_translate = [
            field for field in translation_fields
            if field in batch_rows.columns and batch_rows[field].notna().any()
        ]

        # Different instructions for occupations vs skills
        if is_occupation:
            label_instruction = """7. PREFERREDLABEL FOR OCCUPATIONS:
   - Use professional title NOUNS ONLY, never infinitive verbs
   - The translation must be WHO the person is, not WHAT they do
   - CORRECT: "gerente de recursos humanos" (human resources manager)
   - WRONG: "gestionar recursos humanos" (to manage human resources)"""
        else:
            label_instruction = """7. PREFERREDLABEL FOR SKILLS:
   - For action-based skills: Use infinitive verbs
   - For knowledge/concept skills: Use nouns"""

        prompt = f"""You are a professional translator specializing in ESCO taxonomy translation to {lang_name}.

TASK: Translate {len(batch_rows)} {entity_type.lower()} records from {file_name} into {lang_name}

LANGUAGE-SPECIFIC INSTRUCTIONS:
{lang_instructions}

CRITICAL FORMATTING RULES:
1. PRESERVE EXACT FORMATTING: Line breaks, bullet points, numbered lists
2. COMPLETE TRANSLATIONS: Translate the ENTIRE content, not truncated
3. ALTLABELS: Use line breaks between items (same as English)
4. Preserve taxonomy references and codes exactly as written
5. Use proper {lang_name} characters: {special_chars}
6. Maintain professional register
{label_instruction}
8. CONSISTENCY: PREFERREDLABEL must appear in ALTLABELS

RECORDS TO TRANSLATE:
"""

        for i, (_, row) in enumerate(batch_rows.iterrows(), 1):
            prompt += f"\n{i}. ID: {row[file_config['id_field']]}"

            for field in fields_to_translate:
                content = row.get(field, '')
                if pd.notna(content) and str(content).strip():
                    content_str = str(content).replace('"', "'")
                    prompt += f"\n   {field}: {content_str}"
                else:
                    prompt += f"\n   {field}: [EMPTY]"

        prompt += f"""

OUTPUT FORMAT - RESPOND WITH ONLY THIS JSON STRUCTURE:
{{
  "translations": ["""

        id_field = file_config['id_field']
        for i in range(len(batch_rows)):
            record_id = batch_rows.iloc[i][id_field]
            prompt += f"""
    {{
      "id": "{record_id}","""
            for field in fields_to_translate:
                prompt += f"""
      "{field.lower()}_translated": "YOUR {lang_name.upper()} TRANSLATION HERE","""
            prompt = prompt.rstrip(',')
            prompt += f"""
    }}{"," if i < len(batch_rows) - 1 else ""}"""

        prompt += """
  ]
}

OUTPUT VALID JSON ONLY."""

        return prompt
