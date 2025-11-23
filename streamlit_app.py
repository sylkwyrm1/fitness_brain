# Streamlit entrypoint for the Fitness Brain app
# Run locally with:
#   streamlit run streamlit_app.py

import json
import os
import time
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv
from shopping_list import (
    generate_shopping_list_for_plan,
    generate_shopping_list_from_nutrition,
    load_recipes,
)

from daily_planner import get_daily_plan
from expert_core import (
    EXPERTS,
    NUTRITION_FILE,
    RECIPES_FILE,
    load_json,
    run_expert_turn,
    save_json,
    start_expert_session,
)
from backend_client import save_biometrics, set_token as backend_set_token

try:
    from expert_core import build_shared_state
except ImportError:
    from expert_core import load_shared_state as _legacy_load_shared_state

    def build_shared_state():
        return _legacy_load_shared_state()

try:
    from expert_core import handle_preferences_from_expert_state
except ImportError:
    from expert_core import (
        handle_workout_preferences_from_expert_state as _legacy_handle_preferences_from_expert_state,
    )

    def handle_preferences_from_expert_state(
        expert_state, shared_state
    ):  # pragma: no cover - legacy fallback for hosted deployments
        return _legacy_handle_preferences_from_expert_state(
            expert_state, shared_state
        )
from workout_log import append_workout_log_row, load_workout_log
from state_utils import load_workout_history

load_dotenv()
BACKEND_URL = os.getenv("BACKEND_URL") or st.secrets.get("BACKEND_URL", None)
DEFAULT_BACKEND_EMAIL = os.getenv("BACKEND_EMAIL") or st.secrets.get("BACKEND_EMAIL", "")
DEFAULT_BACKEND_PASSWORD = os.getenv("BACKEND_PASSWORD") or st.secrets.get(
    "BACKEND_PASSWORD", ""
)
AUTH_CACHE_PATH = os.path.expanduser("~/.fitness_brain_auth.json")


def _planned_reps_to_int(val) -> int:
    """Convert planned rep strings like '8' or '6-8' into an integer fallback."""
    if val is None:
        return 0
    try:
        return int(val)
    except (TypeError, ValueError):
        pass
    if isinstance(val, str) and "-" in val:
        parts = val.split("-")
        try:
            return int(parts[0].strip())
        except (ValueError, IndexError):
            return 0
    return 0


def _format_metric_value(val) -> str:
    """Format numeric metric values, falling back to an em dash when missing."""
    if val is None or val == "":
        return "—"
    try:
        if isinstance(val, float):
            return f"{val:.2f}".rstrip("0").rstrip(".") or "0"
        return str(val)
    except Exception:
        return str(val)


