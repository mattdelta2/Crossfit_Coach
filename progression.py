"""
progression.py

Simple progression logic for the Local Workout Agent.

Rules implemented:
- Default increment: +2.5 kg after N consecutive successful sessions
  (hit_target == True) for the same exercise.
- If a recent log for the same exercise reports an injury (injured == True),
  the suggestion will be conservative: reduce suggested load by a small
  percentage (default 10%) or keep the current weight.
- Public API:
    suggest_next_load(logs, exercise_name, current_weight) -> float

The implementation is intentionally simple and deterministic so it is easy to
test and extend. All public functions are annotated and documented.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, List, Optional

# Progression tuning constants
INCREMENT_KG: float = 2.5
REQUIRED_SUCCESSIVE: int = 2
RECENT_WINDOW: int = 6  # how many recent entries to inspect
INJURY_LOOKBACK: int = 6  # how many recent entries to check for injury
INJURY_REDUCTION_FACTOR: float = 0.90  # reduce to 90% of suggested if injured
ROUND_DECIMALS: int = 2


def _parse_date_safe(date_str: Optional[str]) -> Optional[datetime]:
    """Parse an ISO date string to datetime or return None on failure."""
    if not date_str:
        return None
    try:
        # Accept date or datetime ISO formats
        return datetime.fromisoformat(date_str)
    except Exception:
        return None


def _filter_exercise_logs(logs: Iterable, exercise_name: str) -> List:
    """
    Return logs that match the exercise_name (case-insensitive).

    The function does not assume a specific LogEntry type; it expects objects
    with attributes: exercise_name, date, hit_target, injured, affected_area.
    """
    name_lower = exercise_name.strip().lower()
    matched = []
    for entry in logs:
        try:
            ename = getattr(entry, "exercise_name", "")
        except Exception:
            ename = ""
        if not ename:
            continue
        if ename.strip().lower() == name_lower:
            matched.append(entry)
    # Sort by date ascending where possible, otherwise keep original order
    try:
        matched.sort(key=lambda e: _parse_date_safe(getattr(e, "date", None))
                     or datetime.min)
    except Exception:
        pass
    return matched


def _count_recent_consecutive_successes(entries: List) -> int:
    """
    Count how many consecutive recent entries (from newest backwards)
    have hit_target == True.
    """
    count = 0
    for entry in reversed(entries[-RECENT_WINDOW:]):
        hit = getattr(entry, "hit_target", False)
        if hit:
            count += 1
        else:
            break
    return count


def _recent_injury_for_exercise(entries: List) -> bool:
    """
    Return True if any of the most recent entries (within INJURY_LOOKBACK)
    report injured == True for that exercise.
    """
    for entry in entries[-INJURY_LOOKBACK:]:
        if getattr(entry, "injured", False):
            return True
    return False


def suggest_next_load(logs: Iterable,
                      exercise_name: str,
                      current_weight: float) -> float:
    """
    Suggest the next load (kg) for a given exercise.

    Parameters
    ----------
    logs
        Iterable of LogEntry-like objects (must have exercise_name, date,
        hit_target, injured attributes).
    exercise_name
        Name of the exercise to compute progression for.
    current_weight
        The weight used in the most recent session (kg). If 0.0, the function
        will return 0.0.

    Returns
    -------
    float
        Suggested next load in kilograms (rounded to two decimals).
    """
    if current_weight <= 0.0:
        # Nothing to progress from
        return round(max(0.0, float(current_weight)), ROUND_DECIMALS)

    entries = _filter_exercise_logs(logs, exercise_name)
    if not entries:
        # No history for this exercise; keep current weight
        return round(current_weight, ROUND_DECIMALS)

    consecutive = _count_recent_consecutive_successes(entries)
    suggested = float(current_weight)

    if consecutive >= REQUIRED_SUCCESSIVE:
        suggested = current_weight + INCREMENT_KG

    # If there is a recent injury for this exercise, be conservative
    if _recent_injury_for_exercise(entries):
        # Reduce the suggested load relative to current weight (not below 0)
        conservative = max(0.0, current_weight * INJURY_REDUCTION_FACTOR)
        # If we had planned to increase, cap it to the conservative value
        # (i.e., do not increase when injured). If conservative is lower than
        # current, use conservative; otherwise keep current.
        if conservative < suggested:
            suggested = conservative
        else:
            suggested = min(suggested, conservative)

    # Final safety clamp: do not suggest negative weights
    suggested = max(0.0, suggested)
    return round(suggested, ROUND_DECIMALS)


# Optional helper for richer output (useful for CLI or tests)
def suggest_next_load_with_reason(logs: Iterable,
                                  exercise_name: str,
                                  current_weight: float) -> dict:
    """
    Return a dict with suggested load and a short reason string.

    This helper is not used by app.py but is useful for debugging and tests.
    """
    entries = _filter_exercise_logs(logs, exercise_name)
    if not entries:
        return {
            "exercise": exercise_name,
            "current_weight_kg": round(current_weight, ROUND_DECIMALS),
            "suggested_next_load_kg": round(current_weight, ROUND_DECIMALS),
            "reason": "no history; keep current weight",
        }

    consecutive = _count_recent_consecutive_successes(entries)
    injured = _recent_injury_for_exercise(entries)
    suggested = suggest_next_load(logs, exercise_name, current_weight)

    if injured:
        reason = "recent injury detected; being conservative"
    elif consecutive >= REQUIRED_SUCCESSIVE:
        reason = (f"{consecutive} consecutive successful sessions; "
                  f"incremented by {INCREMENT_KG} kg")
    else:
        reason = "insufficient consecutive successes; keep current weight"

    return {
        "exercise": exercise_name,
        "current_weight_kg": round(current_weight, ROUND_DECIMALS),
        "suggested_next_load_kg": suggested,
        "consecutive_successes": consecutive,
        "recent_injury": injured,
        "reason": reason,
    }
