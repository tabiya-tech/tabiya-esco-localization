"""
Pluggable LLM provider for Ethiopia stage-2 matching.

Two providers, common interface:
    provider.generate_json(prompt, system=None) -> dict | None

Selected via config.json `llm` block (see make_provider).

Provider                  Env var(s)                       Default model
gemini      Google AI    GEMINI_API_KEY or GOOGLE_API_KEY  gemini-3-flash-preview
deepseek    DeepSeek     DEEPSEEK_API_KEY                  deepseek-chat

DeepSeek's API is OpenAI-compatible (https://api.deepseek.com/v1/chat/completions).
The provider uses `requests` directly so no extra SDK dependency is required.
"""

from __future__ import annotations

import json
import os
import time
from typing import Optional

import requests


class LLMError(RuntimeError):
    pass


class BaseLLMProvider:
    """Common interface. Both providers return parsed JSON or None on failure."""

    name: str = "base"

    def generate_json(self, prompt: str, system: Optional[str] = None) -> Optional[dict]:
        raise NotImplementedError


class GeminiProvider(BaseLLMProvider):
    name = "gemini"

    def __init__(self, model: str = "gemini-3-flash-preview", api_key: Optional[str] = None,
                 max_retries: int = 5, retry_base_delay: float = 8.0):
        self.model_name = model
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not self.api_key:
            raise LLMError("GEMINI_API_KEY / GOOGLE_API_KEY not set")
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        # Lazy import so DeepSeek-only users don't need google-generativeai installed.
        import google.generativeai as genai
        genai.configure(api_key=self.api_key)
        self._model = genai.GenerativeModel(self.model_name)

    def generate_json(self, prompt: str, system: Optional[str] = None) -> Optional[dict]:
        full = prompt if not system else f"{system}\n\n{prompt}"
        delay = self.retry_base_delay
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._model.generate_content(
                    full,
                    generation_config={"response_mime_type": "application/json"},
                )
                text = (resp.text or "").strip()
                return json.loads(text)
            except json.JSONDecodeError:
                return None
            except Exception as e:
                msg = str(e).lower()
                if any(t in msg for t in ("429", "quota", "rate", "503", "500", "deadline")):
                    if attempt < self.max_retries:
                        time.sleep(delay)
                        delay *= 2
                        continue
                return None
        return None


class DeepSeekProvider(BaseLLMProvider):
    name = "deepseek"

    def __init__(self, model: str = "deepseek-chat",
                 base_url: str = "https://api.deepseek.com/v1",
                 api_key: Optional[str] = None,
                 max_retries: int = 5, retry_base_delay: float = 8.0,
                 temperature: float = 0.0, timeout: float = 60.0):
        self.model_name = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise LLMError("DEEPSEEK_API_KEY not set")
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        self.temperature = temperature
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        })

    def generate_json(self, prompt: str, system: Optional[str] = None) -> Optional[dict]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body = {
            "model": self.model_name,
            "messages": messages,
            "temperature": self.temperature,
            "response_format": {"type": "json_object"},
        }
        url = f"{self.base_url}/chat/completions"
        delay = self.retry_base_delay
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._session.post(url, json=body, timeout=self.timeout)
                if resp.status_code in (429, 500, 502, 503, 504):
                    if attempt < self.max_retries:
                        time.sleep(delay)
                        delay *= 2
                        continue
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return json.loads(content)
            except json.JSONDecodeError:
                return None
            except requests.RequestException:
                if attempt < self.max_retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                return None
            except (KeyError, IndexError):
                return None
        return None


def make_provider(config: dict) -> BaseLLMProvider:
    """Build a provider from a config dict. Expected shape:
        {
          "provider": "gemini" | "deepseek",
          "gemini":   {"model": "..."},
          "deepseek": {"model": "...", "base_url": "..."}
        }
    """
    name = (config.get("provider") or "").strip().lower()
    if name == "gemini":
        params = config.get("gemini") or {}
        return GeminiProvider(model=params.get("model", "gemini-3-flash-preview"))
    if name == "deepseek":
        params = config.get("deepseek") or {}
        return DeepSeekProvider(
            model=params.get("model", "deepseek-chat"),
            base_url=params.get("base_url", "https://api.deepseek.com/v1"),
        )
    raise LLMError(f"Unknown llm provider: {name!r}. Use 'gemini' or 'deepseek'.")
