from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

WORKOUT_HISTORY_PATH = Path("data/processed/workout_history.json")


def load_workout_history() -> Dict[str, Any] | None:
    """
    Load workout history from data/processed/workout_history.json if it exists.
    Returns the parsed dict, or None if the file is missing or invalid.
    """
    if not WORKOUT_HISTORY_PATH.exists():
        return None
    try:
        with WORKOUT_HISTORY_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None
