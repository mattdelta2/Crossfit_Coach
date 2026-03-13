"""
generator.py

Weekly workout generator for the Local Workout Agent.

Provides a simple generator that creates three sessions per week:
- 2 strength sessions (compound lifts + accessories)
- 1 mobility / conditioning session

The generator uses:
- Exercise templates defined in this module (editable)
- Progression suggestions from progression.suggest_next_load
- Injury information to avoid exercises that target the affected area

Public API
----------
generate_weekly_workouts(logs, injuries) -> list[Workout]
"""
from __future__ import annotations

from typing import Iterable, List, Optional

from models import Exercise, Injury, LogEntry, Workout
import progression

# Tuning constants
STRENGTH_SESSIONS_PER_WEEK = 2
MOBILITY_SESSIONS_PER_WEEK = 1
DEFAULT_BODYWEIGHT_EXERCISE_WEIGHT = 0.0
ROUND_DECIMALS = 2

# Minimal exercise template library. You can extend this list later.
_EXERCISE_TEMPLATES: List[Exercise] = [
    Exercise(name="Squat", primary_muscle="legs", equipment="barbell",
             default_sets=3, default_reps=5),
    Exercise(name="Deadlift", primary_muscle="back", equipment="barbell",
             default_sets=1, default_reps=5),
    Exercise(name="Bench Press", primary_muscle="chest", equipment="barbell",
             default_sets=3, default_reps=5),
    Exercise(name="Overhead Press", primary_muscle="shoulders",
             equipment="barbell", default_sets=3, default_reps=5),
    Exercise(name="Barbell Row", primary_muscle="back", equipment="barbell",
             default_sets=3, default_reps=6),
    Exercise(name="Pull Up", primary_muscle="back", equipment="bodyweight",
             default_sets=3, default_reps=6),
    Exercise(name="Romanian Deadlift", primary_muscle="hamstrings",
             equipment="barbell", default_sets=3, default_reps=8),
    Exercise(name="Goblet Squat", primary_muscle="legs", equipment="dumbbell",
             default_sets=3, default_reps=8),
    Exercise(name="Face Pull", primary_muscle="rear delts", equipment="cable",
             default_sets=3, default_reps=12),
    Exercise(name="Plank", primary_muscle="core", equipment="bodyweight",
             default_sets=3, default_reps=60),  # reps = seconds for isometrics
    Exercise(name="Farmer Carry", primary_muscle="grip", equipment="dumbbell",
             default_sets=3, default_reps=40),  # reps = meters
    Exercise(name="Mobility Flow", primary_muscle="full body",
             equipment="bodyweight", default_sets=1, default_reps=20),
]


def _normalize_area(text: Optional[str]) -> str:
    """Return a normalized lowercase string for simple matching."""
    if not text:
        return ""
    return text.strip().lower()


def _is_exercise_safe_for_injuries(ex: Exercise,
                                   injuries: Iterable[Injury]) -> bool:
    """
    Return False if any injury's affected_area matches the exercise name or
    primary muscle (simple substring match). Otherwise True.

    This is intentionally conservative: if the affected area is ambiguous,
    the exercise will be excluded.
    """
    name = _normalize_area(ex.name)
    primary = _normalize_area(ex.primary_muscle)
    for inj in injuries:
        if not getattr(inj, "injured", False):
            continue
        area = _normalize_area(getattr(inj, "affected_area", None))
        if not area:
            # If injured but no area specified, be conservative and allow
            # the exercise (user can opt out manually).
            continue
        if area in name or area in primary or name in area or primary in area:
            return False
    return True


def _last_known_weight_for_exercise(logs: Iterable[LogEntry],
                                    exercise_name: str) -> float:
    """
    Return the most recent weight recorded for exercise_name in logs.

    If none found, return DEFAULT_BODYWEIGHT_EXERCISE_WEIGHT.
    """
    last_weight = DEFAULT_BODYWEIGHT_EXERCISE_WEIGHT
    for entry in logs:
        try:
            if getattr(entry, "exercise_name", "").strip().lower() == \
               exercise_name.strip().lower():
                last_weight = float(getattr(entry, "weight_kg", last_weight))
        except Exception:
            continue
    return round(last_weight, ROUND_DECIMALS)


