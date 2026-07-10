"""DeepSeek helper via DeepSeek's Anthropic-compatible endpoint — the same setup as
miner_tracker (key in secrets.yaml under `deepseek: api_key`, or DEEPSEEK_API_KEY env).
Used by the monthly LLM price scanner to read official prices out of free news text.
Optional: with no key, callers degrade to manual entry.
"""
from __future__ import annotations

import json
import re

from sulfur_tracker.secrets import get_secret

DEFAULT_BASE_URL = "https://api.deepseek.com/anthropic"
# USD per MTok (input, output) — from the user's miner_tracker registry.
PRICES = {"deepseek-v4-pro": (0.435, 0.87), "deepseek-v4-flash": (0.14, 0.28)}


def has_key() -> bool:
    return bool(get_secret("deepseek", "api_key", env_var="DEEPSEEK_API_KEY"))


def _client():
    import anthropic
    key = get_secret("deepseek", "api_key", env_var="DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("no DeepSeek key: set DEEPSEEK_API_KEY or secrets.yaml "
                           "deepseek.api_key")
    base = get_secret("deepseek", "base_url", env_var="DEEPSEEK_BASE_URL") or DEFAULT_BASE_URL
    return anthropic.Anthropic(api_key=key, base_url=base)


def parse_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in response")
    return json.loads(text[start:end + 1])


def extract(prompt: str, system: str, model: str = "deepseek-v4-flash",
            max_tokens: int = 1024) -> dict:
    """Send prompt to DeepSeek and return the parsed JSON object it replies with."""
    resp = _client().messages.create(
        model=model, max_tokens=max_tokens, system=system,
        thinking={"type": "disabled"},   # required by DeepSeek's endpoint
        messages=[{"role": "user", "content": prompt}],
    )
    raw = next((b.text for b in resp.content if b.type == "text"), "")
    return parse_json(raw)
