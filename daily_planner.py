import json
import os
from datetime import date, datetime
from typing import Any, Dict, Optional
from typing import Any, Dict, Optional

# Determine the folder this script lives in
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def load_json(filename):
    """Load a JSON file from the project folder."""
    path = os.path.join(BASE_DIR, filename)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _normalize_key(value):
    if value is None:
        return ""
    return str(value).strip().lower()


def _lookup_day_entry(days_dict, target_key, match_day_type=False):
    """Return (entry, original_key) from a weekday dict using case-insensitive lookup."""
    if not isinstance(days_dict, dict) or not target_key:
        return None, None
    normalized_target = _normalize_key(target_key)
    for original_key, value in days_dict.items():
        if _normalize_key(original_key) == normalized_target:
            return value, original_key
        if (
            match_day_type
            and isinstance(value, dict)
            and _normalize_key(value.get("day_type")) == normalized_target
        ):
            return value, original_key
    return None, None


def _lookup_workout_day(workout_data, day_key):
    days = workout_data.get("days", {})
    if not isinstance(days, dict):
        return None, None
    return _lookup_day_entry(days, day_key)


def _load_planner_entry(planner_data, today_date):
    if not isinstance(planner_data, dict):
        return None
    if planner_data.get("version") != 2:
        return None
    today_iso = today_date.isoformat()
    if planner_data.get("month") != today_iso[:7]:
        return None
    days = planner_data.get("days")
    if not isinstance(days, dict):
        return None
    entry = days.get(today_iso)
    if isinstance(entry, dict):
        return entry
    return None


def _resolve_supplement_entry(supplements_data, weekday_name, forced_day_type_id=None):
    if not isinstance(supplements_data, dict):
        return None, None
    days_struct = supplements_data.get("days")
    if isinstance(days_struct, dict):
        entry = None
        entry_label = None
        if forced_day_type_id:
            entry, entry_label = _lookup_day_entry(
                days_struct, forced_day_type_id, match_day_type=True
            )
        if not entry:
            entry, entry_label = _lookup_day_entry(days_struct, weekday_name)
        return entry, entry_label
    return None, None


def _summarize_biometrics(biometrics):
    if not isinstance(biometrics, dict) or not biometrics:
        return None
    activity = biometrics.get("activity_pattern", {})
    return {
        "sex": biometrics.get("sex"),
        "age": biometrics.get("age"),
        "height_cm": biometrics.get("height_cm"),
        "weight_kg": biometrics.get("current_weight_kg"),
        "goal": biometrics.get("goal"),
        "weekly_change_target": biometrics.get("weekly_weight_change_target_kg"),
        "activity_level": activity.get("job_activity"),
        "training_days_per_week": activity.get("training_days_per_week"),
        "notes": biometrics.get("notes"),
    }


def _summarize_planner(planner_entry, planner_data):
    if not planner_entry:
        return None
    label = None
    if isinstance(planner_data, dict):
        label = planner_data.get("label") or planner_data.get("profile_name")
    return {
        "label": label,
        "day_role": planner_entry.get("day_role"),
        "notes": planner_entry.get("notes"),
        "workout": planner_entry.get("workout"),
        "nutrition": planner_entry.get("nutrition"),
        "supplements": planner_entry.get("supplements"),
    }


def _build_workout_summary(workout_data, planner_entry, weekday_name):
    if not isinstance(workout_data, dict) or not workout_data:
        return None, "No workout.json found or it's empty."

    days = workout_data.get("days", {})
    planner_workout_info = planner_entry.get("workout") if planner_entry else None
    today_workout = None
    workout_source = None

    if isinstance(planner_workout_info, dict):
        planned = planner_workout_info.get("planned")
        planner_day_key = planner_workout_info.get("day_key")
        if planned and planner_day_key:
            today_workout, matched_key = _lookup_workout_day(workout_data, planner_day_key)
            display_key = matched_key or planner_day_key
            if display_key:
                workout_source = f"Planner ({display_key})"
        elif planned is False:
            workout_source = "Planner marked rest/off"

    if today_workout is None and workout_source != "Planner marked rest/off":
        if isinstance(days, dict):
            today_workout = days.get(weekday_name)
        if today_workout is None:
            today_workout, matched_key = _lookup_day_entry(days, weekday_name)
            if matched_key:
                workout_source = matched_key

    if today_workout:
        return (
            {
                "planned": True,
                "focus": today_workout.get("focus", "Unknown"),
                "exercises": today_workout.get("exercises", []),
                "source": workout_source,
            },
            None,
        )

    if workout_source == "Planner marked rest/off":
        return (
            {"planned": False, "source": workout_source},
            "Planner marked today as rest/off.",
        )

    return ({"planned": False}, "No workout scheduled for today (likely a rest day).")


