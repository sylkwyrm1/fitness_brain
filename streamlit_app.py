# Streamlit entrypoint for the Fitness Brain app
# Run locally with:
#   streamlit run streamlit_app.py

import time
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st
import streamlit.components.v1 as components

from daily_planner import get_daily_plan
from expert_core import EXPERTS, start_expert_session, run_expert_turn
from workout_log import append_workout_log_row, load_workout_log


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


def build_planned_sets_for_date(selected_date: date) -> List[Dict[str, Any]]:
    """Convert the saved workout plan for a date into per-set rows."""
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
    return planned_rows


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


st.set_page_config(page_title="Fitness Brain - Daily Planner", layout="wide")

selected_date = date.today()
with st.sidebar:
    st.title("Fitness Brain")
    mode = st.radio(
        "Mode", options=["Daily Planner", "Experts", "Workout Log"], index=0
    )
    if mode == "Daily Planner":
        selected_date = st.date_input("Select date", value=date.today())


def render_daily_planner(selected_date: date):
    plan = get_daily_plan(selected_date)
    display_date = plan.get("date", selected_date.isoformat())
    weekday = plan.get("weekday", selected_date.strftime("%A").lower())
    messages = plan.get("messages", {})

    st.markdown(f"## Daily Plan for **{display_date}** ({weekday.title()})")

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


def render_expert_chat():
    st.sidebar.title("Experts")

    # Choose expert
    expert_key = st.sidebar.selectbox(
        "Choose expert",
        options=["biometrics", "workout", "nutrition", "supplements", "planner"],
        format_func=lambda x: x.capitalize(),
    )

    # Session state: one message history per expert
    if "expert_sessions" not in st.session_state:
        st.session_state["expert_sessions"] = {}

    if expert_key not in st.session_state["expert_sessions"]:
        init_result = start_expert_session(expert_key)
        messages = init_result[0] if isinstance(init_result, tuple) else init_result
        st.session_state["expert_sessions"][expert_key] = {"messages": messages}

    session = st.session_state["expert_sessions"][expert_key]
    messages = session["messages"]

    # Chat history
    st.markdown(f"### {expert_key.capitalize()} Expert")

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "")
        if not content:
            continue
        if role == "assistant":
            st.markdown(f"**{expert_key.capitalize()} Expert:** {content}")
        elif role == "user":
            st.markdown(f"**You:** {content}")

    # Chat input
    user_text = st.chat_input("Type your message")

    # Normal message send
    if user_text:
        new_messages, assistant_text, saved = run_expert_turn(
            expert_key,
            messages,
            user_text,
        )
        session["messages"] = new_messages
        st.rerun()

    # Save button (equivalent to :save)
    if st.button("Save plan (equivalent to :save)"):
        new_messages, assistant_text, saved = run_expert_turn(
            expert_key,
            messages,
            ":save",
        )
        session["messages"] = new_messages
        if saved:
            st.success("Plan saved for this expert.")
        else:
            st.error("Save failed or no changes to save.")
        st.rerun()


