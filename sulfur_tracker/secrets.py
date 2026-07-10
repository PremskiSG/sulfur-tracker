"""Optional secrets.yaml loader. All keys are optional; collectors degrade to
manual entry when a key is absent."""
from __future__ import annotations

from functools import lru_cache

import yaml

from sulfur_tracker.paths import secrets_path


@lru_cache(maxsize=1)
def load_secrets() -> dict:
    p = secrets_path()
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def get(key: str, default=None):
    return load_secrets().get(key, default)


def get_secret(section: str, key: str, env_var: str | None = None):
    """Nested lookup (env var wins), matching miner_tracker's secrets shape, e.g.
        deepseek:
          api_key: "..."
    """
    if env_var:
        import os
        val = os.environ.get(env_var)
        if val:
            return val
    return (load_secrets().get(section) or {}).get(key) or None
