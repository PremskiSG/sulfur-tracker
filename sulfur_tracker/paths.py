"""Filesystem anchors. Stateful files (config.yaml, data/, reports/, secrets.yaml)
live under home_dir(), which defaults to the project root. Set SULFUR_TRACKER_HOME
to relocate (used by tests via tmp_path).
"""
from __future__ import annotations

import os
from pathlib import Path


def home_dir() -> Path:
    env = os.environ.get("SULFUR_TRACKER_HOME")
    if env:
        return Path(env).expanduser()
    # sulfur_tracker/sulfur_tracker/paths.py -> project root
    return Path(__file__).resolve().parent.parent


def config_path() -> Path:
    return home_dir() / "config.yaml"


def secrets_path() -> Path:
    return home_dir() / "secrets.yaml"


def data_dir() -> Path:
    return home_dir() / "data"


def db_path() -> Path:
    return data_dir() / "sulfur_tracker.db"


def reports_dir() -> Path:
    return home_dir() / "reports"


def dashboard_module() -> Path:
    return Path(__file__).resolve().parent / "dashboard.py"