def render_workout_log():
    st.sidebar.title("Workout Log")
    selected_date = st.sidebar.date_input("Date", value=date.today())
    date_str = selected_date.isoformat()

    st.markdown(f"## Session for {date_str}")

    planned_rows = build_planned_sets_for_date(selected_date)

    full_log_df = load_workout_log()

    def render_logged_sets_table() -> None:
        """Show the historical log table for the current date."""
        if full_log_df.empty:
            st.info("No logged sets yet for this date.")
            return

        date_df = full_log_df[full_log_df["date"] == date_str]
        if date_df.empty:
            st.info("No logged sets yet for this date.")
            return

        entries = date_df.to_dict("records")

        def sort_key(entry: Dict[str, Any]) -> Tuple[str, float]:
            set_val = entry.get("set_number", 0)
            try:
                set_num = float(set_val)
            except (TypeError, ValueError):
                set_num = 0.0
            return (str(entry.get("exercise", "")), set_num)

        entries = sorted(entries, key=sort_key)
        display_rows = [
            {
                "Exercise": e.get("exercise", ""),
                "Set #": e.get("set_number", ""),
                "Planned reps": e.get("planned_reps", ""),
                "Actual reps": e.get("actual_reps", ""),
                "Weight (kg)": e.get("weight", ""),
                "RPE": e.get("rpe", ""),
                "Notes": e.get("notes", ""),
            }
            for e in entries
        ]
        st.table(display_rows)

    if not planned_rows:
        st.info("No planned workout found for this date.")
        st.markdown("---")
        st.subheader("Logged sets for this date")
        render_logged_sets_table()
        return

    state = st.session_state.get("workout_state")
    plan_signature = _planned_signature(planned_rows)
    if (
        state is None
        or state.get("date") != date_str
        or state.get("plan_signature") != plan_signature
    ):
        initialise_workout_state(selected_date, planned_rows)
        state = st.session_state["workout_state"]

    # Rest timer (with live countdown)
    if state.get("rest_active") and state.get("rest_end_time"):
        remaining = int(round(state["rest_end_time"] - time.time()))
        if remaining <= 0:
            st.success("Rest finished - next set is ready.")
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

    sets_state: List[Dict[str, Any]] = state.get("sets", [])
    total_sets = len(sets_state)
    completed_sets = sum(1 for s in sets_state if s["status"] == "completed")
    st.write(f"Progress: {completed_sets} / {total_sets} sets completed")

    current_index = state.get("current_index")
    current_set = next(
        (s for s in sets_state if s["index"] == current_index), None
    )
    if current_set:
        target_text = (
            f" @ RPE {current_set['target_rpe']}"
            if current_set.get("target_rpe") is not None
            else ""
        )
        st.write(
            f"Current set: {current_set['exercise']} - Set {current_set['set_number']} "
            f"(planned {current_set['planned_reps']} reps{target_text})"
        )
    else:
        st.success("All sets completed for this date.")

    # Build exercise grouping
    exercise_order: List[str] = []
    exercise_sets: Dict[str, List[Dict[str, Any]]] = {}
    for set_state in sets_state:
        exercise_name = set_state["exercise"]
        exercise_sets.setdefault(exercise_name, []).append(set_state)
        if exercise_name not in exercise_order:
            exercise_order.append(exercise_name)

    st.markdown("---")
    st.subheader("Session runner")

    date_prefix = date_str.replace("-", "")

    for idx, exercise_name in enumerate(exercise_order):
        sets_for_exercise = exercise_sets.get(exercise_name, [])
        total_for_ex = len(sets_for_exercise)
        completed_for_ex = sum(1 for s in sets_for_exercise if s["status"] == "completed")
        has_current = any(s["index"] == current_index for s in sets_for_exercise)

        header = f"{exercise_name} ({completed_for_ex}/{total_for_ex} sets completed)"
        if has_current:
            header = f"▶ {header}"

        expanded_default = idx == 0 or has_current
        with st.expander(header, expanded=expanded_default):
            for set_state in sets_for_exercise:
                set_number = set_state["set_number"]
                planned_reps = set_state.get("planned_reps", "")
                target_rpe = set_state.get("target_rpe")
                rest_seconds = set_state.get("rest_seconds")
                planned_label = (
                    f"Set {set_number} - planned {planned_reps} reps"
                    + (f" @ RPE {target_rpe}" if target_rpe is not None else "")
                )
                if rest_seconds:
                    planned_label += f" | Rest {rest_seconds}s"

                if set_state["status"] == "completed":
                    log_entry = set_state.get("log") or {}
                    actual_reps = log_entry.get("actual_reps", "")
                    weight = log_entry.get("weight", "")
                    actual_rpe = log_entry.get("rpe", "")
                    notes = log_entry.get("notes", "")
                    summary = (
                        f"[done] {planned_label} - actual: {actual_reps} reps @ "
                        f"{weight} kg, RPE {actual_rpe}"
                    )
                    if notes:
                        summary += f" - notes: {notes}"
                    st.markdown(summary)
                    continue

                idx_current = set_state["index"]
                suggested_weight: Optional[float] = None
                suggested_reps: Optional[int] = None
                suggested_rpe: Optional[float] = None

                previous_session_sets = [
                    s
                    for s in sets_state
                    if s["exercise"] == exercise_name
                    and s["status"] == "completed"
                    and s["index"] < idx_current
                    and s.get("log")
                ]
                if previous_session_sets:
                    previous_session_sets.sort(key=lambda s: s["index"])
                    last_log = previous_session_sets[-1].get("log") or {}
                    suggested_weight = last_log.get("weight")
                    suggested_reps = last_log.get("actual_reps")
                    suggested_rpe = last_log.get("rpe")

                if (
                    (suggested_weight is None or suggested_reps is None or suggested_rpe is None)
                    and not full_log_df.empty
                ):
                    ex_df = full_log_df[full_log_df["exercise"] == exercise_name]
                    if not ex_df.empty:
                        last_row = ex_df.iloc[-1]
                        if suggested_weight is None:
                            suggested_weight = last_row.get("weight")
                        if suggested_reps is None:
                            suggested_reps = last_row.get("actual_reps")
                        if suggested_rpe is None:
                            suggested_rpe = last_row.get("rpe")

                if suggested_weight is None:
                    suggested_weight = 0.0
                if suggested_reps is None:
                    suggested_reps = _planned_reps_to_int(planned_reps)
                if suggested_rpe is None:
                    trpe = set_state.get("target_rpe")
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
                suggested_rpe = max(0.0, min(10.0, suggested_rpe))

                st.markdown(planned_label)
                input_cols = st.columns([1, 1, 1])
                base_key = f"{date_prefix}_{exercise_name}_{set_number}"
                weight_val = input_cols[0].number_input(
                    "Weight (kg)",
                    min_value=0.0,
                    max_value=500.0,
                    value=float(suggested_weight),
                    step=0.5,
                    key=f"weight_{base_key}",
                )
                actual_reps_val = input_cols[1].number_input(
                    "Actual reps",
                    min_value=0,
                    max_value=100,
                    value=int(suggested_reps),
                    step=1,
                    key=f"reps_{base_key}",
                )
                actual_rpe_val = input_cols[2].number_input(
                    "Actual RPE",
                    min_value=0.0,
                    max_value=10.0,
                    value=float(suggested_rpe),
                    step=0.5,
                    key=f"rpe_{base_key}",
                )
                notes_val = st.text_input(
                    "Notes (optional)", value="", key=f"notes_{base_key}"
                )
                log_clicked = st.button(
                    "✓ Log set",
                    key=f"log_{base_key}",
                )

                if log_clicked:
                    if weight_val <= 0 or actual_reps_val <= 0 or actual_rpe_val <= 0:
                        st.warning("Please enter positive weight, reps, and RPE before logging.")
                        continue

                    row = {
                        "date": date_str,
                        "exercise": exercise_name,
                        "set_number": set_number,
                        "planned_reps": planned_reps,
                        "actual_reps": int(actual_reps_val),
                        "weight": float(weight_val),
                        "rpe": float(actual_rpe_val),
                        "notes": notes_val.strip(),
                    }
                    append_workout_log_row(row)

                    set_state["status"] = "completed"
                    set_state["log"] = row

                    rest_seconds_val = rest_seconds or 0
                    if rest_seconds_val > 0:
                        state["rest_active"] = True
                        state["rest_end_time"] = time.time() + rest_seconds_val
                        state["rest_exercise"] = exercise_name
                    else:
                        state["rest_active"] = False
                        state["rest_end_time"] = None
                        state["rest_exercise"] = None

                    state["current_index"] = set_state["index"]
                    move_to_next_pending_set(state, after_index=set_state["index"])
                    st.success(f"Logged {exercise_name} - Set {set_number}.")
                    st.rerun()

    st.markdown("---")
    st.subheader("Logged sets for this date")
    render_logged_sets_table()

if mode == "Daily Planner":
    render_daily_planner(selected_date)
elif mode == "Experts":
    render_expert_chat()
elif mode == "Workout Log":
    render_workout_log()
