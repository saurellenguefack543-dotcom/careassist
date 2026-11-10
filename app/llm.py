"""Couche LLM compatible OpenAI (Groq, OpenAI, Ollama, LM Studio, vLLM…).

Ordre de sélection :
  1. GROQ_API_KEY            -> https://api.groq.com/openai/v1, modèle GROQ_MODEL
  2. OPENAI_BASE_URL/API_KEY -> n'importe quel endpoint compatible OpenAI
  3. aucun                   -> None (le moteur de règles déterministe prend le relais)
"""
from __future__ import annotations

import logging

import httpx

from . import config

log = logging.getLogger("careassist.llm")


class LLMClient:
    def __init__(self, base_url: str, api_key: str, model: str, provider: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.provider = provider

    def chat(self, messages: list[dict], temperature: float = 0.3, max_tokens: int = 300) -> str:
        r = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"model": self.model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens},
            timeout=float(config.env("LLM_TIMEOUT", "15")),
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()


def get_llm() -> LLMClient | None:
    if config.env("LLM_DISABLED", "") in ("1", "true", "yes"):
        return None
    groq = config.env("GROQ_API_KEY")
    if groq:
        return LLMClient("https://api.groq.com/openai/v1", groq, config.env("GROQ_MODEL", "llama-3.3-70b-versatile"), "groq")
    base = config.env("OPENAI_BASE_URL")
    key = config.env("OPENAI_API_KEY")
    if base or key:
        return LLMClient(base or "https://api.openai.com/v1", key or "none", config.env("OPENAI_MODEL", "gpt-4o-mini"), "openai-compatible")
    return None


def provider_name() -> str:
    c = get_llm()
    return c.provider if c else "rules"
