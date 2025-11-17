import json
from pathlib import Path
from typing import Any, Dict, Optional

PREFS_PATH = Path("data/config/preferences.json")

DEFAULT_PREFS: Dict[str, Any] = {
    "schema_version": 1,
    "global": {
        "diet_style": None,
        "fasting_protocol": None,
        "preferred_training_environment": None,
        "notes": "",
    },
    "workout": {
        "preferred_training_days": [],
        "preferred_split_name": None,
        "session_duration_minutes": None,
        "deload_strategy": None,
    },
    "nutrition": {
        "diet_style": None,
        "meal_timing_preferences": {
            "fasting_protocol": None,
            "first_meal_time": None,
            "last_meal_time": None,
        },
        "calorie_targets": {},
        "macro_preferences": {
            "protein_grams_per_kg": None,
            "carb_emphasis": None,
            "fat_emphasis": None,
        },
    },
    "supplements": {
        "caffeine_cutoff_time": None,
        "adaptogen_break_pattern": None,
        "preferred_forms": [],
        "stack_rotation_notes": "",
    },
    "schedule": {
        "typical_wake_time": None,
        "typical_sleep_time": None,
        "work_blocks": [],
        "commute_windows": [],
    },
    "daily_planner": {
        "respect_fasting_windows": False,
        "respect_caffeine_cutoff": False,
        "default_day_type_overrides": {},
    },
}


def _ensure_sections(prefs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge whatever is on disk with DEFAULT_PREFS so we always have all sections.
    Disk values win for existing keys; defaults fill the gaps.
    """
    merged: Dict[str, Any] = {}

    disk_version = prefs.get("schema_version")
    if isinstance(disk_version, int):
        merged["schema_version"] = disk_version
    else:
        merged["schema_version"] = DEFAULT_PREFS["schema_version"]

    for section_name in (
        "global",
        "workout",
        "nutrition",
        "supplements",
        "schedule",
        "daily_planner",
    ):
        default_section = DEFAULT_PREFS.get(section_name, {})
        disk_section = prefs.get(section_name) or {}

        if not isinstance(disk_section, dict):
            disk_section = {}

        merged_section = {**default_section, **disk_section}
        merged[section_name] = merged_section

    return merged


def load_preferences() -> Dict[str, Any]:
    """
    Load preferences from disk, creating the file with defaults if needed.
    Always returns a dict with all expected sections.
    """
    if not PREFS_PATH.exists():
        PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        prefs = DEFAULT_PREFS.copy()
        save_preferences(prefs)
        return prefs

    try:
        with PREFS_PATH.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            raise ValueError("preferences.json is not a JSON object")
    except Exception:
        # If the file is corrupt or unreadable, fall back to defaults in memory
        raw = {}

    prefs = _ensure_sections(raw)
    return prefs


def save_preferences(prefs: Dict[str, Any]) -> None:
    """
    Persist preferences to disk. Assumes prefs already has all sections.
    """
    PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PREFS_PATH.open("w", encoding="utf-8") as f:
        json.dump(prefs, f, indent=2, ensure_ascii=False)


def get_pref(section: str, key: str, default: Optional[Any] = None) -> Any:
    """
    Convenience getter that reads from disk each time.
    Suitable for low-frequency reads (alpha).
    """
    prefs = load_preferences()
    section_dict = prefs.get(section) or {}
    if not isinstance(section_dict, dict):
        return default
    return section_dict.get(key, default)


def set_pref(
    section: str,
    key: str,
    value: Any,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Set a single preference value, write to disk, and return the updated preferences dict.

    The `meta` argument is accepted for future use but ignored in this MVP.
    """
    prefs = load_preferences()

    if section not in prefs or not isinstance(prefs[section], dict):
        prefs[section] = {}

    prefs[section][key] = value

    # Future: optionally track meta (source_expert, updated_at, etc.)
    # For now, we ignore `meta` to keep the storage format simple.

    save_preferences(prefs)
    return prefs
