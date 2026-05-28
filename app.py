import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("FIT_DATA_DIR", str(BASE_DIR)))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "fitness.db"
STATIC_DIR = BASE_DIR / "static"

app = FastAPI()

ROUTINES = {
    "day_a": {
        "name": "Day A",
        "exercises": [
            {"name": "Bodyweight Squat", "type": "reps", "sets": 3, "target_reps": "15-20", "notes": "Slow descent (3 sec), pause at bottom"},
            {"name": "Glute Bridge", "type": "reps", "sets": 3, "target_reps": "15", "notes": "Squeeze glutes hard at top"},
            {"name": "Incline Pushup", "type": "amrap", "sets": 3, "target_reps": "AMRAP", "notes": "Hands on counter/desk/sturdy surface"},
            {"name": "Bent-over Row", "type": "reps", "sets": 3, "target_reps": "10-12", "notes": "5 lb dumbbells, back flat, squeeze shoulder blades"},
            {"name": "Plank", "type": "timed", "sets": 3, "target_duration": 30, "notes": "Work up to 45-60 sec"},
        ],
    },
    "day_b": {
        "name": "Day B",
        "exercises": [
            {"name": "Reverse Lunge", "type": "reps", "sets": 3, "target_reps": "10/leg", "notes": "Bodyweight first, add dumbbells later"},
            {"name": "Single-leg Glute Bridge", "type": "reps", "sets": 3, "target_reps": "8-10/side", "notes": "One foot off the floor"},
            {"name": "Pike Pushup", "type": "reps", "sets": 3, "target_reps": "5-8", "notes": "Downward dog position, lower head toward floor"},
            {"name": "Single-arm Bent-over Row", "type": "reps", "sets": 3, "target_reps": "10/side", "notes": "Brace non-working hand on chair/couch"},
            {"name": "Dead Bug", "type": "reps", "sets": 3, "target_reps": "8/side", "notes": "Slow opposite arm/leg lowers"},
        ],
    },
    "day_c": {
        "name": "Day C",
        "exercises": [
            {"name": "Bulgarian Split Squat", "type": "reps", "sets": 3, "target_reps": "8-10/leg", "notes": "Back foot on couch/chair, bodyweight to start"},
            {"name": "Hip Thrust", "type": "reps", "sets": 3, "target_reps": "12-15", "notes": "Pause and squeeze 2 sec at top"},
            {"name": "Pushup Variation", "type": "amrap", "sets": 3, "target_reps": "AMRAP", "notes": "Incline, knee, or full"},
            {"name": "Superman Hold", "type": "timed", "sets": 3, "target_duration": 25, "notes": "Face down, lift arms/chest/legs"},
            {"name": "Side Plank", "type": "timed", "sets": 3, "target_duration": 17, "notes": "Knee-supported version is fine to start"},
        ],
    },
}

WARMUP = [
    "Arm circles",
    "Leg swings (front-to-back, side-to-side)",
    "Bodyweight squats × 10",
    "Hip circles",
    "Cat-cows × 5",
]

ACTIVITY_CANONICAL = [
    "Pickleball", "Bike Ride", "Walking", "Hiking",
    "Swimming", "Yoga", "Stretching", "Running",
]
_ACTIVITY_CANONICAL_LOWER = {c.lower(): c for c in ACTIVITY_CANONICAL}


