from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List

DATA_DIR = Path("data")
LOG_PATH = DATA_DIR / "workout_log.csv"


def load_workout_log() -> List[Dict[str, str]]:
    """
    Load the entire workout log from CSV.

    Returns a list of dicts with keys:
    - date (YYYY-MM-DD)
    - exercise
    - sets
    - reps
    - weight
    - notes
    """
    if not LOG_PATH.exists():
        return []

    with LOG_PATH.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


def append_workout_entries(entries: List[Dict[str, Any]]) -> None:
    """
    Append one or more entries to the workout log.

    Each entry should contain:
    - date (YYYY-MM-DD string)
    - exercise (str)
    - sets (int or str)
    - reps (int or str)
    - weight (float or str)
    - notes (str, optional)
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    fieldnames = ["date", "exercise", "sets", "reps", "weight", "notes"]
    file_exists = LOG_PATH.exists()

    with LOG_PATH.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()

        for e in entries:
            writer.writerow(
                {
                    "date": str(e.get("date", "")),
                    "exercise": str(e.get("exercise", "")),
                    "sets": str(e.get("sets", "")),
                    "reps": str(e.get("reps", "")),
                    "weight": str(e.get("weight", "")),
                    "notes": str(e.get("notes", "")),
                }
            )
