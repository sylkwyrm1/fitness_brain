from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import pandas as pd

from workout_log import load_workout_log

LOG_PATH = Path("data/raw/workout_log.csv")
HISTORY_PATH = Path("data/processed/workout_history.json")
RECENT_SESSIONS_LIMIT = 5


def _safe_mean(series: pd.Series):
    series = series.dropna()
    if series.empty:
        return None
    val = series.mean()
    if pd.isna(val):
        return None
    return float(val)


def _safe_max(series: pd.Series):
    series = series.dropna()
    if series.empty:
        return None
    val = series.max()
    if pd.isna(val):
        return None
    return float(val)


def _to_int_or_none(val):
    if pd.isna(val):
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _summarise_exercise(ex_df: pd.DataFrame) -> Dict[str, Any]:
    if "date" not in ex_df.columns:
        return {
            "total_sessions": 0,
            "total_sets": 0,
            "last_session_date": None,
            "overall": {
                "avg_weight": None,
                "avg_reps": None,
                "avg_rpe": None,
                "max_weight": None,
                "max_reps": None,
            },
            "recent_sessions": [],
        }

    ex_df = ex_df.copy()
    ex_df["weight"] = pd.to_numeric(ex_df.get("weight"), errors="coerce")
    ex_df["actual_reps"] = pd.to_numeric(ex_df.get("actual_reps"), errors="coerce")
    ex_df["rpe"] = pd.to_numeric(ex_df.get("rpe"), errors="coerce")

    ex_df = ex_df.dropna(subset=["date"])
    if ex_df.empty:
        return {
            "total_sessions": 0,
            "total_sets": 0,
            "last_session_date": None,
            "overall": {
                "avg_weight": None,
                "avg_reps": None,
                "avg_rpe": None,
                "max_weight": None,
                "max_reps": None,
            },
            "recent_sessions": [],
        }

    ex_df["date_dt"] = pd.to_datetime(ex_df["date"], errors="coerce")
    ex_df = ex_df.dropna(subset=["date_dt"])
    if ex_df.empty:
        return {
            "total_sessions": 0,
            "total_sets": 0,
            "last_session_date": None,
            "overall": {
                "avg_weight": None,
                "avg_reps": None,
                "avg_rpe": None,
                "max_weight": None,
                "max_reps": None,
            },
            "recent_sessions": [],
        }

    total_sets = len(ex_df)
    total_sessions = ex_df["date"].nunique()
    last_session_dt = ex_df["date_dt"].max()
    last_session_date = last_session_dt.date().isoformat()

    overall_avg_weight = _safe_mean(ex_df["weight"])
    overall_avg_reps = _safe_mean(ex_df["actual_reps"])
    overall_avg_rpe = _safe_mean(ex_df["rpe"])
    overall_max_weight = _safe_max(ex_df["weight"])
    overall_max_reps_val = _safe_max(ex_df["actual_reps"])
    overall_max_reps = _to_int_or_none(overall_max_reps_val)

    overall = {
        "avg_weight": overall_avg_weight,
        "avg_reps": overall_avg_reps,
        "avg_rpe": overall_avg_rpe,
        "max_weight": overall_max_weight,
        "max_reps": overall_max_reps,
    }

    session_rows = []
    for date_str, day_df in ex_df.groupby("date"):
        day_df = day_df.copy()
        day_df["weight"] = pd.to_numeric(day_df.get("weight"), errors="coerce")
        day_df["actual_reps"] = pd.to_numeric(day_df.get("actual_reps"), errors="coerce")
        day_df["rpe"] = pd.to_numeric(day_df.get("rpe"), errors="coerce")

        sets_count = len(day_df)
        avg_weight = _safe_mean(day_df["weight"])
        min_weight = _safe_max(-day_df["weight"]) if not day_df["weight"].dropna().empty else None
        if min_weight is not None:
            min_weight = -min_weight
        max_weight = _safe_max(day_df["weight"])

        avg_reps = _safe_mean(day_df["actual_reps"])
        reps_series = day_df["actual_reps"].dropna()
        if reps_series.empty:
            min_reps = None
            max_reps = None
        else:
            min_reps = _to_int_or_none(reps_series.min())
            max_reps = _to_int_or_none(reps_series.max())

        avg_rpe = _safe_mean(day_df["rpe"])
        rpe_series = day_df["rpe"].dropna()
        if rpe_series.empty:
            min_rpe = None
            max_rpe = None
        else:
            min_rpe = float(rpe_series.min())
            max_rpe = float(rpe_series.max())

        top_set_weight = None
        top_set_reps = None
        top_set_rpe = None
        if not day_df["weight"].dropna().empty:
            max_w = day_df["weight"].max()
            top_rows = day_df[day_df["weight"] == max_w]
            top_row = top_rows.iloc[-1]
            top_set_weight = float(top_row.get("weight")) if not pd.isna(top_row.get("weight")) else None
            top_set_reps = _to_int_or_none(top_row.get("actual_reps"))
            try:
                rpe_val = float(top_row.get("rpe"))
                top_set_rpe = rpe_val if not pd.isna(rpe_val) else None
            except (TypeError, ValueError):
                top_set_rpe = None

        session_rows.append(
            {
                "date": date_str,
                "sets": sets_count,
                "avg_weight": avg_weight,
                "min_weight": min_weight,
                "max_weight": max_weight,
                "avg_reps": avg_reps,
                "min_reps": min_reps,
                "max_reps": max_reps,
                "avg_rpe": avg_rpe,
                "min_rpe": min_rpe,
                "max_rpe": max_rpe,
                "top_set": {
                    "weight": top_set_weight,
                    "reps": top_set_reps,
                    "rpe": top_set_rpe,
                },
            }
        )

    for s in session_rows:
        s["_date_dt"] = pd.to_datetime(s["date"], errors="coerce")
    session_rows = [s for s in session_rows if s["_date_dt"] is not None]
    session_rows.sort(key=lambda x: x["_date_dt"], reverse=True)
    session_rows = session_rows[:RECENT_SESSIONS_LIMIT]
    for s in session_rows:
        s.pop("_date_dt", None)

    return {
        "total_sessions": int(total_sessions),
        "total_sets": int(total_sets),
        "last_session_date": last_session_date,
        "overall": overall,
        "recent_sessions": session_rows,
    }


def summarise_workout_history(log_df: pd.DataFrame) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "summary_generated_at": datetime.now(timezone.utc).isoformat(),
        "exercises": {},
    }

    if log_df is None or log_df.empty:
        return summary

    if "exercise" not in log_df.columns or "date" not in log_df.columns:
        return summary

    df = log_df.copy()
    df = df.dropna(subset=["exercise", "date"])
    if df.empty:
        return summary

    exercises: Dict[str, Any] = {}
    for exercise_name, ex_df in df.groupby("exercise"):
        exercises[str(exercise_name)] = _summarise_exercise(ex_df)

    summary["exercises"] = exercises
    return summary


def main() -> None:
    log_df = load_workout_log()
    history = summarise_workout_history(log_df)

    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY_PATH.open("w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)

    print(
        f"Wrote workout history for {len(history.get('exercises', {}))} exercises "
        f"to {HISTORY_PATH}"
    )


if __name__ == "__main__":
    main()
