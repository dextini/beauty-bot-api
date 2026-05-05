from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import sqlite3
import os
import httpx
from datetime import datetime, timedelta

app = FastAPI(title="Beauty Bot API")  # ← ЭТО САМОЕ ВАЖНОЕ

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "beauty.db"
DEFAULT_WORK_START = "09:00"
DEFAULT_WORK_END = "20:00"
SLOT_INTERVAL = 30


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS masters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            photo_url TEXT,
            description TEXT,
            address TEXT NOT NULL,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            phone TEXT,
            instagram TEXT,
            telegram_id TEXT,
            work_start TEXT DEFAULT '09:00',
            work_end TEXT DEFAULT '20:00'
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            master_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            duration_min INTEGER NOT NULL,
            FOREIGN KEY (master_id) REFERENCES masters(id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            master_id INTEGER NOT NULL,
            service_id INTEGER NOT NULL,
            client_name TEXT NOT NULL,
            client_telegram_id TEXT NOT NULL,
            client_phone TEXT,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (master_id) REFERENCES masters(id),
            FOREIGN KEY (service_id) REFERENCES services(id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS days_off (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            master_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            UNIQUE(master_id, date),
            FOREIGN KEY (master_id) REFERENCES masters(id)
        )
    """)
    for col in ["telegram_id TEXT", "work_start TEXT DEFAULT '09:00'", "work_end TEXT DEFAULT '20:00'"]:
        try:
            c.execute(f"ALTER TABLE masters ADD COLUMN {col}")
        except:
            pass
    conn.commit()
    conn.close()

init_db()


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def generate_slots(work_start: str, work_end: str, interval: int = 30) -> List[str]:
    slots = []
    start = datetime.strptime(work_start, "%H:%M")
    end = datetime.strptime(work_end, "%H:%M")
    current = start
    while current < end:
        slots.append(current.strftime("%H:%M"))
        current += timedelta(minutes=interval)
    return slots


@app.get("/")
def root():
    return {"status": "Beauty Bot API running 🌸"}


@app.get("/masters")
def get_masters(conn: sqlite3.Connection = Depends(get_db)):
    masters = conn.execute("SELECT * FROM masters").fetchall()
    result = []
    for m in masters:
        services = conn.execute("SELECT * FROM services WHERE master_id = ?", (m["id"],)).fetchall()
        master_dict = dict(m)
        master_dict["services"] = [dict(s) for s in services]
        result.append(master_dict)
    return result


@app.get("/masters/{master_id}/slots")
def get_free_slots(master_id: int, date: str, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT * FROM masters WHERE id = ?", (master_id,)).fetchone()
    if not master:
        raise HTTPException(status_code=404, detail="Master not found")
    day_off = conn.execute("SELECT id FROM days_off WHERE master_id=? AND date=?", (master_id, date)).fetchone()
    if day_off:
        return {"date": date, "slots": [], "day_off": True}
    work_start = master["work_start"] or DEFAULT_WORK_START
    work_end = master["work_end"] or DEFAULT_WORK_END
    all_slots = generate_slots(work_start, work_end)
    booked = conn.execute(
        "SELECT time FROM bookings WHERE master_id=? AND date=? AND status!='cancelled'",
        (master_id, date)
    ).fetchall()
    booked_times = {b["time"] for b in booked}
    today = datetime.now().strftime("%Y-%m-%d")
    now_time = datetime.now().strftime("%H:%M")
    free_slots = [
        s for s in all_slots
        if s not in booked_times and not (date == today and s <= now_time)
    ]
    return {"date": date, "slots": free_slots, "day_off": False}


# Для запуска через Python напрямую
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
