"""
models.py

Pydantic models and CSV (de)serialization helpers for the Local Workout Agent.

This module defines the core data models used across the project and provides
stable helpers to convert models to/from flat CSV rows. The CSV helpers use a
simple, explicit format so storage_csv.py can remain minimal and replaceable.

Flake8 / style notes
- Keep lines reasonably short.
- All public functions are annotated.
- No unused imports.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# Exported names
__all__ = [
    "Exercise",
    "Workout",
    "LogEntry",
    "Injury",
    "LOG_COLUMNS",
    "logentry_to_row",
    "logentry_from_row",
    "workout_to_row",
    "workout_from_row",
    "example_logentry",
    "iso_today",
]

# CSV column order for log CSV files (one row per exercise performed).
LOG_COLUMNS: List[str] = [
    "date",
    "workout_name",
    "exercise_name",
    "sets",
    "reps",
    "weight_kg",
    "hit_target",
    "injured",
    "affected_area",
    "notes",
]


def iso_today() -> str:
    """Return today's date as an ISO formatted string (YYYY-MM-DD)."""
    return date.today().isoformat()


class Exercise(BaseModel):
    """Represents an exercise template or definition."""
    name: str = Field(..., description="Canonical exercise name")
    primary_muscle: Optional[str] = Field(
        None, description="Primary muscle group (optional)"
    )
    equipment: Optional[str] = Field(None, description="Equipment required")
    default_sets: int = Field(3, description="Default number of sets")
    default_reps: int = Field(5, description="Default number of reps")

    class Config:
        orm_mode = True


class Workout(BaseModel):
    """A workout composed of multiple exercises."""
    name: str = Field(..., description="Workout name")
    date: Optional[str] = Field(
        None, description="Optional scheduled date ISO")
    exercises: List[Exercise] = Field(default_factory=list)
    notes: Optional[str] = Field(None, description="Optional notes")

    class Config:
        orm_mode = True


class Injury(BaseModel):
    """Simple injury record used by the generator/progression logic."""
    injured: bool = Field(False, description="Whether the user is injured")
    affected_area: Optional[str] = Field(
        None, description="Affected body area")

    class Config:
        orm_mode = True


class LogEntry(BaseModel):
    """One performed exercise entry (one CSV row)."""
    date: str = Field(
        ..., description="ISO date string YYYY-MM-DD")
    workout_name: str = Field(
        ..., description="Name of the workout/session")
    exercise_name: str = Field(
        ..., description="Name of the exercise performed")
    sets: int = Field(
        ..., description="Number of sets performed")
    reps: int = Field(
        ..., description="Reps per set (or target reps)")
    weight_kg: float = Field(..., description="Load in kilograms")
    hit_target: bool = Field(
        ..., description="Whether the target was hit (yes/no)")
    injured: bool = Field(
        False, description="Whether user reported an injury")
    affected_area: Optional[str] = Field(
        None, description="Affected area if injured")
    notes: Optional[str] = Field(
        None, description="Freeform notes")

    class Config:
        orm_mode = True


# --- Serialization helpers ------------------------------------------------- #
def _bool_to_csv(value: bool) -> str:
    """Serialize boolean to CSV-friendly string ('1' or '0')."""
    return "1" if value else "0"


def _csv_to_bool(value: str) -> bool:
    """Deserialize CSV boolean string to Python bool."""
    if value is None:
        return False
    val = str(value).strip().lower()
    return val in ("1", "true", "t", "yes", "y")


def _safe_str(value: Optional[Any]) -> str:
    """Convert a value to a CSV-safe string (no newlines)."""
    if value is None:
        return ""
    return str(value).replace("\n", " ").replace("\r", " ").strip()


def logentry_to_row(entry: LogEntry) -> Dict[str, str]:
    """
    Convert a LogEntry to a flat dict suitable for CSV writing.

    The returned dict keys match LOG_COLUMNS exactly.
    """
    return {
        "date": _safe_str(entry.date),
        "workout_name": _safe_str(entry.workout_name),
        "exercise_name": _safe_str(entry.exercise_name),
        "sets": str(entry.sets),
        "reps": str(entry.reps),
        "weight_kg": f"{entry.weight_kg:.2f}",
        "hit_target": _bool_to_csv(entry.hit_target),
        "injured": _bool_to_csv(entry.injured),
        "affected_area": _safe_str(entry.affected_area),
        "notes": _safe_str(entry.notes),
    }


def logentry_from_row(row: Dict[str, str]) -> LogEntry:
    """
    Convert a CSV row (mapping) into a LogEntry.

    Accepts dict-like objects where missing keys
      fall back to sensible defaults.
    """
    # Defensive access with defaults
    date_str = row.get("date", iso_today())
    workout_name = row.get("workout_name", "")
    exercise_name = row.get("exercise_name", "")
    sets = int(row.get("sets", "0") or 0)
    reps = int(row.get("reps", "0") or 0)
    try:
        weight_kg = float(row.get("weight_kg", "0") or 0.0)
    except ValueError:
        weight_kg = 0.0
    hit_target = _csv_to_bool(row.get("hit_target", "0"))
    injured = _csv_to_bool(row.get("injured", "0"))
    affected_area = row.get("affected_area") or None
    notes = row.get("notes") or None

    return LogEntry(
        date=date_str,
        workout_name=workout_name,
        exercise_name=exercise_name,
        sets=sets,
        reps=reps,
        weight_kg=weight_kg,
        hit_target=hit_target,
        injured=injured,
        affected_area=affected_area,
        notes=notes,
    )


# Workout CSV helpers: store exercises as a JSON string in a single column.
WORKOUT_COLUMNS: List[str] = ["name", "date", "exercises_json", "notes"]


def workout_to_row(workout: Workout) -> Dict[str, str]:
    """
    Convert a Workout to a flat dict for CSV storage.

    Exercises are serialized as a JSON list of dicts.
    """
    exercises_json = json.dumps([ex.dict() for ex in workout.exercises])
    return {
        "name": _safe_str(workout.name),
        "date": _safe_str(workout.date),
        "exercises_json": exercises_json,
        "notes": _safe_str(workout.notes),
    }


def workout_from_row(row: Dict[str, str]) -> Workout:
    """
    Convert a CSV row into a Workout.

    Expects 'exercises_json' to be a JSON-encoded list of exercise dicts.
    """
    name = row.get("name", "")
    date_str = row.get("date") or None
    notes = row.get("notes") or None
    exercises_json = row.get("exercises_json", "[]")
    try:
        exercises_data = json.loads(exercises_json)
    except Exception:
        exercises_data = []
    exercises: List[Exercise] = []
    for item in exercises_data:
        try:
            exercises.append(Exercise.parse_obj(item))
        except Exception:
            # Skip malformed exercise entries
            continue

    return Workout(name=name, date=date_str, exercises=exercises, notes=notes)


# --- Example fixtures ----------------------------------------------------- #
def example_logentry() -> LogEntry:
    """Return a sample LogEntry useful for tests and docs."""
    return LogEntry(
        date=iso_today(),
        workout_name="Upper A",
        exercise_name="Bench Press",
        sets=3,
        reps=5,
        weight_kg=80.0,
        hit_target=True,
        injured=False,
        affected_area=None,
        notes="Felt strong; paused at bottom on last rep.",
    )