def _build_nutrition_summary(nutrition_data, planner_entry, weekday_name, current_date):
    if not isinstance(nutrition_data, dict) or not nutrition_data:
        return None, "No nutrition.json found or it's empty."

    planner_nutrition_id = None
    if planner_entry:
        planner_nutrition = planner_entry.get("nutrition")
        if isinstance(planner_nutrition, dict):
            planner_nutrition_id = planner_nutrition.get("day_type_id")

    resolved = resolve_nutrition_template(
        nutrition_data, weekday_name, current_date, planner_nutrition_id
    )
    if resolved:
        return (
            {
                "profile_name": resolved.get("profile_name"),
                "plan_label": resolved.get("plan_label"),
                "day_type_label": resolved.get("day_type_label"),
                "role": resolved.get("role"),
                "calories": resolved.get("calories"),
                "macros": resolved.get("macros", {}),
                "meals": resolved.get("meals", []),
                "notes": resolved.get("notes"),
            },
            None,
        )
    return (None, "Nutrition data could not be parsed for today.")


def _build_supplements_summary(supplements_data, planner_entry, weekday_name):
    if not isinstance(supplements_data, dict) or not supplements_data:
        return None, "No supplements.json found or it's empty."

    template_name = supplements_data.get("template_name", "Unnamed template")
    planner_supp_id = None
    if planner_entry:
        planner_supp = planner_entry.get("supplements")
        if isinstance(planner_supp, dict):
            planner_supp_id = planner_supp.get("day_type_id")

    days_struct = supplements_data.get("days")
    if isinstance(days_struct, dict):
        today_supp, _ = _resolve_supplement_entry(
            supplements_data, weekday_name, planner_supp_id
        )
        if today_supp:
            return (
                {
                    "template_name": template_name,
                    "day_type": today_supp.get("day_type", planner_supp_id or "unknown"),
                    "on": today_supp.get("on", True),
                    "protocol": today_supp.get("protocol", []),
                    "notes": today_supp.get("notes"),
                },
                None,
            )
        return (
            {"template_name": template_name, "day_type": None, "on": None, "protocol": [], "notes": None},
            "No specific supplement plan defined for this weekday in 'days'.",
        )

    protocol = supplements_data.get("protocol", [])
    return (
        {
            "template_name": template_name,
            "day_type": None,
            "on": None,
            "protocol": protocol,
            "notes": supplements_data.get("notes"),
        },
        None if protocol else "No protocol entries found.",
    )


def get_daily_plan(target_date: Optional[date] = None) -> Dict[str, Any]:
    """
    Compute the daily plan for the given date using saved JSON data.

    Returns a dictionary with keys:
        - date (YYYY-MM-DD string)
        - weekday (lowercase weekday name)
        - planner (summary dict or None)
        - biometrics (summary dict or None)
        - workout (summary dict or None)
        - nutrition (summary dict or None)
        - supplements (summary dict or None)
        - messages (dict of informational messages per section)
    """
    target_date = target_date or datetime.now().date()
    weekday_name = target_date.strftime("%A")
    weekday_key = weekday_name.lower()

    biometrics = load_json("biometrics.json")
    workout = load_json("workout.json")
    nutrition = load_json("nutrition.json")
    supplements = load_json("supplements.json")
    planner = load_json("planner.json")

    planner_entry = _load_planner_entry(planner, target_date)

    biometrics_summary = _summarize_biometrics(biometrics)
    biometrics_message = (
        None if biometrics else "No biometrics.json found or it's empty."
    )

    workout_summary, workout_message = _build_workout_summary(
        workout, planner_entry, weekday_name
    )

    nutrition_summary, nutrition_message = _build_nutrition_summary(
        nutrition, planner_entry, weekday_name, target_date
    )

    supplements_summary, supplements_message = _build_supplements_summary(
        supplements, planner_entry, weekday_name
    )

    plan = {
        "date": target_date.isoformat(),
        "weekday": weekday_key,
        "planner": _summarize_planner(planner_entry, planner),
        "biometrics": biometrics_summary,
        "workout": workout_summary,
        "nutrition": nutrition_summary,
        "supplements": supplements_summary,
        "messages": {
            "planner": None
            if planner_entry
            else "No planner entry for this date or planner.json missing.",
            "biometrics": biometrics_message,
            "workout": workout_message,
            "nutrition": nutrition_message,
            "supplements": supplements_message,
        },
    }
    return plan


