"""
Google Gemini translation provider.
"""

import json
import time
import logging
from typing import Any

import pandas as pd
import google.generativeai as genai

from .base import BaseTranslator


class GeminiTranslator(BaseTranslator):
    """Gemini API translator implementation."""

    RATE_LIMIT_DELAY = 0.1
    MAX_RETRIES = 3
    TIMEOUT_DELAY = 15

    def __init__(self, api_key: str, model: str, lang_code: str, lang_config: dict[str, Any]):
        super().__init__(api_key, model, lang_code, lang_config)

        genai.configure(api_key=api_key)

        try:
            self.model_instance = genai.GenerativeModel(model)
            logging.info(f"Initialized Gemini model: {model}")
        except Exception as e:
            # Try fallback models
            fallbacks = ['gemini-3-flash-preview', 'gemini-2.5-flash', 'gemini-2.0-flash']
            for fallback in fallbacks:
                try:
                    self.model_instance = genai.GenerativeModel(fallback)
                    logging.warning(f"Using fallback model: {fallback}")
                    break
                except Exception:
                    continue
            else:
                raise ValueError(f"Could not initialize any Gemini model: {e}")

    def translate_batch(
        self,
        batch_rows: pd.DataFrame,
        file_config: dict[str, Any],
        file_name: str,
    ) -> dict[str, dict[str, str]] | None:
        """Translate a batch of records using Gemini."""

        prompt = self.create_translation_prompt(batch_rows, file_config, file_name)

        response_text = self._call_api(prompt, retry_count=0)

        if not response_text or response_text.startswith('ERROR'):
            return None

        return self._parse_response(response_text, batch_rows, file_config)

    def _call_api(self, prompt: str, retry_count: int = 0) -> str | None:
        """Execute API call with retry logic."""
        try:
            delay = self.RATE_LIMIT_DELAY * (1 + retry_count * 0.3)
            time.sleep(delay)

            generation_config = genai.types.GenerationConfig(
                temperature=0.05,
                top_p=0.8,
                max_output_tokens=12000,
            )

            response = self.model_instance.generate_content(
                prompt,
                generation_config=generation_config,
                safety_settings=[
                    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
                ],
            )

            if response and response.text:
                return response.text.strip()
            else:
                logging.warning("Empty response from Gemini")
                return None

        except Exception as e:
            error_msg = str(e).lower()

            if "timeout" in error_msg or "503" in error_msg or "socket" in error_msg:
                if retry_count < self.MAX_RETRIES:
                    logging.warning(f"Network error, retrying ({retry_count + 1}/{self.MAX_RETRIES})")
                    time.sleep(self.TIMEOUT_DELAY)
                    return self._call_api(prompt, retry_count + 1)

            elif "quota" in error_msg or "limit" in error_msg:
                if retry_count < self.MAX_RETRIES:
                    logging.warning("Rate limit, waiting 20s...")
                    time.sleep(20)
                    return self._call_api(prompt, retry_count + 1)

            logging.error(f"API error: {e}")
            return f"ERROR: {e}"

    def _parse_response(
        self,
        response: str,
        batch_rows: pd.DataFrame,
        file_config: dict[str, Any],
    ) -> dict[str, dict[str, str]] | None:
        """Parse JSON response from Gemini."""
        try:
            json_start = response.find('{')
            json_end = response.rfind('}') + 1

            if json_start == -1 or json_end <= json_start:
                logging.warning("No JSON found in response")
                return None

            json_str = response[json_start:json_end]
            data = json.loads(json_str)

            if 'translations' not in data:
                logging.warning("No 'translations' key in response")
                return None

            translations = {}
            id_field = file_config['id_field']
            translation_fields = file_config['translation_fields']
            lang_suffix = self.lang_code.upper()

            for translation in data['translations']:
                record_id = translation.get('id', '')

                # Find matching row
                matching = batch_rows[batch_rows[id_field] == record_id]
                if matching.empty:
                    continue

                translation_dict = {}
                for field in translation_fields:
                    translated_key = f"{field.lower()}_translated"
                    target_field = f"{field}_{lang_suffix}"
                    translation_dict[target_field] = translation.get(translated_key, '')

                translations[record_id] = translation_dict

            return translations if translations else None

        except json.JSONDecodeError as e:
            logging.warning(f"JSON parse error: {e}")
            return None
