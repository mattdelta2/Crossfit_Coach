"""
storage_csv.py

CSV storage adapter for the Local Workout Agent.

Provides a minimal, stable interface so other modules can rely on CSV storage
now and swap to SQLite later without changing callers.

Public functions:
- read_logs() -> list[LogEntry]
- append_log(entry: LogEntry) -> None
- read_workouts() -> list[Workout]
- write_workout(workout: Workout) -> None
"""

from __future__ import annotations

import csv
import logging
import os
import threading
from typing import Dict, List

from models import (  # noqa: E402 - models is a local module
    LOG_COLUMNS,
    LogEntry,
    Workout,
    logentry_from_row,
    logentry_to_row,
    workout_from_row,
    workout_to_row,
)

# Storage configuration
STORAGE_DIR = os.environ.get("WORKOUT_STORAGE_DIR", "data")
LOG_CSV = os.path.join(STORAGE_DIR, "logs.csv")
WORKOUTS_CSV = os.path.join(STORAGE_DIR, "workouts.csv")

# Internal lock for safe concurrent appends
_APPEND_LOCK = threading.Lock()

# Ensure storage directory exists
os.makedirs(STORAGE_DIR, exist_ok=True)


def _ensure_file_with_header(path: str, columns: List[str]) -> None:
    """
    Ensure a CSV file exists and has the header row.

    If the file is missing or empty, create it and write the header.
    """
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        try:
            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=columns)
                writer.writeheader()
        except Exception:
            logging.exception("Failed to create CSV file: %s", path)
            raise


def read_logs() -> List[LogEntry]:
    """
    Read all log entries from the logs CSV.

    Returns a list of LogEntry objects. If the file is missing, returns an
    empty list.
    """
    _ensure_file_with_header(LOG_CSV, LOG_COLUMNS)
    entries: List[LogEntry] = []
    try:
        with open(LOG_CSV, "r", newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                try:
                    entries.append(logentry_from_row(row))
                except Exception:
                    logging.exception("Skipping malformed log row: %s", row)
    except FileNotFoundError:
        # Should not happen due to _ensure_file_with_header, but be defensive.
        logging.warning("Log CSV not found: %s", LOG_CSV)
    return entries


def append_log(entry: LogEntry) -> None:
    """
    Append a single LogEntry to the logs CSV.

    This function is safe for concurrent calls within the same process.
    """
    _ensure_file_with_header(LOG_CSV, LOG_COLUMNS)
    row: Dict[str, str] = logentry_to_row(entry)
    with _APPEND_LOCK:
        try:
            with open(LOG_CSV, "a", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=LOG_COLUMNS)
                writer.writerow(row)
        except Exception:
            logging.exception("Failed to append log entry: %s", row)
            raise


# Workout CSV uses a small set of columns; exercises are stored as JSON.
WORKOUT_COLUMNS = ["name", "date", "exercises_json", "notes"]


def read_workouts() -> List[Workout]:
    """
    Read all workouts from the workouts CSV.

    Returns a list of Workout objects. If the file is missing, returns an
    empty list.
    """
    _ensure_file_with_header(WORKOUTS_CSV, WORKOUT_COLUMNS)
    workouts: List[Workout] = []
    try:
        with open(WORKOUTS_CSV, "r", newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                try:
                    workouts.append(workout_from_row(row))
                except Exception:
                    logging.exception(
                        "Skipping malformed workout row: %s", row)
    except FileNotFoundError:
        logging.warning("Workouts CSV not found: %s", WORKOUTS_CSV)
    return workouts


def write_workout(workout: Workout) -> None:
    """
    Append or update a workout in the workouts CSV.

    Current simple behaviour: append a new row. If you later want to update
    by name, replace this with a read-modify-write.
    """
    _ensure_file_with_header(WORKOUTS_CSV, WORKOUT_COLUMNS)
    row: Dict[str, str] = workout_to_row(workout)
    try:
        with open(WORKOUTS_CSV, "a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=WORKOUT_COLUMNS)
            writer.writerow(row)
    except Exception:
        logging.exception("Failed to write workout: %s", row)
        raise
