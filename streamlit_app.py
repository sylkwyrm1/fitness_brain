# Streamlit entrypoint for the Fitness Brain app
# Run locally with:
#   streamlit run streamlit_app.py

import streamlit as st
from datetime import date
from typing import List

from daily_planner import get_daily_plan
from expert_core import EXPERTS, start_expert_session, run_expert_turn
from workout_log import load_workout_log, append_workout_entries


st.set_page_config(page_title="Fitness Brain – Daily Planner", layout="wide")

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

    # Try to fetch the planned workout for this date using the existing planner logic
    try:
        plan = get_daily_plan(selected_date)
        workout_info = plan.get("workout") or {}
        planned_set = workout_info.get("exercises") or []
    except Exception:
        planned_set = []

    st.markdown(f"## Workout log for {date_str}")

    exercise_suggestions: List[str] = []
    if planned_set:
        st.subheader("Planned workout")
        for ex in planned_set:
            name = ex.get("name", "Exercise")
            sets = ex.get("sets", "?")
            reps = ex.get("reps", "?")
            st.write(f"- {name} ({sets} x {reps})")
            if name:
                exercise_suggestions.append(name)
    else:
        st.info("No planned workout found for this date.")

    st.subheader("Log performed sets")

    form_key = f"workout_log_form_{date_str}"
    with st.form(key=form_key):
        exercise = st.selectbox(
            "Exercise (from plan)",
            options=["(type custom)"] + exercise_suggestions,
            index=0,
        )
        custom_exercise = st.text_input("Or custom exercise name", "")

        sets = st.number_input("Sets", min_value=1, max_value=20, value=3, step=1)
        reps = st.number_input("Reps per set", min_value=1, max_value=50, value=10, step=1)
        weight = st.number_input("Weight (kg)", min_value=0.0, max_value=500.0, value=0.0, step=0.5)
        notes = st.text_area("Notes", "")

        submitted = st.form_submit_button("Add to log")

    if submitted:
        exercise_name = custom_exercise.strip() or exercise
        if not exercise_name or exercise_name == "(type custom)":
            st.error("Please provide an exercise name (select from plan or type a custom one).")
        else:
            entry = {
                "date": date_str,
                "exercise": exercise_name,
                "sets": int(sets),
                "reps": int(reps),
                "weight": float(weight),
                "notes": notes.strip(),
            }
            append_workout_entries([entry])
            st.success("Entry added to workout log.")
            st.rerun()

    st.subheader("Logged sets for this date")

    all_entries = load_workout_log()
    entries_for_date = [e for e in all_entries if e.get("date") == date_str]

    if entries_for_date:
        entries_for_date = sorted(
            entries_for_date,
            key=lambda e: (e.get("exercise", ""), e.get("sets", "")),
        )
        st.table(entries_for_date)
    else:
        st.info("No logged sets yet for this date.")


if mode == "Daily Planner":
    render_daily_planner(selected_date)
elif mode == "Experts":
    render_expert_chat()
elif mode == "Workout Log":
    render_workout_log()
