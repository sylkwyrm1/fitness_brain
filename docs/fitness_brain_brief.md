fitness_brain — Project Brief

(For ChatGPT / Code Assistants working inside VS Code)

1. Overview

fitness_brain is a modular personal fitness & nutrition assistant.
Each domain (“expert”) owns its own JSON file.
Experts can read all other expert JSONs via shared_state but may write only to their own JSON when the user issues a Save command (CLI :save or Streamlit Save button).

Everything flows through a central orchestrator (expert_core.py) and a shared preferences system (preferences_manager.py).

The project has two front-ends:

A CLI (multi_expert_cli.py)

A Streamlit app (streamlit_app.py)

Both use the same experts and the same JSON files.

2. Experts & Their JSON Files

Each expert has:

A system prompt (text instructions)

An expert-specific JSON schema

Read-only access to other experts via shared_state

Write access only to its own JSON on Save

Current experts:

2.1 Biometrics — biometrics.json

Sex, age, height, weight, goal (cut/maintain/bulk), activity level, etc.

2.2 Workout — workout.json

Human-readable weekday-based plan:

days[Weekday].exercises[] = {
    name,
    sets,
    reps (string, e.g. "6–8"),
    rest_seconds,
    target_rpe
}

2.3 Nutrition — nutrition.json

Weekly templates with:

calories, macros

meal slots with times

direct food items

recipe links:
recipe_links[Day][MealName] = {recipe_id, servings}

2.4 Supplements — supplements.json

Stack templates, adaptogen break rules, timing rules.

2.5 Recipes — recipes.json

Full recipe database:

id, name, meal_type, tags

ingredients, instructions

per-serving macros

2.6 Pantry — pantry.json

User’s food inventory with:

id, name, category

is_staple

status: in_stock / low / out / unknown

3. Logs & Derived Data
3.1 Workout Log — data/raw/workout_log.csv

Per-set logging:
date, exercise, set_number, planned_reps, actual_reps, weight, rpe, notes

3.2 Workout History — data/processed/workout_history.json

Aggregated stats per exercise:

recent sessions

min/max/avg values

top-set trends
Used by the Workout Expert for smarter next-set suggestions.

4. Shared Preferences System
4.1 File: data/config/preferences.json

Single source of truth for cross-cutting preferences.

Top-level structure:

schema_version
global
workout
nutrition
supplements
schedule
daily_planner


Example fields:

global.fasting_protocol

schedule.typical_wake_time

daily_planner.respect_fasting_windows

nutrition.meal_timing_preferences

and optional notes fields for free-form “memory-like” info.

4.2 File: preferences_manager.py

API:

load_preferences() -> dict

save_preferences(prefs: dict)

get_pref(section, key, default)

set_pref(section, key, value, meta=None)

Always ensures all sections exist.
Writes directly to preferences.json.

4.3 Expert-triggered updates

Experts (starting with Workout Expert) can emit:

"_preferences_updates": {
    "global": {...},
    "daily_planner": {...},
    "nutrition": {...}
}


The orchestrator in expert_core.py pops this key, applies updates via preferences_manager.set_pref, and removes it from the expert’s JSON before saving.

5. Orchestrator (expert_core.py)
Key responsibilities:

Load expert JSONs into a combined shared_state

Load workout history

Load preferences (preferences_manager)

Central function:

build_shared_state() -> dict

Update preferences when experts emit _preferences_updates:

handle_workout_preferences_from_expert_state()

apply_preferences_updates()

6. Interfaces
6.1 CLI (multi_expert_cli.py)

Menu of experts

Chat-style interface per expert

Explicit :save to write JSON

On Workout save: preferences update hook fires

shared_state = build_shared_state() at startup

6.2 Streamlit (streamlit_app.py)

Pages:

Daily Planner — shows workout, nutrition, supplements, preferences

Experts — chat with Save button

Workout Log — session runner with rest timer & autofill

Workout History

Shopping List

Uses the same orchestrator and preferences system.

7. Your Working Rules (for assistants)

One change at a time (avoid big refactors).

Never alter expert JSON schemas without explicit request.

When I ask for a code change, modify only the mentioned files.

Respect the architecture:

Experts write only their own JSON.

Shared prefs handled only through preferences_manager.py and orchestrator.

Don’t modify my venv / git / Streamlit Cloud setup.

Be direct and practical; no fluff.

8. Goals for Future Development

These are NOT implemented yet but important context:

Fasting window support in Daily Planner (shift meal times automatically).

Structured and free-text preference “memory”.

More experts contributing to the shared preferences.

Pantry-aware meal planning and shopping lists.

Workout blocks / rotations as modules.

Potential schedule expert for wake/sleep/work blocks.

If you read this file, you should fully understand the architecture, the rules, and how to make safe incremental improvements to the project.