def print_daily_plan(plan: Dict[str, Any]) -> None:
    weekday_display = plan.get("weekday", "").upper()
    print("=" * 50)
    print(f" DAILY PLAN DEBUG VIEW FOR {weekday_display}")
    print("=" * 50)

    planner_info = plan.get("planner")
    if planner_info:
        print("\n[Planner]")
        label = planner_info.get("label")
        if label:
            print(f"  Plan: {label}")
        day_role = planner_info.get("day_role")
        if day_role:
            print(f"  Day role: {day_role}")
        notes = planner_info.get("notes")
        if notes:
            print(f"  Notes: {notes}")

    # Biometrics
    print("\n[Biometrics]")
    biometrics_summary = plan.get("biometrics")
    if biometrics_summary:
        sex = biometrics_summary.get("sex", "?")
        age = biometrics_summary.get("age", "?")
        height = biometrics_summary.get("height_cm", "?")
        weight = biometrics_summary.get("weight_kg", "?")
        goal = biometrics_summary.get("goal", "?")
        print(f"  {sex}, {age} yrs, {height} cm, {weight} kg")
        print(f"  Goal: {goal}")
    else:
        print(f"  {plan['messages'].get('biometrics')}")

    # Workout
    print("\n[Workout]")
    workout_summary = plan.get("workout")
    if workout_summary and workout_summary.get("planned"):
        source = workout_summary.get("source")
        if source:
            print(f"  Source: {source}")
        print(f"  Focus: {workout_summary.get('focus', 'Unknown')}")
        exercises = workout_summary.get("exercises") or []
        if exercises:
            for ex in exercises:
                name = ex.get("name", "Exercise")
                sets = ex.get("sets")
                reps = ex.get("reps")
                duration = ex.get("duration")
                if duration:
                    print(f"   - {name}: {duration}")
                else:
                    print(f"   - {name}: {sets} x {reps}")
        else:
            print("  (No exercises listed for today.)")
    else:
        message = plan["messages"].get("workout") or "No workout scheduled for today (likely a rest day)."
        print(f"  {message}")

    # Nutrition
    print("\n[Nutrition]")
    nutrition_summary = plan.get("nutrition")
    if nutrition_summary:
        print(f"  Profile: {nutrition_summary.get('profile_name', 'Nutrition plan')}")
        plan_label = nutrition_summary.get("plan_label")
        if plan_label:
            print(f"  Plan: {plan_label}")
        label = nutrition_summary.get("day_type_label")
        if label:
            print(f"  Day type: {label}")
        role = nutrition_summary.get("role")
        if role:
            print(f"  Role: {role}")

        calories = nutrition_summary.get("calories")
        macros = nutrition_summary.get("macros") or {}
        if calories is not None:
            print(f"  Calories: {calories}")
        if macros:
            print(
                f"  Macros: P {macros.get('protein_g', '?')}g | "
                f"C {macros.get('carbs_g', '?')}g | "
                f"F {macros.get('fat_g', '?')}g"
            )

        meals = nutrition_summary.get("meals", [])
        if meals:
            print("  Meals:")
            for meal in meals:
                t = meal.get("time", "")
                name = meal.get("name", "Meal")
                label_display = f"{t} - {name}" if t else name
                print(f"   - {label_display}")
        else:
            print("  (No meals listed for today.)")

        notes = nutrition_summary.get("notes")
        if notes:
            print(f"  Notes: {notes}")
    else:
        print(f"  {plan['messages'].get('nutrition')}")

    # Supplements
    print("\n[Supplements]")
    supplements_summary = plan.get("supplements")
    if supplements_summary:
        template_name = supplements_summary.get("template_name", "Unnamed template")
        print(f"  Template: {template_name}")
        day_type = supplements_summary.get("day_type")
        if day_type:
            print(f"  Day type: {day_type}")
        on_flag = supplements_summary.get("on")
        if on_flag is not None:
            print(f"  Stack active today: {'yes' if on_flag else 'no'}")

        protocol = supplements_summary.get("protocol") or []
        if protocol:
            for block in protocol:
                time_label = block.get("time", "Time not set")
                print(f"   [{time_label}]")
                for item in block.get("items", []):
                    name = item.get("name", "Supplement")
                    other_fields = [
                        f"{k}={v}" for k, v in item.items() if k != "name"
                    ]
                    extra = ", ".join(other_fields)
                    if extra:
                        print(f"     - {name} ({extra})")
                    else:
                        print(f"     - {name}")
        else:
            print("  No protocol entries for this day.")
        notes = supplements_summary.get("notes")
        if notes:
            print(f"  Notes: {notes}")
    else:
        message = plan["messages"].get("supplements") or "No supplements.json found or it's empty."
        print(f"  {message}")

    print("\nDone.\n")