def build_planned_sets_for_date(selected_date: date) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Convert the saved workout plan for a date into per-set rows."""
    plan: Dict[str, Any] = {}
    try:
        plan = get_daily_plan(selected_date)
        workout_info = plan.get("workout") or {}
        exercises = workout_info.get("exercises") or []
    except Exception:
        exercises = []

    planned_rows: List[Dict[str, Any]] = []
    for ex in exercises:
        name = ex.get("name") or "Exercise"
        sets = ex.get("sets", 0) or 0
        reps = ex.get("reps", "")
        rest_seconds = ex.get("rest_seconds")
        target_rpe = ex.get("target_rpe")

        try:
            sets_int = int(sets)
        except (TypeError, ValueError):
            sets_int = 0

        try:
            rest_int = int(rest_seconds) if rest_seconds is not None else None
        except (TypeError, ValueError):
            rest_int = None

        try:
            target_rpe_val = float(target_rpe) if target_rpe is not None else None
        except (TypeError, ValueError):
            target_rpe_val = None

        for set_idx in range(1, sets_int + 1):
            planned_rows.append(
                {
                    "exercise": name,
                    "set_number": set_idx,
                    "planned_reps": str(reps),
                    "rest_seconds": rest_int,
                    "target_rpe": target_rpe_val,
                }
            )
    return planned_rows, plan


def _planned_signature(planned_rows: List[Dict[str, Any]]) -> List[Tuple[Any, ...]]:
    """Create a simple signature for the planned sets so we can detect changes."""
    return [
        (
            row.get("exercise"),
            row.get("set_number"),
            row.get("planned_reps"),
            row.get("rest_seconds"),
            row.get("target_rpe"),
        )
        for row in planned_rows
    ]


def initialise_workout_state(selected_date: date, planned_rows: List[Dict[str, Any]]) -> None:
    """Populate st.session_state for the session runner based on the selected date."""
    date_str = selected_date.isoformat()
    log_df = load_workout_log()
    if not log_df.empty:
        log_df = log_df[log_df["date"] == date_str]

    sets_state: List[Dict[str, Any]] = []
    for idx, row in enumerate(planned_rows):
        log_entry = None
        if not log_df.empty:
            mask = (log_df["exercise"] == row["exercise"]) & (
                log_df["set_number"].astype(str) == str(row["set_number"])
            )
            if mask.any():
                log_entry = log_df[mask].iloc[0].to_dict()

        status = "completed" if log_entry else "pending"
        sets_state.append(
            {
                "index": idx,
                "exercise": row["exercise"],
                "set_number": row["set_number"],
                "planned_reps": row["planned_reps"],
                "rest_seconds": row.get("rest_seconds"),
                "target_rpe": row.get("target_rpe"),
                "status": status,
                "log": log_entry,
            }
        )

    pending_indices = [s["index"] for s in sets_state if s["status"] == "pending"]
    current_index = pending_indices[0] if pending_indices else None

    st.session_state["workout_state"] = {
        "date": date_str,
        "sets": sets_state,
        "current_index": current_index,
        "rest_active": False,
        "rest_end_time": None,
        "rest_exercise": None,
        "plan_signature": _planned_signature(planned_rows),
    }


def move_to_next_pending_set(state: Dict[str, Any], after_index: Optional[int] = None) -> None:
    """Advance the current set pointer to the next pending set."""
    sets = state.get("sets", [])
    pending = sorted(s["index"] for s in sets if s["status"] == "pending")
    if not pending:
        state["current_index"] = None
        return

    if after_index is not None:
        for idx in pending:
            if idx > after_index:
                state["current_index"] = idx
                return

    state["current_index"] = pending[0]


def ensure_workout_state_for_date(selected_date: date, planned_rows: List[Dict[str, Any]]) -> None:
    """Ensure the workout session state exists for the selected date/plan."""
    expected_signature = _planned_signature(planned_rows)
    date_str = selected_date.isoformat()
    state = st.session_state.get("workout_state")
    if (
        state is None
        or state.get("date") != date_str
        or state.get("plan_signature") != expected_signature
    ):
        initialise_workout_state(selected_date, planned_rows)
    else:
        state["plan_signature"] = expected_signature


def update_current_index_after_completion(state: Dict[str, Any]) -> None:
    """Move the pointer to the next pending set after completing one."""
    move_to_next_pending_set(state, after_index=state.get("current_index"))


st.set_page_config(page_title="Fitness Brain - Daily Planner", layout="wide")


def _login_to_backend(email: str, password: str) -> bool:
    """Attempt to log in to the backend and cache the token for this session."""
    if not BACKEND_URL:
        st.error("BACKEND_URL is not configured.")
        return False
    try:
        resp = requests.post(
            f"{BACKEND_URL}/auth/login",
            json={"email": email, "password": password},
            timeout=10,
        )
        if resp.ok:
            token = resp.json().get("access_token")
            if token:
                st.session_state["auth_token"] = token
                st.session_state["auth_email"] = email
                backend_set_token(token)
                _persist_auth(email, token)
                st.session_state["auth_source"] = "login"
                st.success("Signed in successfully.")
                return True
            st.error("Login failed: token missing.")
            return False
        st.error(f"Login failed: {resp.status_code}")
        return False
    except Exception as exc:
        st.error(f"Login error: {exc}")
        return False


def _register_backend(email: str, password: str) -> bool:
    """Create a new backend user account."""
    if not BACKEND_URL:
        st.error("BACKEND_URL is not configured.")
        return False
    try:
        resp = requests.post(
            f"{BACKEND_URL}/auth/register",
            json={"email": email, "password": password},
            timeout=10,
        )
        if resp.status_code == 201:
            st.success("Account created. You can sign in now.")
            return True
        if resp.status_code == 400:
            st.error("Account already exists for that email.")
            return False
        st.error(f"Registration failed: {resp.status_code}")
        return False
    except Exception as exc:
        st.error(f"Registration error: {exc}")
        return False


def _persist_auth(email: str, token: str) -> None:
    """Store authentication details on device to enable automatic sign-in."""
    try:
        with open(AUTH_CACHE_PATH, "w", encoding="utf-8") as auth_file:
            json.dump({"email": email, "token": token}, auth_file)
    except Exception as exc:  # pragma: no cover - local disk writes are best-effort
        st.warning(f"Unable to remember login on this device: {exc}")


def _load_cached_auth() -> None:
    """Load saved authentication details from disk if available."""
    try:
        with open(AUTH_CACHE_PATH, "r", encoding="utf-8") as auth_file:
            data = json.load(auth_file)
        token = data.get("token")
        email = data.get("email")
        if token and email:
            st.session_state["auth_token"] = token
            st.session_state["auth_email"] = email
            st.session_state["auth_source"] = "cache"
            backend_set_token(token)
        else:
            _clear_cached_auth()
    except FileNotFoundError:
        return
    except Exception as exc:  # pragma: no cover - local disk reads are best-effort
        st.warning(f"Unable to load saved login: {exc}")


def _clear_cached_auth() -> None:
    """Remove cached authentication details when signing out."""
    st.session_state.pop("auth_token", None)
    st.session_state.pop("auth_email", None)
    backend_set_token("")
    try:
        if os.path.exists(AUTH_CACHE_PATH):
            os.remove(AUTH_CACHE_PATH)
    except Exception as exc:  # pragma: no cover - local disk writes are best-effort
        st.warning(f"Unable to clear saved login: {exc}")


with st.sidebar:
    st.title("Fitness Brain")
    st.subheader("Account")
    _load_cached_auth()
    if st.session_state.get("auth_source") == "cache":
        st.caption("Signed in with saved credentials for this device.")
    if "auth_token" not in st.session_state:
        auth_mode = st.radio("Select", ["Login", "Register"], horizontal=True, key="auth_mode")
        if auth_mode == "Login":
            login_email = st.text_input("Email", value=DEFAULT_BACKEND_EMAIL, key="login_email")
            login_password = st.text_input(
                "Password", type="password", value=DEFAULT_BACKEND_PASSWORD, key="login_password"
            )
            if st.button("Sign in", key="login_button"):
                _login_to_backend(login_email, login_password)
        else:
            reg_email = st.text_input("Email", value="", key="register_email")
            reg_password = st.text_input("Password", type="password", value="", key="register_password")
            if st.button("Create account", key="register_button"):
                if _register_backend(reg_email, reg_password):
                    _login_to_backend(reg_email, reg_password)
    else:
        st.write(f"Signed in as {st.session_state.get('auth_email', '')}")
        if st.button("Sign out", key="logout_button"):
            _clear_cached_auth()

    if "auth_token" in st.session_state:
        mode = st.radio(
            "Workspace",
            options=[
                "Profile",
                "Talk to the Expert",
                "Planners",
                "Trackers",
                "Kitchen",
                "Scheduler",
            ],
            index=0,
        )
    else:
        st.info("Please sign in to access the app.")
        mode = None

if "auth_token" not in st.session_state:
    st.stop()

selected_schedule_date = st.session_state.get("scheduler_selected_date", date.today())
if mode == "Scheduler":
    selected_schedule_date = st.date_input(
        "Select schedule date",
        value=selected_schedule_date,
        key="scheduler_date_input",
    )
    st.session_state["scheduler_selected_date"] = selected_schedule_date

shared_state = build_shared_state()


def _parse_time_to_minutes(time_str: str | None) -> int:
    if not isinstance(time_str, str):
        return 24 * 60
    time_str = time_str.strip()
    if not time_str:
        return 24 * 60
    for fmt in ("%H:%M", "%I:%M %p"):
        try:
            parsed = datetime.strptime(time_str, fmt)
            return parsed.hour * 60 + parsed.minute
        except ValueError:
            continue
    return 24 * 60


def _minutes_to_time_str(minutes: int) -> str:
    minutes = minutes % (24 * 60)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _shift_time(base_time: str | None, offset_minutes: int, default: str) -> str:
    base_minutes = _parse_time_to_minutes(base_time)
    if base_minutes >= 24 * 60:
        base_minutes = _parse_time_to_minutes(default)
    if base_minutes >= 24 * 60:
        base_minutes = 6 * 60  # 06:00 fallback
    return _minutes_to_time_str(base_minutes + offset_minutes)


def _resolve_named_time(
    label: str,
    wake_time: str | None,
    training_time: str | None,
    default: str,
) -> str:
    lower = label.strip().lower()
    if not lower:
        return default

    mapping = {
        "wake": wake_time,
        "on waking": wake_time,
        "upon waking": wake_time,
        "morning": wake_time,
        "breakfast": _shift_time(wake_time, 60, default),
        "pre-workout": _shift_time(training_time, -60, default),
        "pre workout": _shift_time(training_time, -60, default),
        "post-workout": _shift_time(training_time, 30, default),
        "post workout": _shift_time(training_time, 30, default),
        "lunch": "12:30",
        "dinner": "18:30",
        "snacks": "16:00",
        "with first meal": _shift_time(wake_time, 90, default),
        "with lunch": "13:00",
        "with dinner": "19:30",
        "before bed": "21:30",
    }
    result = mapping.get(lower)
    if result:
        return result
    return default


def _build_day_timeline(plan: Dict[str, Any], shared_state: Dict[str, Any]) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    if not isinstance(plan, dict):
        return events

    preferences = shared_state.get("preferences") or {}
    schedule_prefs = preferences.get("schedule") or {}
    workout_prefs = preferences.get("workout") or {}
    daily_prefs = preferences.get("daily_planner") or {}
    fasted_time = daily_prefs.get("fasted_cardio_time")

    wake_time = schedule_prefs.get("typical_wake_time")
    training_time = workout_prefs.get("preferred_training_time") or "15:00"
    fasted_time = daily_prefs.get("fasted_cardio_time")
    if fasted_time and ":" not in fasted_time:
        fasted_time = _resolve_named_time(fasted_time, wake_time, training_time, "09:00")

    if wake_time:
        events.append({"time": wake_time, "label": "Wake up", "detail": ""})

    if fasted_time:
        events.append(
            {"time": fasted_time, "label": "Fasted cardio", "detail": "Cardio"}
        )

    fasted_notes = plan.get("messages", {}).get("workout") or ""
    workout_block = plan.get("workout", {})
    if workout_block.get("planned"):
        time_str = training_time
        focus = workout_block.get("focus") or "Workout session"
        label = f"{focus}"
        if fasted_notes:
            label = f"{label} ({fasted_notes})"
        events.append({"time": time_str, "label": label, "detail": "Training"})

    nutrition = plan.get("nutrition") or {}
    meals = nutrition.get("meals") if isinstance(nutrition.get("meals"), list) else []
    first_meal_time = None
    for meal in meals:
        time_str = (meal.get("time") or "").strip()
        name = meal.get("name") or "Meal"
        if ":" not in time_str:
            time_str = _resolve_named_time(time_str, wake_time, training_time, "12:00")
        if first_meal_time is None:
            first_meal_time = time_str
        events.append(
            {
                "time": time_str or "12:00",
                "label": f"{name}",
                "detail": "Nutrition",
            }
        )

    supplements_block = plan.get("supplements") or {}
    protocol = supplements_block.get("protocol") or []
    for block in protocol:
        time_label = (block.get("time") or "").strip()
        time_str = time_label or "06:00"
        if ":" not in time_label:
            default_slot = first_meal_time or wake_time or "06:00"
            time_str = _resolve_named_time(time_label, wake_time, training_time, default_slot)
        items = block.get("items") or []
        if not items:
            continue
        item_names = ", ".join(item.get("name", "Supplement") for item in items)
        events.append(
            {
                "time": time_str or "00:00",
                "label": f"{item_names}",
                "detail": "Supplements",
            }
        )

    events = sorted(
        events,
        key=lambda e: _parse_time_to_minutes(e.get("time")),
    )
    return events


def render_daily_planner(selected_date: date):
    plan = get_daily_plan(selected_date)
    timeline = _build_day_timeline(plan, shared_state)
    timeline = _build_day_timeline(plan, shared_state)
    display_date = plan.get("date", selected_date.isoformat())
    weekday = plan.get("weekday", selected_date.strftime("%A").lower())
    messages = plan.get("messages", {})

    st.markdown(f"## Daily Plan for **{display_date}** ({weekday.title()})")
    if timeline:
        st.markdown("**Timeline**")
        for event in timeline:
            detail = f" ({event['detail']})" if event.get("detail") else ""
            st.write(f"- {event['time']} — {event['label']}{detail}")

    planner_info = plan.get("planner")
    if planner_info:
        bits = []
        label = planner_info.get("label")
        if label:
            bits.append(f"Plan: {label}")
        day_role = planner_info.get("day_role")
        if day_role:
            bits.append(f"Role: {day_role}")
        notes = planner_info.get("notes")
        if notes:
            bits.append(f"Notes: {notes}")
        if bits:
            st.info(" | ".join(bits))

    biometrics = plan.get("biometrics")
    with st.expander("Biometrics & Goals", expanded=True):
        if biometrics:
            cols = st.columns(3)
            cols[0].metric("Sex", biometrics.get("sex", "-"))
            cols[1].metric("Age", biometrics.get("age", "-"))
            cols[2].metric("Height (cm)", biometrics.get("height_cm", "-"))

            cols2 = st.columns(3)
            cols2[0].metric("Weight (kg)", biometrics.get("weight_kg", "-"))
            cols2[1].metric("Goal", biometrics.get("goal", "-"))
            cols2[2].metric("Target delta / week", biometrics.get("weekly_change_target", "-"))

            activity = biometrics.get("activity_level")
            if activity:
                st.write(f"**Activity Level:** {activity}")
            notes = biometrics.get("notes")
            if notes:
                st.write(f"**Notes:** {notes}")
        else:
            st.info(messages.get("biometrics", "No biometrics information available."))

    workout = plan.get("workout")
    
    with st.expander("Workout", expanded=True):
        if workout and workout.get("planned"):
            source = workout.get("source")
            if source:
                st.write(f"**Source:** {source}")
            st.write(f"**Focus:** {workout.get('focus', 'Unknown')}")
            exercises = workout.get("exercises") or []
            if exercises:
                for ex in exercises:
                    name = ex.get("name", "Exercise")
                    sets = ex.get("sets", "?")
                    reps = ex.get("reps", "?")
                    duration = ex.get("duration")
                    if duration:
                        st.write(f"- {name}: {duration}")
                    else:
                        st.write(f"- {name}: {sets} x {reps}")
            else:
                st.write("No exercises listed for this workout.")
        else:
            st.info(messages.get("workout", "No workout planned for this day."))

    nutrition = plan.get("nutrition")
    with st.expander("Nutrition", expanded=True):
        if nutrition:
            st.write(f"**Profile:** {nutrition.get('profile_name', '-')}")
            day_type = nutrition.get("day_type_label")
            if day_type:
                st.write(f"**Day Type:** {day_type}")
            plan_label = nutrition.get("plan_label")
            if plan_label:
                st.write(f"**Plan:** {plan_label}")
            role = nutrition.get("role")
            if role:
                st.write(f"**Role:** {role}")

            calories = nutrition.get("calories")
            macros = nutrition.get("macros") or {}
            cols = st.columns(4)
            cols[0].metric("Calories", calories or "-")
            cols[1].metric("Protein (g)", macros.get("protein_g", "-"))
            cols[2].metric("Carbs (g)", macros.get("carbs_g", "-"))
            cols[3].metric("Fat (g)", macros.get("fat_g", "-"))

            meals = nutrition.get("meals", [])
            if meals:
                st.write("### Meals")
                for meal in meals:
                    time = meal.get("time", "")
                    name = meal.get("name", "Meal")
                    title = f"{time} – {name}" if time else name
                    st.write(f"**{title}**")
                    for item in meal.get("items", []):
                        item_name = item.get("name", "Item")
                        extra = ", ".join(
                            f"{k}={v}" for k, v in item.items() if k not in {"name"}
                        )
                        if extra:
                            st.write(f"- {item_name} ({extra})")
                        else:
                            st.write(f"- {item_name}")
            notes = nutrition.get("notes")
            if notes:
                st.write(f"**Notes:** {notes}")
        else:
            st.info(messages.get("nutrition", "No nutrition plan for this day."))

    supplements = plan.get("supplements")
    with st.expander("Supplements", expanded=False):
        if supplements:
            st.write(f"**Template:** {supplements.get('template_name', '-')}")
            day_type = supplements.get("day_type")
            if day_type:
                st.write(f"**Day Type:** {day_type}")
            on_flag = supplements.get("on")
            if on_flag is not None:
                st.write(f"**Active today:** {'Yes' if on_flag else 'No'}")
            protocol = supplements.get("protocol") or []
            if protocol:
                for block in protocol:
                    time = block.get("time", "Time not set")
                    st.write(f"**{time}**")
                    for item in block.get("items", []):
                        name = item.get("name", "Supplement")
                        extra = ", ".join(
                            f"{k}={v}" for k, v in item.items() if k != "name"
                        )
                        if extra:
                            st.write(f"- {name} ({extra})")
                        else:
                            st.write(f"- {name}")
            else:
                st.write("No supplement protocol entries for this day.")
            notes = supplements.get("notes")
            if notes:
                st.write(f"**Notes:** {notes}")
        else:
            st.info(messages.get("supplements", "No supplements protocol for this day."))

    with st.expander("Planner / Notes", expanded=False):
        if planner_info:
            role = planner_info.get("day_role")
            if role:
                st.write(f"**Day Role:** {role}")
            notes = planner_info.get("notes")
            if notes:
                st.write(notes)
            else:
                st.write("No additional planner notes for this day.")
        else:
            st.info(messages.get("planner") or "No planner metadata for this day.")


def _render_expert_conversation_block(
    expert_key: str,
    heading: str,
    chat_key: str,
    button_key: str,
    enable_save: bool = True,
) -> None:
    global shared_state

    st.markdown(f"#### {heading}")
    session_store = st.session_state.setdefault("expert_sessions_blocks", {})
    if expert_key not in session_store:
        init_result = start_expert_session(expert_key)
        messages = init_result[0] if isinstance(init_result, tuple) else init_result
        session_store[expert_key] = {"messages": messages}

    messages = session_store[expert_key]["messages"]

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "")
        if not content:
            continue
        if role == "assistant":
            st.markdown(f"**{expert_key.replace('_', ' ').title()} Expert:** {content}")
        elif role == "user":
            st.markdown(f"**You:** {content}")

    user_text = st.chat_input("Type your message", key=chat_key)
    if user_text:
        new_messages, assistant_text, saved = run_expert_turn(
            expert_key, messages, user_text
        )
        session_store[expert_key]["messages"] = new_messages
        st.rerun()

    if st.button(
        "Save plan (equivalent to :save)", key=button_key, disabled=not enable_save
    ):
        new_messages, assistant_text, saved = run_expert_turn(
            expert_key, messages, ":save"
        )
        session_store[expert_key]["messages"] = new_messages
        if saved:
            try:
                with open(EXPERTS[expert_key]["file"], "r", encoding="utf-8") as f:
                    expert_state = json.load(f)
            except Exception:
                expert_state = None

            if isinstance(expert_state, dict):
                prefs_changed = handle_preferences_from_expert_state(
                    expert_state, shared_state
                )
                if prefs_changed:
                    try:
                        with open(
                            EXPERTS[expert_key]["file"], "w", encoding="utf-8"
                        ) as f:
                            json.dump(expert_state, f, indent=2, ensure_ascii=False)
                    except Exception:
                        pass
                shared_state[expert_key] = expert_state
            st.success("Plan saved for this expert.")
        else:
            st.error("Save failed or no changes to save.")
        st.rerun()


def render_expert_chat():
    st.sidebar.title("Experts")
    expert_key = "council"
    _render_expert_conversation_block(
        expert_key,
        "Strategy Council",
        chat_key=f"chat_{expert_key}",
        button_key=f"save_{expert_key}",
    )


def render_workout_log():
    st.header("Workout Log")

    selected_date: date = st.date_input(
        "Select workout date",
        value=st.session_state.get("workout_log_selected_date", date.today()),
        key="workout_log_date_input",
    )
    st.session_state["workout_log_selected_date"] = selected_date

    planned_sets, daily_plan = build_planned_sets_for_date(selected_date)

    if not planned_sets:
        st.info("No workout scheduled for this date.")
        return

    ensure_workout_state_for_date(selected_date, planned_sets)
    state = st.session_state["workout_state"]

    sets = state["sets"]
    total_sets = len(sets)
    completed_sets_count = sum(1 for s in sets if s["status"] == "completed")

    exercise_order: List[str] = []
    for s in sets:
        if s["exercise"] not in exercise_order:
            exercise_order.append(s["exercise"])

    first_exercise = exercise_order[0] if exercise_order else None

    current_set = None
    if state.get("current_index") is not None:
        current_set = next(
            (s for s in sets if s["index"] == state["current_index"]), None
        )

    if state.get("rest_active") and state.get("rest_end_time"):
        remaining = int(round(state["rest_end_time"] - time.time()))
        if remaining <= 0:
            state["rest_active"] = False
            state["rest_end_time"] = None
            state["rest_exercise"] = None
        else:
            exercise_name = state.get("rest_exercise", "exercise")
            components.html(
                f"""
                <div style="
                    padding: 0.6rem 0.8rem;
                    margin: 0.2rem 0 0.6rem 0;
                    font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                    border-radius: 8px;
                    background-color: rgba(255, 255, 255, 0.06);
                    border: 1px solid rgba(255, 255, 255, 0.12);
                    color: #f5f5f5;
                    font-size: 0.9rem;
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    gap: 0.75rem;
                ">
                  <div>
                    Resting after <strong>{exercise_name}</strong>:
                    <span id="rest-remaining">{remaining}</span> seconds remaining.
                  </div>
                  <div style="display: flex; gap: 0.5rem;">
                    <button id="rest-minus-30" style="
                        padding: 0.2rem 0.5rem;
                        border-radius: 6px;
                        border: 1px solid rgba(255, 255, 255, 0.2);
                        background-color: rgba(255, 255, 255, 0.04);
                        color: #f5f5f5;
                        cursor: pointer;
                        font-size: 0.8rem;
                    ">-30s</button>
                    <button id="rest-plus-30" style="
                        padding: 0.2rem 0.5rem;
                        border-radius: 6px;
                        border: 1px solid rgba(255, 255, 255, 0.2);
                        background-color: rgba(255, 255, 255, 0.16);
                        color: #f5f5f5;
                        cursor: pointer;
                        font-size: 0.8rem;
                    ">+30s</button>
                  </div>
                </div>
                <script>
                (function() {{
                    var remaining = {remaining};
                    var el = document.getElementById("rest-remaining");
                    if (!el) return;

                    function beep() {{
                        try {{
                            var AudioContext = window.AudioContext || window.webkitAudioContext;
                            if (!AudioContext) return;
                            var ctx = new AudioContext();
                            if (ctx.state === 'suspended' && ctx.resume) {{
                                ctx.resume();
                            }}
                            var osc = ctx.createOscillator();
                            var gainNode = ctx.createGain();
                            osc.type = 'square';
                            osc.frequency.value = 1000;
                            osc.connect(gainNode);
                            gainNode.connect(ctx.destination);
                            gainNode.gain.setValueAtTime(0.5, ctx.currentTime);
                            osc.start();
                            gainNode.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.7);
                            osc.stop(ctx.currentTime + 0.7);
                        }} catch (e) {{
                            console.log('Beep failed:', e);
                        }}
                    }}

                    var minusBtn = document.getElementById("rest-minus-30");
                    var plusBtn = document.getElementById("rest-plus-30");

                    if (minusBtn) {{
                        minusBtn.addEventListener("click", function() {{
                            remaining = Math.max(0, remaining - 30);
                            el.textContent = remaining;
                        }});
                    }}

                    if (plusBtn) {{
                        plusBtn.addEventListener("click", function() {{
                            remaining = remaining + 30;
                            el.textContent = remaining;
                        }});
                    }}

                    var timer = setInterval(function() {{
                        remaining -= 1;
                        if (remaining <= 0) {{
                            remaining = 0;
                            clearInterval(timer);
                            beep();
                        }}
                        el.textContent = remaining;
                    }}, 1000);
                }})();
                </script>
                """,
                height=90,
            )

    st.subheader(f"Progress: {completed_sets_count} / {total_sets} sets completed")

    if current_set is not None:
        st.write(
            f"Current set: **{current_set['exercise']} — Set {current_set['set_number']}** "
            f"(planned {current_set['planned_reps']} reps @ RPE {current_set['target_rpe']})"
        )
    else:
        st.success("All sets completed for this date.")

    hide_completed = st.checkbox(
        "Hide completed sets",
        value=False,
        key="hide_completed_sets",
        help="When checked, completed sets are hidden from the list below.",
    )

    st.markdown("---")

    full_log_df = load_workout_log()

    for exercise_name in exercise_order:
        exercise_sets = [s for s in sets if s["exercise"] == exercise_name]
        completed_for_ex = sum(1 for s in exercise_sets if s["status"] == "completed")
        total_for_ex = len(exercise_sets)
        is_current_exercise = any(
            s["index"] == state.get("current_index") for s in exercise_sets
        )

        header_label = f"{exercise_name} ({completed_for_ex}/{total_for_ex} sets completed)"
        if is_current_exercise:
            header_label = "▶ " + header_label

        expanded_default = (exercise_name == first_exercise) or is_current_exercise

        with st.expander(header_label, expanded=expanded_default):
            for set_info in exercise_sets:
                idx = set_info["index"]
                is_current_row = state.get("current_index") == idx
                base_label = (
                    f"Set {set_info['set_number']} — "
                    f"planned {set_info['planned_reps']} reps "
                    f"@ RPE {set_info['target_rpe']}"
                )
                set_label = f"▶ {base_label}" if is_current_row else base_label

                if set_info["status"] == "completed":
                    if hide_completed:
                        continue

                    log_row = set_info.get("log") or {}
                    actual_reps = log_row.get("actual_reps", "")
                    weight = log_row.get("weight", "")
                    rpe = log_row.get("rpe", "")
                    notes = log_row.get("notes", "")
                    st.markdown(
                        f"- ✅ **{set_label}** — actual: {actual_reps} reps @ {weight} kg, RPE {rpe}"
                        + (f" — _{notes}_" if notes else "")
                    )
                    continue

                suggested_weight = None
                suggested_reps = None
                suggested_rpe = None

                if full_log_df is not None and not full_log_df.empty:
                    ex_df_all = full_log_df[full_log_df["exercise"] == exercise_name]

                    if not ex_df_all.empty:
                        day_str = selected_date.isoformat()
                        day_df = ex_df_all[ex_df_all["date"] == day_str]

                        if not day_df.empty:
                            last_row = day_df.iloc[-1]
                        else:
                            last_row = ex_df_all.iloc[-1]

                        suggested_weight = last_row.get("weight")
                        suggested_reps = last_row.get("actual_reps")
                        suggested_rpe = last_row.get("rpe")

                if suggested_weight is None:
                    suggested_weight = 0.0
                if suggested_reps is None:
                    suggested_reps = _planned_reps_to_int(set_info["planned_reps"])
                if suggested_rpe is None:
                    trpe = set_info.get("target_rpe")
                    suggested_rpe = float(trpe) if trpe is not None else 7.0

                try:
                    suggested_weight = float(suggested_weight)
                except (TypeError, ValueError):
                    suggested_weight = 0.0

                try:
                    suggested_reps = int(suggested_reps)
                except (TypeError, ValueError):
                    suggested_reps = 0
                if suggested_reps < 0:
                    suggested_reps = 0

                try:
                    suggested_rpe = float(suggested_rpe)
                except (TypeError, ValueError):
                    suggested_rpe = 7.0
                if suggested_rpe < 0.0:
                    suggested_rpe = 0.0
                if suggested_rpe > 10.0:
                    suggested_rpe = 10.0

                cols = st.columns([3, 1, 1, 1, 1])
                with cols[0]:
                    st.write(set_label)

                base_key = f"{selected_date.isoformat()}_{exercise_name}_set{set_info['set_number']}"
                weight_key = base_key + "_weight"
                reps_key = base_key + "_reps"
                rpe_key = base_key + "_rpe"

                if weight_key not in st.session_state:
                    st.session_state[weight_key] = suggested_weight
                if reps_key not in st.session_state:
                    st.session_state[reps_key] = suggested_reps
                if rpe_key not in st.session_state:
                    st.session_state[rpe_key] = suggested_rpe

                with cols[1]:
                    weight_val = st.number_input(
                        "Weight (kg)",
                        min_value=0.0,
                        step=0.5,
                        key=weight_key,
                    )

                with cols[2]:
                    actual_reps_val = st.number_input(
                        "Reps",
                        min_value=0,
                        step=1,
                        key=reps_key,
                    )

                with cols[3]:
                    actual_rpe_val = st.number_input(
                        "RPE",
                        min_value=0.0,
                        max_value=10.0,
                        step=0.5,
                        key=rpe_key,
                    )

                with cols[4]:
                    log_button = st.button("✓", key=base_key + "_log", help="Log this set")

                notes_key = base_key + "_notes"
                notes_val = st.text_input("Notes (optional)", key=notes_key)

                if log_button:
                    if weight_val <= 0 or actual_reps_val <= 0 or actual_rpe_val <= 0:
                        st.warning("Please enter weight, reps, and RPE before logging this set.")
                    else:
                        row = {
                            "date": selected_date.isoformat(),
                            "exercise": exercise_name,
                            "set_number": set_info["set_number"],
                            "planned_reps": set_info["planned_reps"],
                            "actual_reps": int(actual_reps_val),
                            "weight": float(weight_val),
                            "rpe": float(actual_rpe_val),
                            "notes": notes_val,
                        }
                        append_workout_log_row(row)

                        set_info["status"] = "completed"
                        set_info["log"] = row

                        rest_seconds = int(set_info.get("rest_seconds") or 0)
                        if rest_seconds > 0:
                            state["rest_active"] = True
                            state["rest_end_time"] = time.time() + rest_seconds
                            state["rest_exercise"] = exercise_name
                        else:
                            state["rest_active"] = False
                            state["rest_end_time"] = None
                            state["rest_exercise"] = None

                        state["current_index"] = set_info["index"]
                        update_current_index_after_completion(state)

                        st.rerun()

    st.markdown("---")
    st.subheader("Logged sets for this date")

    if full_log_df is not None and not full_log_df.empty:
        date_str = selected_date.isoformat()
        df_for_date = full_log_df[full_log_df["date"] == date_str]
        if df_for_date.empty:
            st.write("No sets logged yet for this date.")
        else:
            st.dataframe(df_for_date, width="stretch")
    else:
        st.write("No workout log data yet.")


def render_workout_history():
    st.header("Workout History")

    history = load_workout_history()

    if not history or "exercises" not in history or not history["exercises"]:
        st.info(
            "No workout history available yet. Log some sets and run workout_history.py."
        )
        return

    exercises_dict = history["exercises"]
    exercise_names = sorted(exercises_dict.keys())

    selected_exercise = st.selectbox("Select exercise", exercise_names)
    ex = exercises_dict.get(selected_exercise, {}) or {}

    st.subheader(f"Overview: {selected_exercise}")
    overall = ex.get("overall", {}) or {}
    total_sessions = ex.get("total_sessions", 0)
    total_sets = ex.get("total_sets", 0)
    last_session_date = ex.get("last_session_date")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total sessions", total_sessions)
        st.metric("Total sets", total_sets)
    with col2:
        st.metric("Avg weight", _format_metric_value(overall.get("avg_weight")))
        st.metric("Max weight", _format_metric_value(overall.get("max_weight")))
    with col3:
        st.metric("Avg reps", _format_metric_value(overall.get("avg_reps")))
        st.metric("Max reps", _format_metric_value(overall.get("max_reps")))
        st.metric("Avg RPE", _format_metric_value(overall.get("avg_rpe")))

    if last_session_date:
        st.caption(f"Last session: {last_session_date}")

    st.markdown("---")
    st.subheader("Recent sessions")

    recent_sessions = ex.get("recent_sessions", []) or []

    if not recent_sessions:
        st.write("No recent sessions recorded for this exercise.")
    else:
        chart_rows: List[Dict[str, float]] = []
        for sess in recent_sessions:
            date_str = sess.get("date")
            top = sess.get("top_set") or {}
            weight = top.get("weight")
            if weight is None:
                weight = sess.get("max_weight")
            if weight is None:
                weight = sess.get("avg_weight")

            if date_str is None or weight is None:
                continue

            try:
                chart_rows.append({"date": date_str, "top_weight": float(weight)})
            except (TypeError, ValueError):
                continue

        trend_text = "Trend: not enough data."
        if chart_rows:
            chart_rows_sorted = sorted(chart_rows, key=lambda r: r["date"])
            if len(chart_rows_sorted) >= 2:
                first = chart_rows_sorted[0]["top_weight"]
                last = chart_rows_sorted[-1]["top_weight"]
                delta = last - first
                if delta > 2.5:
                    trend_text = (
                        f"Trend: ↑ increasing (approx. +{delta:.1f} kg vs earliest session)."
                    )
                elif delta < -2.5:
                    trend_text = (
                        f"Trend: ↓ decreasing (approx. {delta:.1f} kg vs earliest session)."
                    )
                else:
                    trend_text = "Trend: → relatively stable across recent sessions."

            chart_df = pd.DataFrame(chart_rows_sorted)
            chart_df["date"] = pd.to_datetime(chart_df["date"], errors="coerce")
            chart_df = chart_df.dropna(subset=["date"])
            if not chart_df.empty:
                chart_df = chart_df.set_index("date")
                st.markdown("**Top-set weight over recent sessions**")
                st.line_chart(chart_df["top_weight"])

        st.caption(trend_text)

        df_sessions = pd.DataFrame(recent_sessions)
        for col in list(df_sessions.columns):
            if col.startswith("_"):
                df_sessions = df_sessions.drop(columns=[col])

        preferred_order = [
            "date",
            "sets",
            "avg_weight",
            "min_weight",
            "max_weight",
            "avg_reps",
            "min_reps",
            "max_reps",
            "avg_rpe",
            "min_rpe",
            "max_rpe",
        ]
        cols_in_order = [c for c in preferred_order if c in df_sessions.columns]
        remaining = [
            c for c in df_sessions.columns if c not in cols_in_order and c != "top_set"
        ]
        display_cols = cols_in_order + remaining
        df_sessions = df_sessions[display_cols]

        st.dataframe(df_sessions, width="stretch")

        most_recent = recent_sessions[0]
        top = most_recent.get("top_set") or {}
        if isinstance(top, dict) and any(value is not None for value in top.values()):
            st.markdown("**Most recent top set:**")
            st.write(
                f"- Date: {most_recent.get('date', '—')}\n"
                f"- Weight: {_format_metric_value(top.get('weight'))} kg\n"
                f"- Reps: {_format_metric_value(top.get('reps'))}\n"
                f"- RPE: {_format_metric_value(top.get('rpe'))}"
            )


def render_concierge(shared_state: Dict[str, Any]) -> None:
    st.header("My Profile")
    st.caption("Enter your core details, save, and lock them in. This feeds every expert behind the scenes.")

    biometrics = shared_state.get("biometrics") or {}

    def _default_dob() -> date:
        dob_raw = biometrics.get("dob")
        if isinstance(dob_raw, str):
            try:
                return date.fromisoformat(dob_raw)
            except Exception:
                return date(1990, 1, 1)
        return date(1990, 1, 1)

    def _compute_age(dob_dt: date) -> int:
        try:
            return int((date.today() - dob_dt).days // 365.25)
        except Exception:
            return 0

    with st.form("biometrics_form"):
        name = st.text_input("Name", biometrics.get("name", ""))
        sex_options = ["", "male", "female", "other"]
        sex_val = biometrics.get("sex", "")
        sex_index = sex_options.index(sex_val) if sex_val in sex_options else 0
        sex = st.selectbox("Sex", sex_options, index=sex_index)
        dob = st.date_input(
            "Date of birth",
            value=_default_dob(),
            min_value=date(1900, 1, 1),
            max_value=date.today(),
        )
        height_cm = st.number_input(
            "Height (cm)", min_value=0, max_value=300, value=int(biometrics.get("height_cm", 0) or 0)
        )
        weight_kg = st.number_input(
            "Current weight (kg)",
            min_value=0.0,
            max_value=500.0,
            value=float(biometrics.get("current_weight_kg", 0.0) or 0.0),
            step=0.1,
        )
        bodyfat = st.number_input(
            "Body fat %",
            min_value=0.0,
            max_value=100.0,
            value=float(biometrics.get("bodyfat_pct", 0.0) or 0.0),
            step=0.1,
        )
        locked = st.checkbox("Lock these details", value=bool(biometrics.get("locked", False)))

        if st.form_submit_button("Save / Lock"):
            payload = {
                "name": name,
                "sex": sex,
                "dob": dob.isoformat(),
                "age": _compute_age(dob),
                "height_cm": height_cm,
                "current_weight_kg": weight_kg,
                "bodyfat_pct": bodyfat,
                "locked": locked,
                "last_updated": date.today().isoformat(),
            }
            if save_biometrics(payload):
                st.success("Profile saved.")
                st.rerun()
            else:
                st.error("Save failed. Check backend connection and credentials.")

    st.markdown("---")
    st.subheader("Current Profile")
    if biometrics:
        cols = st.columns(3)
        cols[0].metric("Name", biometrics.get("name", "—"))
        dob_val = biometrics.get("dob")
        dob_text = "—"
        age_text = "—"
        try:
            if isinstance(dob_val, str):
                dob_dt = date.fromisoformat(dob_val)
                dob_text = dob_dt.isoformat()
                age_text = _compute_age(dob_dt)
        except Exception:
            pass
        cols[1].metric("Date of birth", dob_text)
        cols[2].metric("Age", age_text)

        cols = st.columns(3)
        cols[0].metric("Height (cm)", biometrics.get("height_cm", "—"))
        cols[1].metric("Weight (kg)", biometrics.get("current_weight_kg", "—"))
        cols[2].metric("Body fat %", biometrics.get("bodyfat_pct", "—"))

        st.write(f"Locked: {'Yes' if biometrics.get('locked') else 'No'}")
        notes = biometrics.get("notes")
        if notes:
            st.info(notes)
    else:
        st.info("No biometrics saved yet. Use the form above to create your profile.")


def _summarise_domain(shared_state: Dict[str, Any], key: str) -> str:
    data = shared_state.get(key) or {}
    if not data:
        return "No plan saved yet."
    if key == "workout":
        name = data.get("template_name") or "Unnamed template"
        days = data.get("days_per_week")
        return f"{name} · {days or '?'} days/week"
    if key == "nutrition":
        return f"{data.get('profile_name', 'Weekly plan')} · {len(data.get('day_types', {}))} day types"
    if key == "supplements":
        return data.get("template_name", "Weekly stack not saved")
    if key == "recipes":
        recipes = data.get("recipes", [])
        return f"{len(recipes)} recipes saved"
    if key == "pantry":
        items = data.get("items", [])
        return f"{len(items)} pantry items tracked"
    if key == "planner":
        return f"Month: {data.get('month', 'n/a')} · {len((data.get('days') or {}))} days planned"
    if key == "workout_planner":
        return "Schedules workout sessions across the calendar"
    if key == "meal_planner":
        links = data.get("recipe_links") or {}
        return f"{len(links)} day-type meal rotations configured"
    return "Ready when you are."


def render_expert_hub(shared_state: Dict[str, Any]) -> None:
    st.header("Talk to the Expert")
    st.caption("One conversation, all domains considered. The council coordinates behind the scenes.")
    biometrics = shared_state.get("biometrics") or {}
    last_updated = biometrics.get("last_updated")
    if isinstance(last_updated, str):
        try:
            last_dt = date.fromisoformat(last_updated)
            days_since = (date.today() - last_dt).days
            if days_since > 7:
                st.warning(f"It has been {days_since} days since you updated your profile. Consider checking in.")
        except Exception:
            pass
    _render_expert_conversation_block(
        "council",
        "Strategy Council",
        chat_key="chat_council",
        button_key="save_council",
    )


SLOT_MAP: Dict[str, List[str]] = {
    "training": ["breakfast", "lunch", "dinner"],
    "rest": ["breakfast", "lunch", "dinner"],
    "fasted": ["lunch", "dinner"],
    "other": ["breakfast", "lunch", "dinner"],
}


def _collect_recipe_candidates(recipes: Dict[str, Any]) -> Dict[str, List[str]]:
    role_map: Dict[str, List[str]] = {}
    for rid, recipe in recipes.items():
        tags = [str(tag).lower() for tag in (recipe.get("tags") or [])]
        for tag in tags:
            role_map.setdefault(tag, []).append(rid)
    return role_map


def _select_recipe(
    candidates: List[str],
    recipes: Dict[str, Any],
    used: set[str],
    diet_style: str | None,
) -> str | None:
    style = (diet_style or "").lower().strip()
    for rid in candidates:
        if rid in used:
            continue
        recipe = recipes.get(rid)
        if not recipe:
            continue
        tags = [str(tag).lower() for tag in (recipe.get("tags") or [])]
        if style and style in tags:
            return rid
    for rid in candidates:
        if rid not in used:
            return rid
    return None


def _build_recipe_links(
    nutrition_plan: Dict[str, Any],
    recipes: Dict[str, Any],
    preferences: Dict[str, Any],
) -> Dict[str, Dict[str, Dict[str, Any]]]:
    day_types = nutrition_plan.get("day_types") or {}
    if not day_types:
        return {}
    recipe_candidates = _collect_recipe_candidates(recipes)
    diet_style = (preferences.get("global") or {}).get("diet_style")
    links: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for day_type_id, info in day_types.items():
        role = (info.get("role") or "other").lower()
        slots = SLOT_MAP.get(role, SLOT_MAP["other"])
        used_ids: set[str] = set()
        day_links: Dict[str, Dict[str, Any]] = {}
        for slot in slots:
            candidates = recipe_candidates.get(role, []) + recipe_candidates.get("other", [])
            recipe_id = _select_recipe(candidates, recipes, used_ids, diet_style)
            if recipe_id:
                day_links[slot] = {"recipe_id": recipe_id, "servings": 1}
                used_ids.add(recipe_id)
        if day_links:
            links[day_type_id] = day_links
    return links


def render_planners(shared_state: Dict[str, Any]) -> None:
    st.header("Planners")
    st.caption("Shape the reusable building blocks for your program.")

    workout_tab, meal_tab, calendar_tab = st.tabs(
        ["Workout Planner", "Meal Planner", "Monthly Planner"]
    )

    with workout_tab:
        st.subheader("Workout Planner")
        workout_plan = shared_state.get("workout") or {}
        if workout_plan:
            st.write(f"**Template:** {workout_plan.get('template_name', 'Untitled')}")
            st.write(f"**Days per week:** {workout_plan.get('days_per_week', '-')}")
            if workout_plan.get("days"):
                st.write("**Saved days:**")
                for name, info in workout_plan["days"].items():
                    focus = info.get("focus", "n/a")
                    st.write(f"- {name}: {focus}")
        else:
            st.info("No workout template saved yet. Visit the Workout expert in the hub to create one.")
        st.markdown("---")
        confirm_workout_plan = st.checkbox(
            "I'm happy with this schedule; enable save",
            key="workout_planner_confirm",
        )
        _render_expert_conversation_block(
            "workout_planner",
            "Chat with Workout Planner",
            chat_key="chat_workout_planner_tab",
            button_key="save_workout_planner_tab",
            enable_save=confirm_workout_plan,
        )

    with meal_tab:
        st.subheader("Meal Planner")
        nutrition_plan = shared_state.get("nutrition") or {}
        if nutrition_plan:
            st.write(f"**Profile:** {nutrition_plan.get('profile_name', 'Weekly plan')}")
            st.write(f"**Day types:** {len(nutrition_plan.get('day_types', {}))}")
            st.write(f"**Weekly plans:** {len(nutrition_plan.get('weekly_plans', {}))}")
            active = nutrition_plan.get("active_weekly_plan")
            if active:
                st.write(f"**Active weekly rotation:** {active}")
            day_types = nutrition_plan.get("day_types", {})
            if day_types:
                role_groups: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {}
                for day_key, info in day_types.items():
                    role = (info.get("role") or "other").title()
                    role_groups.setdefault(role, []).append((day_key, info))
            st.markdown("**Templates by role**")
            for role, entries in role_groups.items():
                st.write(f"- {role}: {len(entries)} template(s)")
                for key, info in entries:
                    macros = info.get("macros") or {}
                    calories = info.get("calories", "-")
                    st.caption(
                        f"    • {key}: {calories} kcal | "
                        f"P {macros.get('protein_g', '-')}/"
                        f"C {macros.get('carbs_g', '-')}/"
                        f"F {macros.get('fat_g', '-')}"
                    )
            generate_from_recipes = st.button(
                "Populate meals from recipes",
                use_container_width=True,
            )
            if generate_from_recipes:
                recipes = load_recipes()
                if not recipes:
                    st.warning(
                        "You need at least one recipe saved (use the Recipes expert) before Meal Planner can populate meals."
                    )
                else:
                    nutrition_data = load_json(NUTRITION_FILE, nutrition_plan)
                    new_links = _build_recipe_links(
                        nutrition_data, recipes, shared_state.get("preferences") or {}
                    )
                    if not new_links:
                        st.warning(
                            "No matching recipes were found for the current day type roles."
                        )
                    else:
                        nutrition_data["recipe_links"] = new_links
                        save_json(NUTRITION_FILE, nutrition_data)
                        shared_state["nutrition"] = nutrition_data
                        st.success("Meal rotation saved via nutrition.json")
        else:
            st.info("No nutrition plan saved yet. Chat with the Nutrition expert to build one.")
        st.markdown("---")
        confirm_meal_plan = st.checkbox(
            "I'm happy with this meal rotation; enable save",
            key="meal_planner_confirm",
        )
        _render_expert_conversation_block(
            "meal_planner",
            "Chat with Meal Planner",
            chat_key="chat_meal_planner_tab",
            button_key="save_meal_planner_tab",
            enable_save=confirm_meal_plan,
        )

    with calendar_tab:
        st.subheader("Monthly / Combined Planner")
        planner_state = shared_state.get("planner") or {}
        if planner_state:
            st.write(f"**Month:** {planner_state.get('month', 'n/a')}")
            st.write(f"**Label:** {planner_state.get('label', 'n/a')}")
            st.write(f"**Days configured:** {len(planner_state.get('days', {}))}")
        else:
            st.info(
                "No calendar plan saved yet. Use the Planner expert to map workouts, meals, and supplements onto specific dates."
            )
        st.markdown("---")
        confirm_scheduler = st.checkbox(
            "I'm happy with this calendar; enable save",
            key="scheduler_confirm",
        )
        _render_expert_conversation_block(
            "planner",
            "Chat with Scheduler",
            chat_key="chat_scheduler_tab",
            button_key="save_scheduler_tab",
            enable_save=confirm_scheduler,
        )


def render_shopping_list_tools() -> None:
    st.subheader("Shopping List")

    recipes = load_recipes()

    if not recipes:
        st.info(
            "No recipes found in recipes.json.\n\n"
            "Use the Recipes expert to create and save some recipes first."
        )
        return

    label_to_id: Dict[str, str] = {}
    labels: List[str] = []
    for rid, recipe in recipes.items():
        name = recipe.get("name") or rid
        label = f"{name} ({rid})" if name != rid else name
        label_to_id[label] = rid
        labels.append(label)

    labels.sort()

    st.write("Select recipes and servings to build a shopping list.")
    selected_labels = st.multiselect("Recipes to include", options=labels)

    recipe_servings: Dict[str, int] = {}
    if selected_labels:
        st.write("Set the number of servings for each selected recipe:")
        for label in selected_labels:
            rid = label_to_id[label]
            key = f"shopping_servings_{rid}"
            servings = st.number_input(
                f"Servings for {label}",
                min_value=0,
                step=1,
                value=1,
                key=key,
            )
            recipe_servings[rid] = int(servings)

    generate = st.button("Generate shopping list")

    if generate:
        recipe_servings_clean = {rid: n for rid, n in recipe_servings.items() if n > 0}

        if not recipe_servings_clean:
            st.warning("Please select at least one recipe and set servings above zero.")
        else:
            text_list = generate_shopping_list_for_plan(recipe_servings_clean)
            st.subheader("Shopping list")
            st.code(text_list, language="text")

    st.markdown("---")
    st.subheader("Generate from current nutrition plan")
    st.caption(
        "This uses nutrition.json and its 'recipe_links' mapping to figure out which "
        "recipes and servings are planned across your days, then builds a shopping "
        "list automatically."
    )
    generate_from_plan = st.button("Generate from nutrition plan")
    if generate_from_plan:
        text_list_plan = generate_shopping_list_from_nutrition()
        st.subheader("Shopping list from nutrition plan")
        st.code(text_list_plan, language="text")


def render_kitchen(shared_state: Dict[str, Any]) -> None:
    st.header("Kitchen")
    st.caption("Browse recipes, manage pantry staples, and prep your shopping list.")

    recipes_tab, recipe_db_tab, pantry_tab, shopping_tab = st.tabs(
        ["Recipes", "Recipe Database", "Pantry", "Shopping List"]
    )

    with recipes_tab:
        recipes_state = shared_state.get("recipes") or {}
        recipes = recipes_state.get("recipes", [])
        st.subheader("Recipe Library")
        if recipes:
            st.write(f"{len(recipes)} recipes saved.")
            names = [r.get("name") or r.get("id") for r in recipes][:10]
            if names:
                st.write(", ".join(names) + ("..." if len(recipes) > 10 else ""))
        else:
            st.info("No recipes saved yet.")
        st.caption("Use the Recipes expert in the hub to add or edit entries.")

    with recipe_db_tab:
        recipes_state = shared_state.get("recipes") or {}
        recipes = recipes_state.get("recipes", [])
        st.subheader("Recipe Database")
        if not recipes:
            st.info("No recipes saved yet. Chat with the Recipes expert to create one.")
        else:
            id_to_recipe = {r.get("id"): r for r in recipes if r.get("id")}
            labels = [
                f"{(r.get('name') or r.get('id') or 'Recipe')} ({rid})"
                for rid, r in id_to_recipe.items()
            ]
            selected_label = st.selectbox(
                "Select a recipe",
                options=labels,
            )
            selected_id = None
            for rid, r in id_to_recipe.items():
                label = f"{(r.get('name') or r.get('id') or 'Recipe')} ({rid})"
                if label == selected_label:
                    selected_id = rid
                    selected_recipe = r
                    break

            if selected_id:
                st.write(f"**Meal type:** {selected_recipe.get('meal_type', '-')}")
                st.write(f"**Tags:** {', '.join(selected_recipe.get('tags') or []) or '—'}")
                macros = selected_recipe.get("per_serving") or {}
                st.write(
                    f"**Per serving macros:** "
                    f"{macros.get('calories', '-') } kcal, "
                    f"P {macros.get('protein_g', '-')}, "
                    f"C {macros.get('carbs_g', '-')}, "
                    f"F {macros.get('fat_g', '-')}"
                )
                new_name = st.text_input(
                    "Rename recipe",
                    value=selected_recipe.get("name", ""),
                    key=f"rename_{selected_id}",
                )
                if st.button("Save recipe name", key=f"rename_btn_{selected_id}"):
                    if not new_name.strip():
                        st.warning("Please provide a non-empty name.")
                    else:
                        recipes_data = load_json(
                            RECIPES_FILE, {"schema_version": 1, "recipes": []}
                        )
                        updated = False
                        for recipe in recipes_data.get("recipes", []):
                            if recipe.get("id") == selected_id:
                                recipe["name"] = new_name.strip()
                                updated = True
                                break
                        if updated:
                            save_json(RECIPES_FILE, recipes_data)
                            shared_state["recipes"] = recipes_data
                            st.success(
                                "Recipe renamed. Experts and planners will use the new name automatically."
                            )
                        else:
                            st.error("Could not find that recipe in recipes.json.")

    with pantry_tab:
        pantry_state = shared_state.get("pantry") or {}
        items = pantry_state.get("items", [])
        st.subheader("Pantry")
        if items:
            st.write(f"{len(items)} items tracked.")
            low = [item.get("name") for item in items if item.get("status") == "low"]
            if low:
                st.warning(f"Low stock: {', '.join(low)}")
        else:
            st.info("No pantry items tracked yet.")
        st.caption("Talk to the Pantry expert to capture staples and their status.")

    with shopping_tab:
        render_shopping_list_tools()


def render_trackers(shared_state: Dict[str, Any]) -> None:
    st.header("Trackers")
    st.caption("Log what happened and monitor progress.")

    workout_tab, history_tab, biometrics_tab, food_tab = st.tabs(
        ["Workout Tracker", "Workout History", "Biometrics", "Food Logger (beta)"]
    )

    with workout_tab:
        render_workout_log()

    with history_tab:
        render_workout_history()

    with biometrics_tab:
        st.subheader("Biometrics Tracker")
        biometrics = shared_state.get("biometrics") or {}
        if biometrics:
            st.metric("Current weight (kg)", biometrics.get("current_weight_kg", "-"))
            st.metric("Goal", biometrics.get("goal", "-"))
            st.write("**Notes:**", biometrics.get("notes", "—"))
        else:
            st.info("No biometrics on file yet.")
        st.caption("Future versions will allow logging weight/body comp directly.")

    with food_tab:
        st.subheader("Food Logger")
        st.info(
            "Coming soon: tick off meals from today's plan, note substitutions, and sync with your pantry."
        )


def render_scheduler(selected_date: date) -> None:
    st.header("Scheduler")
    st.caption("See the combined plan for a specific day, including workouts, meals, and supplements.")
    render_daily_planner(selected_date)


if mode == "Profile":
    render_concierge(shared_state)
elif mode == "Talk to the Expert":
    render_expert_hub(shared_state)
elif mode == "Planners":
    render_planners(shared_state)
elif mode == "Trackers":
    render_trackers(shared_state)
elif mode == "Kitchen":
    render_kitchen(shared_state)
elif mode == "Scheduler":
    render_scheduler(selected_schedule_date)
