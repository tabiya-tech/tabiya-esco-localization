"""
Translation configuration: languages, taxonomy files, and constants.
"""

from typing import Any


# Taxonomy files and their translation fields
TAXONOMY_FILES = {
    'occupations.csv': {
        'type': 'OCCUPATION',
        'translation_fields': ['PREFERREDLABEL', 'ALTLABELS', 'DESCRIPTION', 'DEFINITION', 'SCOPENOTE'],
        'id_field': 'ORIGINURI',
        'context': 'Professional occupations and job roles',
    },
    'skills.csv': {
        'type': 'SKILL',
        'translation_fields': ['PREFERREDLABEL', 'ALTLABELS', 'DESCRIPTION', 'DEFINITION', 'SCOPENOTE'],
        'id_field': 'ORIGINURI',
        'context': 'Skills, competencies, and knowledge areas',
    },
    'occupation_groups.csv': {
        'type': 'OCCUPATION_GROUP',
        'translation_fields': ['PREFERREDLABEL', 'ALTLABELS', 'DESCRIPTION'],
        'id_field': 'ORIGINURI',
        'context': 'Occupational classifications and groupings',
    },
    'skill_groups.csv': {
        'type': 'SKILL_GROUP',
        'translation_fields': ['PREFERREDLABEL', 'ALTLABELS', 'DESCRIPTION', 'SCOPENOTE'],
        'id_field': 'ORIGINURI',
        'context': 'Skill classifications and competency groupings',
    },
}


class LanguageConfig:
    """Configuration for supported languages."""

    LANGUAGES = {
        # African Languages
        'sw': {
            'name': 'Swahili',
            'native_name': 'Kiswahili',
            'formal_register': 'professional',
            'instructions': 'Use standard Swahili (Kiswahili sanifu). Maintain professional register.',
            'special_chars': 'Standard Latin alphabet',
            'rtl': False,
            'family': 'Bantu',
        },
        'am': {
            'name': 'Amharic',
            'native_name': 'አማርኛ',
            'formal_register': 'professional',
            'instructions': 'Use standard Amharic. Maintain professional register.',
            'special_chars': 'Ethiopic script',
            'rtl': False,
            'family': 'Semitic',
        },
        # European Languages
        'es': {
            'name': 'Spanish',
            'native_name': 'Espanol',
            'formal_register': 'professional',
            'instructions': 'Use international Spanish. Maintain professional register.',
            'special_chars': 'a, e, i, o, u, n, u',
            'rtl': False,
            'family': 'Romance',
            'infinitive_verbs': ['ser', 'gestionar', 'administrar', 'dirigir', 'coordinar', 'supervisar',
                                'ensenar', 'realizar', 'ejecutar', 'desarrollar', 'controlar', 'operar'],
        },
        'fr': {
            'name': 'French',
            'native_name': 'Francais',
            'formal_register': 'professional',
            'instructions': 'Use international French. Maintain professional register.',
            'special_chars': 'a, a, e, e, e, e, i, i, o, u, u, u, y, c',
            'rtl': False,
            'family': 'Romance',
        },
        'de': {
            'name': 'German',
            'native_name': 'Deutsch',
            'formal_register': 'professional',
            'instructions': 'Use standard German (Hochdeutsch). Capitalize all nouns.',
            'special_chars': 'a, o, u, ss',
            'rtl': False,
            'family': 'Germanic',
        },
        'pt': {
            'name': 'Portuguese',
            'native_name': 'Portugues',
            'formal_register': 'professional',
            'instructions': 'Use European Portuguese standard. Maintain professional register.',
            'special_chars': 'a, a, a, a, c, e, e, i, o, o, o, u',
            'rtl': False,
            'family': 'Romance',
        },
        'uk': {
            'name': 'Ukrainian',
            'native_name': 'Українська',
            'formal_register': 'professional',
            'instructions': 'Use standard Ukrainian. Maintain professional register.',
            'special_chars': 'Cyrillic alphabet',
            'rtl': False,
            'family': 'Slavic',
        },
        'bs': {
            'name': 'Bosnian',
            'native_name': 'Bosanski',
            'formal_register': 'professional',
            'instructions': 'Use standard Bosnian. Maintain professional register.',
            'special_chars': 'c, c, dz, s, z',
            'rtl': False,
            'family': 'Slavic',
        },
        # Middle Eastern
        'ar': {
            'name': 'Arabic',
            'native_name': 'العربية',
            'formal_register': 'formal',
            'instructions': 'Use Modern Standard Arabic (MSA). Maintain formal professional register.',
            'special_chars': 'Arabic alphabet',
            'rtl': True,
            'family': 'Semitic',
        },
        # Asian Languages
        'zh-CN': {
            'name': 'Chinese (Simplified)',
            'native_name': '简体中文',
            'formal_register': 'professional',
            'instructions': 'Use Simplified Chinese characters.',
            'special_chars': 'Chinese characters',
            'rtl': False,
            'family': 'Sino-Tibetan',
        },
        'hi': {
            'name': 'Hindi',
            'native_name': 'हिन्दी',
            'formal_register': 'professional',
            'instructions': 'Use standard Hindi in Devanagari script. Maintain professional register.',
            'special_chars': 'Devanagari script',
            'rtl': False,
            'family': 'Indo-Aryan',
        },
    }

    @classmethod
    def get_language_info(cls, lang_code: str) -> dict[str, Any] | None:
        """Get language configuration by code."""
        return cls.LANGUAGES.get(lang_code.lower())

    @classmethod
    def get_supported_languages(cls) -> list[str]:
        """Get list of supported language codes."""
        return sorted(cls.LANGUAGES.keys())

    @classmethod
    def display_language_menu(cls) -> None:
        """Display formatted language selection menu."""
        print("\n" + "=" * 60)
        print("SUPPORTED LANGUAGES")
        print("=" * 60)

        by_family: dict[str, list] = {}
        for code, info in cls.LANGUAGES.items():
            family = info.get('family', 'Other')
            if family not in by_family:
                by_family[family] = []
            by_family[family].append((code, info))

        for family in sorted(by_family.keys()):
            print(f"\n{family} Languages:")
            for code, info in sorted(by_family[family], key=lambda x: x[1]['name']):
                rtl_marker = " [RTL]" if info.get('rtl', False) else ""
                print(f"  [{code:6s}] {info['name']:20s} ({info['native_name']}){rtl_marker}")

        print("\n" + "=" * 60)


# Available LLM providers and their models
LLM_PROVIDERS = {
    'gemini': {
        'name': 'Google Gemini',
        'models': ['gemini-3-flash-preview', 'gemini-2.5-flash', 'gemini-2.5-pro'],
        'default_model': 'gemini-3-flash-preview',
        'env_key': 'GEMINI_API_KEY',
    },
    'openai': {
        'name': 'OpenAI',
        'models': ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo'],
        'default_model': 'gpt-4o-mini',
        'env_key': 'OPENAI_API_KEY',
    },
    'anthropic': {
        'name': 'Anthropic Claude',
        'models': ['claude-sonnet-4-20250514', 'claude-3-5-haiku-20241022'],
        'default_model': 'claude-sonnet-4-20250514',
        'env_key': 'ANTHROPIC_API_KEY',
    },
}
