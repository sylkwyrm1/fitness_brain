from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

DATA_DIR = Path("data") / "raw"
LOG_PATH = DATA_DIR / "workout_log.csv"
COLUMNS = ["date", "exercise", "set_number", "planned_reps", "actual_reps", "weight", "rpe", "notes"]


def load_workout_log() -> pd.DataFrame:
    """
    Load the workout log as a pandas DataFrame with the expected columns.
    """
    if not LOG_PATH.exists():
        return pd.DataFrame(columns=COLUMNS)

    df = pd.read_csv(LOG_PATH)
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[COLUMNS]


def append_workout_log_row(row: Dict[str, Any]) -> None:
    """
    Append a single row to the workout log CSV.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df = load_workout_log()
    normalized = {col: row.get(col, "") for col in COLUMNS}
    new_df = pd.DataFrame([normalized])
    if df.empty:
        combined = new_df
    else:
        combined = pd.concat([df, new_df], ignore_index=True)
    combined.to_csv(LOG_PATH, index=False)


# Backwards compatibility helpers (if older code still imports them)
def append_workout_entries(entries: List[Dict[str, Any]]) -> None:
    for entry in entries:
        append_workout_log_row(entry)