def normalize_activity_name(name):
    if not name:
        return name
    cleaned = " ".join(name.split())
    if not cleaned:
        return cleaned
    canonical = _ACTIVITY_CANONICAL_LOWER.get(cleaned.lower())
    if canonical:
        return canonical
    return cleaned.title()


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS workouts (
                id TEXT PRIMARY KEY,
                date TEXT NOT NULL,
                type TEXT NOT NULL,
                name TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                duration_seconds INTEGER,
                notes TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS exercises (
                id TEXT PRIMARY KEY,
                workout_id TEXT NOT NULL REFERENCES workouts(id) ON DELETE CASCADE,
                exercise_name TEXT NOT NULL,
                exercise_type TEXT NOT NULL DEFAULT 'reps',
                target_sets INTEGER NOT NULL DEFAULT 3,
                target_reps TEXT,
                target_duration_seconds INTEGER,
                order_index INTEGER NOT NULL,
                notes TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sets (
                id TEXT PRIMARY KEY,
                exercise_id TEXT NOT NULL REFERENCES exercises(id) ON DELETE CASCADE,
                set_number INTEGER NOT NULL,
                reps INTEGER,
                weight_lbs REAL,
                duration_seconds INTEGER,
                completed INTEGER NOT NULL DEFAULT 0,
                completed_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS weight_entries (
                id TEXT PRIMARY KEY,
                date TEXT NOT NULL,
                weight_lbs REAL NOT NULL,
                notes TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS custom_activities (
                id TEXT PRIMARY KEY,
                date TEXT NOT NULL,
                activity_name TEXT NOT NULL,
                duration_minutes INTEGER,
                notes TEXT
            )
        """)

        for r in conn.execute("SELECT id, activity_name FROM custom_activities").fetchall():
            normalized = normalize_activity_name(r["activity_name"])
            if normalized != r["activity_name"]:
                conn.execute(
                    "UPDATE custom_activities SET activity_name = ? WHERE id = ?",
                    (normalized, r["id"]),
                )


def get_workout_full(conn, workout_id):
    row = conn.execute("SELECT * FROM workouts WHERE id = ?", (workout_id,)).fetchone()
    if not row:
        return None
    w = dict(row)
    ex_rows = conn.execute(
        "SELECT * FROM exercises WHERE workout_id = ? ORDER BY order_index", (workout_id,)
    ).fetchall()
    exercises = []
    for ex in ex_rows:
        e = dict(ex)
        set_rows = conn.execute(
            "SELECT * FROM sets WHERE exercise_id = ? ORDER BY set_number", (e["id"],)
        ).fetchall()
        e["sets"] = [dict(s) for s in set_rows]
        exercises.append(e)
    w["exercises"] = exercises
    return w


class WorkoutIn(BaseModel):
    date: str
    type: str
    name: str
    notes: Optional[str] = None


class WorkoutUpdate(BaseModel):
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    duration_seconds: Optional[int] = None
    notes: Optional[str] = None


class SetUpdate(BaseModel):
    reps: Optional[int] = None
    weight_lbs: Optional[float] = None
    duration_seconds: Optional[int] = None
    completed: int = Field(ge=0, le=1)


class WeightIn(BaseModel):
    date: str
    weight_lbs: float = Field(gt=0, le=1000)
    notes: Optional[str] = None


class ActivityIn(BaseModel):
    date: str
    activity_name: str
    duration_minutes: Optional[int] = None
    notes: Optional[str] = None


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/routines")
async def get_routines():
    return {"routines": ROUTINES, "warmup": WARMUP}


@app.get("/api/workouts")
async def list_workouts(date: Optional[str] = None):
    with db() as conn:
        if date:
            rows = conn.execute(
                "SELECT id, date, type, name, started_at, finished_at, duration_seconds, notes FROM workouts WHERE date = ? ORDER BY started_at DESC",
                (date,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, date, type, name, started_at, finished_at, duration_seconds, notes FROM workouts ORDER BY date DESC, started_at DESC"
            ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/workouts")
async def create_workout(workout: WorkoutIn):
    workout_id = secrets.token_hex(8)
    now = datetime.now(timezone.utc).isoformat()

    with db() as conn:
        conn.execute(
            "INSERT INTO workouts (id, date, type, name, started_at, notes) VALUES (?, ?, ?, ?, ?, ?)",
            (workout_id, workout.date, workout.type, workout.name, now, workout.notes),
        )

        if workout.type in ROUTINES:
            routine = ROUTINES[workout.type]
            for idx, ex_def in enumerate(routine["exercises"]):
                ex_id = secrets.token_hex(8)
                conn.execute(
                    """INSERT INTO exercises
                       (id, workout_id, exercise_name, exercise_type, target_sets, target_reps, target_duration_seconds, order_index, notes)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (ex_id, workout_id, ex_def["name"], ex_def["type"], ex_def["sets"],
                     ex_def.get("target_reps"), ex_def.get("target_duration"), idx, ex_def.get("notes")),
                )
                for set_num in range(1, ex_def["sets"] + 1):
                    set_id = secrets.token_hex(8)
                    conn.execute(
                        "INSERT INTO sets (id, exercise_id, set_number, completed) VALUES (?, ?, ?, 0)",
                        (set_id, ex_id, set_num),
                    )

        return get_workout_full(conn, workout_id)


@app.get("/api/workouts/{workout_id}")
async def get_workout(workout_id: str):
    with db() as conn:
        w = get_workout_full(conn, workout_id)
    if not w:
        raise HTTPException(status_code=404, detail="Workout not found")
    return w


@app.put("/api/workouts/{workout_id}")
async def update_workout(workout_id: str, update: WorkoutUpdate):
    with db() as conn:
        row = conn.execute("SELECT id FROM workouts WHERE id = ?", (workout_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Workout not found")
        fields = []
        values = []
        for field in ("started_at", "finished_at", "duration_seconds", "notes"):
            val = getattr(update, field)
            if val is not None:
                fields.append(f"{field} = ?")
                values.append(val)
        if fields:
            values.append(workout_id)
            conn.execute(f"UPDATE workouts SET {', '.join(fields)} WHERE id = ?", values)
        return get_workout_full(conn, workout_id)


@app.delete("/api/workouts/{workout_id}")
async def delete_workout(workout_id: str):
    with db() as conn:
        cur = conn.execute("DELETE FROM workouts WHERE id = ?", (workout_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Workout not found")
    return {"ok": True}


@app.put("/api/sets/{set_id}")
async def update_set(set_id: str, update: SetUpdate):
    now = datetime.now(timezone.utc).isoformat() if update.completed else None
    with db() as conn:
        cur = conn.execute(
            "UPDATE sets SET reps = ?, weight_lbs = ?, duration_seconds = ?, completed = ?, completed_at = ? WHERE id = ?",
            (update.reps, update.weight_lbs, update.duration_seconds, update.completed, now, set_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Set not found")
        row = conn.execute("SELECT * FROM sets WHERE id = ?", (set_id,)).fetchone()
    return dict(row)


@app.get("/api/weight")
async def list_weight():
    with db() as conn:
        rows = conn.execute(
            "SELECT id, date, weight_lbs, notes FROM weight_entries ORDER BY date DESC"
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/weight")
async def create_weight(entry: WeightIn):
    entry_id = secrets.token_hex(8)
    with db() as conn:
        conn.execute(
            "INSERT INTO weight_entries (id, date, weight_lbs, notes) VALUES (?, ?, ?, ?)",
            (entry_id, entry.date, entry.weight_lbs, entry.notes),
        )
    return {"id": entry_id, "date": entry.date, "weight_lbs": entry.weight_lbs, "notes": entry.notes}


@app.delete("/api/weight/{entry_id}")
async def delete_weight(entry_id: str):
    with db() as conn:
        cur = conn.execute("DELETE FROM weight_entries WHERE id = ?", (entry_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Entry not found")
    return {"ok": True}


@app.get("/api/activities")
async def list_activities():
    with db() as conn:
        rows = conn.execute(
            "SELECT id, date, activity_name, duration_minutes, notes FROM custom_activities ORDER BY date DESC"
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/activities")
async def create_activity(entry: ActivityIn):
    entry_id = secrets.token_hex(8)
    name = normalize_activity_name(entry.activity_name)
    with db() as conn:
        conn.execute(
            "INSERT INTO custom_activities (id, date, activity_name, duration_minutes, notes) VALUES (?, ?, ?, ?, ?)",
            (entry_id, entry.date, name, entry.duration_minutes, entry.notes),
        )
    return {"id": entry_id, "date": entry.date, "activity_name": name,
            "duration_minutes": entry.duration_minutes, "notes": entry.notes}


@app.delete("/api/activities/{entry_id}")
async def delete_activity(entry_id: str):
    with db() as conn:
        cur = conn.execute("DELETE FROM custom_activities WHERE id = ?", (entry_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Activity not found")
    return {"ok": True}


@app.get("/api/trends/exercise")
async def exercise_trends(name: str):
    with db() as conn:
        rows = conn.execute("""
            SELECT w.date, e.exercise_type, s.set_number, s.reps, s.weight_lbs, s.duration_seconds
            FROM sets s
            JOIN exercises e ON s.exercise_id = e.id
            JOIN workouts w ON e.workout_id = w.id
            WHERE e.exercise_name = ? AND s.completed = 1
            ORDER BY w.date, s.set_number
        """, (name,)).fetchall()

    by_date = {}
    for r in rows:
        d = r["date"]
        if d not in by_date:
            by_date[d] = {"date": d, "type": r["exercise_type"], "sets": []}
        by_date[d]["sets"].append({
            "set_number": r["set_number"],
            "reps": r["reps"],
            "weight_lbs": r["weight_lbs"],
            "duration_seconds": r["duration_seconds"],
        })

    result = []
    for d in sorted(by_date.keys()):
        entry = by_date[d]
        sets = entry["sets"]
        if entry["type"] == "timed":
            entry["value"] = max((s["duration_seconds"] or 0) for s in sets)
            entry["label"] = "sec"
        else:
            entry["value"] = sum((s["reps"] or 0) for s in sets)
            entry["label"] = "reps"
            max_weight = max((s["weight_lbs"] or 0) for s in sets)
            if max_weight > 0:
                entry["max_weight"] = max_weight
        result.append(entry)

    return result


@app.get("/api/trends/calendar")
async def calendar_trends(month: str):
    like = month + "%"
    with db() as conn:
        workouts = conn.execute(
            "SELECT date, type, name FROM workouts WHERE date LIKE ? ORDER BY date", (like,)
        ).fetchall()
        activities = conn.execute(
            "SELECT date, activity_name FROM custom_activities WHERE date LIKE ? ORDER BY date", (like,)
        ).fetchall()
    return {
        "workouts": [dict(r) for r in workouts],
        "activities": [dict(r) for r in activities],
    }


@app.get("/api/trends/exercises-list")
async def exercises_list():
    with db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT exercise_name FROM exercises ORDER BY exercise_name"
        ).fetchall()
    return [r["exercise_name"] for r in rows]


@app.get("/api/trends/activities-list")
async def activities_list():
    with db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT activity_name FROM custom_activities "
            "WHERE duration_minutes IS NOT NULL ORDER BY activity_name"
        ).fetchall()
    return [r["activity_name"] for r in rows]


@app.get("/api/trends/activity")
async def activity_trend(name: str):
    with db() as conn:
        rows = conn.execute(
            "SELECT date, SUM(duration_minutes) as total FROM custom_activities "
            "WHERE activity_name = ? AND duration_minutes IS NOT NULL "
            "GROUP BY date ORDER BY date",
            (name,),
        ).fetchall()
    return [{"date": r["date"], "value": r["total"], "label": "min"} for r in rows]


@app.get("/api/export")
async def export_data():
    with db() as conn:
        workouts = []
        for w in conn.execute("SELECT * FROM workouts ORDER BY date DESC").fetchall():
            workouts.append(get_workout_full(conn, w["id"]))
        weight = [dict(r) for r in conn.execute("SELECT * FROM weight_entries ORDER BY date DESC").fetchall()]
        activities = [dict(r) for r in conn.execute("SELECT * FROM custom_activities ORDER BY date DESC").fetchall()]
    return {"workouts": workouts, "weight_entries": weight, "custom_activities": activities}


@app.post("/api/import")
async def import_data(data: dict):
    added = {"workouts": 0, "weight_entries": 0, "custom_activities": 0}
    with db() as conn:
        for w in data.get("weight_entries", []):
            try:
                wid = w.get("id") or secrets.token_hex(8)
                conn.execute(
                    "INSERT OR IGNORE INTO weight_entries (id, date, weight_lbs, notes) VALUES (?, ?, ?, ?)",
                    (wid, w["date"], w["weight_lbs"], w.get("notes")),
                )
                added["weight_entries"] += 1
            except Exception:
                continue
        for a in data.get("custom_activities", []):
            try:
                aid = a.get("id") or secrets.token_hex(8)
                conn.execute(
                    "INSERT OR IGNORE INTO custom_activities (id, date, activity_name, duration_minutes, notes) VALUES (?, ?, ?, ?, ?)",
                    (aid, a["date"], normalize_activity_name(a["activity_name"]), a.get("duration_minutes"), a.get("notes")),
                )
                added["custom_activities"] += 1
            except Exception:
                continue
        for w in data.get("workouts", []):
            try:
                wid = w.get("id") or secrets.token_hex(8)
                existing = conn.execute("SELECT id FROM workouts WHERE id = ?", (wid,)).fetchone()
                if existing:
                    continue
                conn.execute(
                    "INSERT INTO workouts (id, date, type, name, started_at, finished_at, duration_seconds, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (wid, w["date"], w["type"], w["name"], w.get("started_at"), w.get("finished_at"), w.get("duration_seconds"), w.get("notes")),
                )
                for ex in w.get("exercises", []):
                    eid = ex.get("id") or secrets.token_hex(8)
                    conn.execute(
                        "INSERT INTO exercises (id, workout_id, exercise_name, exercise_type, target_sets, target_reps, target_duration_seconds, order_index, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (eid, wid, ex["exercise_name"], ex["exercise_type"], ex["target_sets"], ex.get("target_reps"), ex.get("target_duration_seconds"), ex["order_index"], ex.get("notes")),
                    )
                    for s in ex.get("sets", []):
                        sid = s.get("id") or secrets.token_hex(8)
                        conn.execute(
                            "INSERT INTO sets (id, exercise_id, set_number, reps, weight_lbs, duration_seconds, completed, completed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (sid, eid, s["set_number"], s.get("reps"), s.get("weight_lbs"), s.get("duration_seconds"), s.get("completed", 0), s.get("completed_at")),
                        )
                added["workouts"] += 1
            except Exception:
                continue
    return added


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


if __name__ == "__main__":
    init_db()
    uvicorn.run(
        app,
        host=os.environ.get("FIT_HOST", "0.0.0.0"),
        port=int(os.environ.get("FIT_PORT", "8322")),
    )
