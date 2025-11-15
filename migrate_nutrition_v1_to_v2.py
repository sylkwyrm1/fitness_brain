import json
import re
from pathlib import Path

WEEKDAYS = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]

BASE_DIR = Path(__file__).resolve().parent
SOURCE_FILE = BASE_DIR / "nutrition.json"
TARGET_FILE = BASE_DIR / "nutrition_v2.json"


def slugify(label: str, fallback: str) -> str:
    """Convert a label into a simple snake_case identifier."""
    base = re.sub(r"[^a-z0-9]+", "_", (label or "").lower()).strip("_")
    if not base:
        base = re.sub(r"[^a-z0-9]+", "_", fallback.lower()).strip("_")
    return base or "day"


def normalise_weekday_key(name: str) -> str:
    return str(name).strip().lower()


def build_template_payload(day_data: dict, root_defaults: dict) -> dict:
    """Create the payload stored under a day_type entry."""
    calories = day_data.get("calories")
    if calories is None:
        calories = root_defaults.get("default_calories") or root_defaults.get("calories")

    macros = day_data.get("macros")
    if not macros:
        macros = root_defaults.get("default_macros") or root_defaults.get("macros") or {}

    meals = day_data.get("meals")
    if meals is None:
        meals = root_defaults.get("meals", [])

    label = day_data.get("label") or day_data.get("day_type")
    if not label:
        label = root_defaults.get("template_name") or "Daily template"

    return {
        "label": label,
        "calories": calories,
        "macros": macros,
        "meals": meals,
    }


def convert_v1_to_v2(data: dict) -> dict:
    """Convert any legacy nutrition JSON into the new version 2 schema."""
    day_types = {}
    weekly_pattern = {}
    template_lookup = {}

    days_struct = data.get("days")
    if isinstance(days_struct, dict) and days_struct:
        normalised_days = {
            normalise_weekday_key(k): v for k, v in days_struct.items() if isinstance(v, dict)
        }
    else:
        normalised_days = {}

    if normalised_days:
        fallback_entry = next(iter(normalised_days.values()))
        for weekday in WEEKDAYS:
            source = normalised_days.get(weekday, fallback_entry)
            payload = build_template_payload(source, data)
            payload_key = json.dumps(payload, sort_keys=True)

            if payload_key in template_lookup:
                day_type_id = template_lookup[payload_key]
            else:
                label_hint = source.get("day_type") or source.get("label") or weekday
                day_type_id = slugify(label_hint, weekday)
                base_id = day_type_id
                counter = 2
                while day_type_id in day_types:
                    day_type_id = f"{base_id}_{counter}"
                    counter += 1
                template_lookup[payload_key] = day_type_id
                day_types[day_type_id] = payload

            weekly_pattern[weekday] = {"day_type": day_type_id}
    else:
        payload = build_template_payload(data, data)
        day_types["default"] = payload
        weekly_pattern = {weekday: {"day_type": "default"} for weekday in WEEKDAYS}

    profile_name = data.get("profile_name") or data.get("template_name") or "Default Profile"
    notes = data.get("notes")

    converted = {
        "version": 2,
        "profile_name": profile_name,
        "day_types": day_types,
        "weekly_pattern": weekly_pattern,
    }
    if notes:
        converted["notes"] = notes

    return converted


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


def main():
    legacy = load_v1_data()
    if legacy is None:
        return

    if legacy.get("version") == 2:
        print("[i] nutrition.json already appears to be version 2. No new file created.")
        return

    converted = convert_v1_to_v2(legacy)

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
