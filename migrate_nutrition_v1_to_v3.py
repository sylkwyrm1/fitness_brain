import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SOURCE_FILE = BASE_DIR / "nutrition.json"
TARGET_FILE = BASE_DIR / "nutrition_v3.json"


def load_v1_data():
    if not SOURCE_FILE.exists():
        print(f"[!] {SOURCE_FILE.name} does not exist. Nothing to migrate.")
        return None
    try:
        with SOURCE_FILE.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        print(f"[!] Could not parse {SOURCE_FILE.name}: {exc}")
        return None


def build_v3_from_v1(data):
    profile_name = (
        data.get("profile_name") or data.get("template_name") or "Default Profile"
    )
    day_label = data.get("template_name") or "Default Day"
    calories = data.get("calories") or data.get("default_calories")
    macros = data.get("macros") or data.get("default_macros") or {}
    meals = data.get("meals", [])

    day_types = {
        "default_day": {
            "label": day_label,
            "role": "other",
            "calories": calories,
            "macros": macros,
            "meals": meals,
        }
    }

    converted = {
        "version": 3,
        "profile_name": profile_name,
        "day_types": day_types,
        "weekly_plans": {},
        "monthly_plans": {},
        "active_weekly_plan": None,
        "active_monthly_plan": None,
    }

    notes = data.get("notes")
    if notes:
        converted["notes"] = notes

    return converted


def main():
    legacy = load_v1_data()
    if legacy is None:
        return

    if legacy.get("version") == 3:
        print("[i] nutrition.json already appears to be version 3. No new file created.")
        return

    converted = build_v3_from_v1(legacy)

    if TARGET_FILE.exists():
        print(
            f"[!] {TARGET_FILE.name} already exists. Move or delete it before running the migration."
        )
        return

    with TARGET_FILE.open("w", encoding="utf-8") as handle:
        json.dump(converted, handle, indent=2, ensure_ascii=False)

    print(
        f"[OK] Created {TARGET_FILE.name} using data from {SOURCE_FILE.name}. "
        "Review the new file and replace nutrition.json manually when ready."
    )


if __name__ == "__main__":
    main()