def _get_today_from_weekdays(days_struct, weekday_name):
    """
    Look up the entry for the current weekday inside a legacy `days` dict.

    Old schemas stored weekdays in Title Case ("Monday") so we normalise keys.
    """
    if not isinstance(days_struct, dict):
        return None
    lower_map = {str(k).strip().lower(): v for k, v in days_struct.items()}
    return lower_map.get(weekday_name.lower())


def _resolve_weekly_day_type(nutrition_data, weekly_plan_id, weekday_key):
    """Return (day_type_id, plan_label) for a given weekly plan id."""
    weekly_plans = nutrition_data.get("weekly_plans")
    if (
        not weekly_plan_id
        or not isinstance(weekly_plans, dict)
        or weekly_plan_id not in weekly_plans
    ):
        return None, None

    plan = weekly_plans[weekly_plan_id]
    if not isinstance(plan, dict):
        return None, None

    pattern = plan.get("pattern")
    if not isinstance(pattern, dict):
        return None, None

    day_info = pattern.get(weekday_key)
    if not isinstance(day_info, dict):
        return None, None

    return day_info.get("day_type"), plan.get("label") or weekly_plan_id


def _resolve_v3_day_template(nutrition_data, weekday_key, today_date):
    """Return (template_dict, metadata) for the new v3 schema."""
    day_types = nutrition_data.get("day_types")
    if not isinstance(day_types, dict) or not day_types:
        return None

    today_iso = today_date.isoformat()
    month_key = today_iso[:7]
    day_type_id = None
    plan_label = None

    monthly_plans = nutrition_data.get("monthly_plans")
    active_month = nutrition_data.get("active_monthly_plan")
    if (
        isinstance(monthly_plans, dict)
        and active_month
        and active_month == month_key
    ):
        monthly_plan = monthly_plans.get(month_key)
        if isinstance(monthly_plan, dict):
            plan_label = monthly_plan.get("label") or f"Monthly plan {month_key}"
            days_map = monthly_plan.get("days")
            if isinstance(days_map, dict):
                entry = days_map.get(today_iso)
                if isinstance(entry, dict):
                    day_type_id = entry.get("day_type")
            if not day_type_id:
                base_weekly_plan = monthly_plan.get("base_weekly_plan")
                day_type_id, base_label = _resolve_weekly_day_type(
                    nutrition_data, base_weekly_plan, weekday_key
                )
                if day_type_id and not plan_label:
                    plan_label = base_label

    if not day_type_id:
        day_type_id, plan_label = _resolve_weekly_day_type(
            nutrition_data, nutrition_data.get("active_weekly_plan"), weekday_key
        )

    if not day_type_id:
        return None

    template = day_types.get(day_type_id)
    if not isinstance(template, dict):
        return None

    return template, {
        "day_type_id": day_type_id,
        "plan_label": plan_label,
    }


