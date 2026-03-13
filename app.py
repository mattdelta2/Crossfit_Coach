"""
app.py

FastAPI web GUI entrypoint for the local workout agent.

Expected companion modules:
- models.py: Workout, Exercise, LogEntry, Injury
- storage_csv.py: read_logs, append_log, read_workouts, write_workout
- progression.py: suggest_next_load
- generator.py: generate_weekly_workouts
- discord_notify.py: post_webhook
"""

from typing import List, Optional

import logging
import os

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# Try to import project modules. If missing, keep placeholders so the
# app can start during incremental development.
try:
    from models import Workout, Exercise, LogEntry, Injury  # noqa: W0611
    import storage_csv
    import progression
    import generator
    import discord_notify
except Exception as exc:  # pragma: no cover - import-time fallback
    logging.warning('Project modules not available: %s', exc)
    Workout = Exercise = LogEntry = Injury = None  # type: ignore
    storage_csv = None  # type: ignore
    progression = None  # type: ignore
    generator = None  # type: ignore
    discord_notify = None  # type: ignore

app = FastAPI(title='Local Workout Agent', version='0.1')
templates = Jinja2Templates(directory='ui_templates')

if os.path.isdir('ui_templates/static'):
    app.mount('/static', StaticFiles(directory='ui_templates/static'),
              name='static')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['http://localhost', 'http://localhost:8000',
                   'http://127.0.0.1:8000'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)


class LogSessionPayload(BaseModel):
    """Pydantic model for logging a session via API."""
    date: str
    workout_name: str
    exercise_name: str
    sets: int
    reps: int
    weight_kg: float
    hit_target: bool
    injured: bool = False
    affected_area: Optional[str] = None
    notes: Optional[str] = None
    post_to_discord: bool = False


def ensure_storage_available() -> None:
    """Raise HTTPException if required modules are not implemented."""
    if storage_csv is None:
        raise HTTPException(
            status_code=500,
            detail='Storage module not implemented. Implement storage_csv.py.'
        )
    if progression is None:
        raise HTTPException(
            status_code=500,
            detail=(
                'Progression module not implemented. '
                'Implement progression.py.'
            )
        )
    if generator is None:
        raise HTTPException(
            status_code=500,
            detail='Generator module not implemented. Implement generator.py.'
        )


@app.get('/', response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Home page: show latest workouts and logs."""
    logs: List = []
    workouts: List = []
    try:
        if storage_csv:
            logs = storage_csv.read_logs()
            workouts = storage_csv.read_workouts()
    except Exception:
        logging.exception('Failed to read logs or workouts')
    return templates.TemplateResponse(
        'index.html', {'request': request, 'logs': logs, 'workouts': workouts}
    )


@app.get('/workouts', response_class=HTMLResponse)
async def view_workouts(request: Request) -> HTMLResponse:
    """Page to view saved or generated workouts."""
    try:
        workouts = storage_csv.read_workouts() if storage_csv else []
    except Exception:
        logging.exception('Failed to read workouts')
        workouts = []
    return templates.TemplateResponse(
        'workouts.html', {'request': request, 'workouts': workouts}
    )


@app.get('/logs', response_class=HTMLResponse)
async def view_logs(request: Request) -> HTMLResponse:
    """Page to view session logs."""
    try:
        logs = storage_csv.read_logs() if storage_csv else []
    except Exception:
        logging.exception('Failed to read logs')
        logs = []
    return templates.TemplateResponse('logs.html',
                                      {'request': request, 'logs': logs})


@app.get('/generate', response_class=HTMLResponse)
async def generate_page(request: Request) -> HTMLResponse:
    """Trigger generation of weekly workouts."""
    ensure_storage_available()
    try:
        logs = storage_csv.read_logs()
        injuries = [entry for entry in logs if getattr(
            entry, 'injured', False)]
        weekly = generator.generate_weekly_workouts(
            logs=logs, injuries=injuries)
    except Exception:
        logging.exception('Failed to generate workouts')
        weekly = []
    return templates.TemplateResponse('generate.html',
                                      {'request': request, 'weekly': weekly})


@app.post('/api/log_session', response_class=JSONResponse)
async def api_log_session(payload: LogSessionPayload) -> JSONResponse:
    """
    Log a session, suggest next load, and optionally post to Discord.
    """
    ensure_storage_available()

    try:
        entry = LogEntry(
            date=payload.date,
            workout_name=payload.workout_name,
            exercise_name=payload.exercise_name,
            sets=payload.sets,
            reps=payload.reps,
            weight_kg=payload.weight_kg,
            hit_target=payload.hit_target,
            injured=payload.injured,
            affected_area=payload.affected_area or '',
            notes=payload.notes or '',
        )
    except Exception:
        logging.exception('Failed to construct LogEntry')
        raise HTTPException(
            status_code=500,
            detail='LogEntry model mismatch. Check models.py signature.'
        )

    try:
        storage_csv.append_log(entry)
    except Exception:
        logging.exception('Failed to append log')
        raise HTTPException(
            status_code=500,
            detail='Failed to save log. Check storage_csv.py implementation.'
        )

    try:
        logs = storage_csv.read_logs()
        suggested = progression.suggest_next_load(
            logs=logs,
            exercise_name=payload.exercise_name,
            current_weight=payload.weight_kg
        )
    except Exception:
        logging.exception('Progression suggestion failed')
        suggested = payload.weight_kg

    discord_result = False
    if payload.post_to_discord:
        webhook_url = os.environ.get('DISCORD_WEBHOOK_URL')
        if not webhook_url:
            logging.warning(
                'DISCORD_WEBHOOK_URL not set; skipping Discord post')
        else:
            try:
                message = (
                    f'Workout logged: {payload.workout_name}\n'
                    f'{payload.exercise_name}: {payload.sets}x{payload.reps} '
                    f'@ {payload.weight_kg} kg\n'
                    f'Hit target: {"Yes" if payload.hit_target else "No"}\n'
                    f'Suggested next load: {suggested} kg'
                )
                discord_result = discord_notify.post_webhook(
                    message=message, webhook_url=webhook_url
                )
            except Exception:
                logging.exception('Discord post failed')
                discord_result = False

    return JSONResponse({
        'status': 'ok',
        'suggested_next_load_kg': suggested,
        'discord_posted': discord_result
    })


@app.get('/api/suggest_next/{exercise_name}', response_class=JSONResponse)
async def api_suggest_next(exercise_name: str,
                           current_weight: float = 0.0) -> JSONResponse:
    """Return a suggested next load for an exercise."""
    ensure_storage_available()
    try:
        logs = storage_csv.read_logs()
        suggested = progression.suggest_next_load(
            logs=logs, exercise_name=exercise_name,
            current_weight=current_weight
        )
        return JSONResponse({
            'exercise': exercise_name,
            'current_weight_kg': current_weight,
            'suggested_next_load_kg': suggested
        })
    except Exception:
        logging.exception('Failed to compute suggestion')
        raise HTTPException(
            status_code=500,
            detail='Suggestion failed. Check progression.py implementation.'
        )


if __name__ == '__main__':
    import uvicorn

    uvicorn.run('app:app', host='127.0.0.1', port=8000, reload=True)