def _select_strength_exercises(injuries: Iterable[Injury],
                               count: int = 4) -> List[Exercise]:
    """
    Select a small set of strength exercises from the template library,
    filtering out exercises that conflict with injuries.

    Selection strategy: prefer compound lifts first, then accessories.
    """
    safe = [ex for ex in _EXERCISE_TEMPLATES
            if _is_exercise_safe_for_injuries(ex, injuries)]
    # Heuristic ordering: barbell compound lifts first
    preferred = sorted(
        safe,
        key=lambda e: (
            0 if e.equipment and "barbell" in e.equipment.lower() else 1,
            0 if e.default_reps <= 6 else 1,
            e.name
        )
    )
    return preferred[:count]


def _select_mobility_exercises(injuries: Iterable[Injury],
                               count: int = 3) -> List[Exercise]:
    """Select mobility/conditioning exercises, avoiding injured areas."""
    safe = [ex for ex in _EXERCISE_TEMPLATES
            if _is_exercise_safe_for_injuries(ex, injuries)]
    mobility = [ex for ex in safe if "mobility" in ex.name.lower()
                or ex.equipment == "bodyweight"]
    if not mobility:
        mobility = safe[:count]
    return mobility[:count]


def _build_strength_workout(name: str,
                            logs: Iterable[LogEntry],
                            injuries: Iterable[Injury]) -> Workout:
    """
    Build a single strength workout.

    For each selected exercise, determine a target weight using progression.
    """
    exercises = _select_strength_exercises(injuries, count=4)
    workout_exs: List[Exercise] = []
    for ex in exercises:
        last_weight = _last_known_weight_for_exercise(logs, ex.name)
        # Ask progression for a suggested next load
        try:
            suggested = progression.suggest_next_load(
                logs=logs, exercise_name=ex.name, current_weight=last_weight
            )
        except Exception:
            suggested = last_weight
        # Create a copy of the template with suggested defaults for sets/reps
        workout_ex = Exercise(
            name=ex.name,
            primary_muscle=ex.primary_muscle,
            equipment=ex.equipment,
            default_sets=ex.default_sets,
            default_reps=ex.default_reps,
        )
        # Attach a lightweight hint in the name for UI (not persisted to CSV)
        # Users can ignore or edit this in the UI.
        workout_ex.name = f"{workout_ex.name} — {suggested:.2f} kg"
        workout_exs.append(workout_ex)
    return Workout(name=name, exercises=workout_exs, notes="Strength session")


def _build_mobility_workout(name: str,
                            logs: Iterable[LogEntry],
                            injuries: Iterable[Injury]) -> Workout:
    """Build a mobility / conditioning workout."""
    exercises = _select_mobility_exercises(injuries, count=3)
    workout_exs: List[Exercise] = []
    for ex in exercises:
        workout_exs.append(ex)
    return Workout(name=name, exercises=workout_exs,
                   notes="Mobility / conditioning")


def generate_weekly_workouts(logs: Iterable[LogEntry],
                             injuries: Optional[Iterable[Injury]] = None
                             ) -> List[Workout]:
    """
    Generate a simple weekly plan (list of Workout objects).

    Parameters
    ----------
    logs
        Iterable of LogEntry objects (history).
    injuries
        Optional iterable of Injury objects. 
        If omitted, treated as no injuries.

    Returns
    -------
    list[Workout]
        A list of Workout objects representing the week's sessions.
    """
    if injuries is None:
        injuries = []

    workouts: List[Workout] = []
    # Create two strength sessions (A and B)
    for i in range(STRENGTH_SESSIONS_PER_WEEK):
        name = f"Strength Session {chr(ord('A') + i)}"
        workouts.append(_build_strength_workout(name=name,
                                                logs=logs,
                                                injuries=injuries))
    # Create one mobility session
    workouts.append(_build_mobility_workout(name="Mobility Session",
                                            logs=logs,
                                            injuries=injuries))
    return workouts