def resolve_nutrition_template(
    nutrition_data, weekday_name, today_date=None, forced_day_type_id=None
):
    """
    Return a dict representing today's nutrition template regardless of schema.

    Keys returned:
        profile_name, day_type_label, day_type_id, calories, macros, meals, notes
    """
    if not nutrition_data:
        return None

    if today_date is None:
        today_date = datetime.now().date()

    weekday_key = weekday_name.lower()
    profile_name = (
        nutrition_data.get("profile_name")
        or nutrition_data.get("template_name")
        or "Nutrition plan"
    )
    version = nutrition_data.get("version")
    day_types = nutrition_data.get("day_types")

    if forced_day_type_id and isinstance(day_types, dict):
        template = day_types.get(forced_day_type_id)
        if isinstance(template, dict):
            return {
                "profile_name": profile_name,
                "plan_label": "Planner override",
                "day_type_label": template.get("label") or forced_day_type_id,
                "day_type_id": forced_day_type_id,
                "calories": template.get("calories"),
                "macros": template.get("macros", {}),
                "meals": template.get("meals", []),
                "notes": nutrition_data.get("notes"),
                "role": template.get("role"),
            }

    if version == 3 and isinstance(day_types, dict):
        v3_template = _resolve_v3_day_template(nutrition_data, weekday_key, today_date)
        if v3_template:
            template, metadata = v3_template
            return {
                "profile_name": profile_name,
                "plan_label": metadata.get("plan_label"),
                "day_type_label": template.get("label") or metadata.get("day_type_id"),
                "day_type_id": metadata.get("day_type_id"),
                "calories": template.get("calories"),
                "macros": template.get("macros", {}),
                "meals": template.get("meals", []),
                "notes": nutrition_data.get("notes"),
                "role": template.get("role"),
            }

    if (
        version == 2
        and isinstance(day_types, dict)
        and isinstance(nutrition_data.get("weekly_pattern"), dict)
    ):
        weekly_pattern = nutrition_data["weekly_pattern"]
        pattern_entry = weekly_pattern.get(weekday_key)
        if not pattern_entry:
            return {
                "profile_name": profile_name,
                "day_type_label": None,
                "day_type_id": None,
                "calories": None,
                "macros": {},
                "meals": [],
                "notes": "No weekly pattern entry for this weekday.",
            }

        day_type_id = pattern_entry.get("day_type")
        day_types = nutrition_data["day_types"]
        template = day_types.get(day_type_id)
        if not template:
            missing_note = (
                f"Weekly pattern references '{day_type_id}' "
                "but it was not found under day_types."
            )
            return {
                "profile_name": profile_name,
                "day_type_label": day_type_id,
                "day_type_id": day_type_id,
                "calories": None,
                "macros": {},
                "meals": [],
                "notes": missing_note,
            }

        return {
            "profile_name": profile_name,
            "day_type_label": template.get("label") or day_type_id,
            "day_type_id": day_type_id,
            "calories": template.get("calories"),
            "macros": template.get("macros", {}),
            "meals": template.get("meals", []),
            "notes": nutrition_data.get("notes"),
        }

    # ---- Legacy weekly schema with explicit per-day entries ----
    days_struct = nutrition_data.get("days")
    if isinstance(days_struct, dict) and days_struct:
        today_entry = _get_today_from_weekdays(days_struct, weekday_name)
        if today_entry:
            return {
                "profile_name": profile_name,
                "day_type_label": today_entry.get("day_type")
                or today_entry.get("label")
                or weekday_name,
                "day_type_id": today_entry.get("day_type"),
                "calories": today_entry.get("calories")
                or nutrition_data.get("default_calories"),
                "macros": today_entry.get("macros", nutrition_data.get("default_macros", {})),
                "meals": today_entry.get("meals", []),
                "notes": nutrition_data.get("notes"),
            }

        return {
            "profile_name": profile_name,
            "day_type_label": None,
            "day_type_id": None,
            "calories": None,
            "macros": {},
            "meals": [],
            "notes": f"No specific nutrition defined for {weekday_name} in 'days'.",
        }

    # ---- Legacy single-template schema ----
    return {
        "profile_name": profile_name,
        "day_type_label": nutrition_data.get("template_name") or weekday_name,
        "day_type_id": "default",
        "calories": nutrition_data.get("calories"),
        "macros": nutrition_data.get("macros", {}),
        "meals": nutrition_data.get("meals", []),
        "notes": nutrition_data.get("notes"),
    }

def main():
    plan = get_daily_plan()
    print_daily_plan(plan)


if __name__ == "__main__":
    main()
