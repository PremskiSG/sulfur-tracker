"""config.yaml loader. Cached; call load_config.cache_clear() in tests if needed."""
from __future__ import annotations

from functools import lru_cache

import yaml

from sulfur_tracker.paths import config_path


@lru_cache(maxsize=1)
def load_config() -> dict:
    p = config_path()
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def collectors_config() -> dict:
    return load_config().get("collectors", {})


def collector_config(name: str) -> dict:
    return collectors_config().get(name, {}) or {}


def scoring_config() -> dict:
    return load_config().get("scoring", {}) or {}


def baselines() -> dict:
    return load_config().get("baselines", {}) or {}


def http_config() -> dict:
    return load_config().get("http", {}) or {}


def headline_cadence_days() -> int:
    return int(load_config().get("headline_cadence_days", 14))
