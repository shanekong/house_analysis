from __future__ import annotations

import os
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_SQLITE_PATH = BACKEND_DIR / "data" / "house_analysis.db"


def database_url() -> str:
    """Return the configured database URL, defaulting to a local SQLite file."""

    configured = os.getenv("HOUSE_DATABASE_URL")
    if configured:
        return configured
    DEFAULT_SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{DEFAULT_SQLITE_PATH}"

