#!/usr/bin/env python3
"""Translate missing records for Kenya Swahili."""

import os
import sys
from pathlib import Path

import pandas as pd

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / '.env')

from core.translation.config import TAXONOMY_FILES, LanguageConfig
from core.translation.providers import GeminiTranslator


def main():
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        print("Error: GEMINI_API_KEY not found")
        return 1

    outputs_dir = Path(__file__).parent.parent / 'outputs'

    # Load taxonomy and translations
    taxonomy = pd.read_csv(outputs_dir / 'taxonomy' / 'occupations.csv')
    translations = pd.read_csv(outputs_dir / 'translations' / 'sw' / 'occupations_translated_sw_FINAL.csv')

    # Find missing
    tax_ids = set(taxonomy['ID'])
    trans_ids = set(translations['ID'])
    missing_ids = tax_ids - trans_ids

    if not missing_ids:
        print("No missing records to translate!")
        return 0

    print(f"Translating {len(missing_ids)} missing records...")
    missing_df = taxonomy[taxonomy['ID'].isin(missing_ids)].copy()

    for _, row in missing_df.iterrows():
        print(f"  - {row['PREFERREDLABEL']}")

    # Initialize translator
    lang_code = 'sw'
    lang_config = LanguageConfig.get_language_info(lang_code)
    translator = GeminiTranslator(api_key, 'gemini-2.5-flash', lang_code, lang_config)

    # Translate
    file_config = TAXONOMY_FILES['occupations.csv']
    result = translator.translate_batch(missing_df, file_config, "occupations.csv")

    if not result:
        print("No translations returned!")
        return 1

    print(f"\nReceived {len(result)} translations")

    # Build new rows
    new_rows = []
    for _, row in missing_df.iterrows():
        record_id = row[file_config['id_field']]
        trans_dict = result.get(record_id, {})

        new_row = row.to_dict()
        for field, value in trans_dict.items():
            new_row[field] = value
        new_rows.append(new_row)

    new_df = pd.DataFrame(new_rows)

    # Ensure columns match translations file
    for col in translations.columns:
        if col not in new_df.columns:
            new_df[col] = ''
    new_df = new_df[[c for c in translations.columns if c in new_df.columns]]

    # Combine and save
    combined = pd.concat([translations, new_df], ignore_index=True)
    combined.to_csv(outputs_dir / 'translations' / 'sw' / 'occupations_translated_sw_FINAL.csv', index=False)

    print(f"\nUpdated file: {len(combined)} total records")
    print("\n=== TRANSLATIONS ===")
    for _, row in new_df.iterrows():
        print(f"\nEN: {row.get('PREFERREDLABEL', 'N/A')}")
        print(f"SW: {row.get('PREFERREDLABEL_SW', 'N/A')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
