from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import sqlite3
import os
from datetime import datetime, timedelta

app = FastAPI(title="Beauty Bot API")

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
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS register_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id TEXT UNIQUE,
            name TEXT,
            address TEXT,
            phone TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    for col in ["telegram_id TEXT", "work_start TEXT DEFAULT '09:00'", "work_end TEXT DEFAULT '20:00'", "bot_token TEXT"]:
        try:
            c.execute(f"ALTER TABLE masters ADD COLUMN {col}")
        except:
            pass
    
    c.execute("SELECT COUNT(*) FROM masters")
    if c.fetchone()[0] == 0:
        masters_data = [
            ("Алина Козлова", None, "Мастер маникюра с 5-летним опытом", "ул. Ленина, 12", 55.751244, 37.618423, "+79001234567", "@alina_nails"),
            ("Мария Иванова", None, "Профессиональный визажист и мастер бровей", "пр. Мира, 45", 55.763244, 37.628423, "+79009876543", "@maria_beauty"),
            ("Екатерина Смирнова", None, "Специалист по уходу за ресницами", "ул. Садовая, 8", 55.745244, 37.608423, "+79005551234", "@kate_lashes"),
        ]
        c.executemany("INSERT INTO masters (name, photo_url, description, address, lat, lon, phone, instagram) VALUES (?,?,?,?,?,?,?,?)", masters_data)
        conn.commit()
        
        c.execute("SELECT id FROM masters")
        ids = [row[0] for row in c.fetchall()]
        services = [
            (ids[0], "Маникюр классический", 1200, 60),
            (ids[0], "Маникюр с покрытием гель-лак", 2000, 90),
            (ids[0], "Педикюр", 2500, 120),
            (ids[1], "Макияж дневной", 2500, 60),
            (ids[1], "Коррекция бровей", 800, 30),
            (ids[1], "Макияж вечерний", 4000, 90),
            (ids[2], "Наращивание ресниц", 3000, 120),
            (ids[2], "Ламинирование ресниц", 2500, 90),
        ]
        c.executemany("INSERT INTO services (master_id, name, price, duration_min) VALUES (?,?,?,?)", services)
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


@app.get("/masters/by-telegram/{telegram_id}")
def get_master_by_telegram(telegram_id: str, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT * FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(status_code=404, detail="Master not found")
    return dict(master)


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


@app.post("/bookings")
async def create_booking(data: dict, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT * FROM masters WHERE id = ?", (data["master_id"],)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    
    service = conn.execute("SELECT * FROM services WHERE id=? AND master_id=?", (data["service_id"], data["master_id"])).fetchone()
    if not service:
        raise HTTPException(404, "Service not found")
    
    day_off = conn.execute("SELECT id FROM days_off WHERE master_id=? AND date=?", (data["master_id"], data["date"])).fetchone()
    if day_off:
        raise HTTPException(409, "Master is off this day")
    
    existing = conn.execute(
        "SELECT id FROM bookings WHERE master_id=? AND date=? AND time=? AND status!='cancelled'",
        (data["master_id"], data["date"], data["time"])
    ).fetchone()
    if existing:
        raise HTTPException(409, "This time slot is already booked")
    
    cursor = conn.execute(
        "INSERT INTO bookings (master_id, service_id, client_name, client_telegram_id, client_phone, date, time) VALUES (?,?,?,?,?,?,?)",
        (data["master_id"], data["service_id"], data["client_name"], data["client_telegram_id"], data.get("client_phone"), data["date"], data["time"])
    )
    conn.commit()
    booking_id = cursor.lastrowid
    
    booking = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    return dict(booking)


@app.post("/register-request")
async def register_request(data: dict, conn: sqlite3.Connection = Depends(get_db)):
    existing = conn.execute("SELECT id FROM register_requests WHERE telegram_id=?", (data["telegram_id"],)).fetchone()
    if existing:
        raise HTTPException(409, "Request already exists")
    conn.execute(
        "INSERT INTO register_requests (telegram_id, name, address, phone) VALUES (?,?,?,?)",
        (data["telegram_id"], data["name"], data["address"], data["phone"])
    )
    conn.commit()
    return {"status": "ok"}


@app.get("/register-requests/pending")
def get_pending_requests(conn: sqlite3.Connection = Depends(get_db)):
    requests = conn.execute("SELECT * FROM register_requests WHERE status='pending'").fetchall()
    return [dict(r) for r in requests]


@app.post("/approve-master/{telegram_id}")
def approve_master(telegram_id: str, conn: sqlite3.Connection = Depends(get_db)):
    request = conn.execute("SELECT * FROM register_requests WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not request:
        raise HTTPException(404, "Request not found")
    conn.execute(
        "INSERT INTO masters (name, address, phone, telegram_id, lat, lon, description) VALUES (?,?,?,?,?,?,?)",
        (request["name"], request["address"], request["phone"], telegram_id, 55.751244, 37.618423, "Новый мастер")
    )
    conn.execute("UPDATE register_requests SET status='approved' WHERE telegram_id=?", (telegram_id,))
    conn.commit()
    return {"status": "ok"}


@app.patch("/masters/{master_id}/bot-token")
def set_master_bot_token(master_id: int, bot_token: str, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("UPDATE masters SET bot_token = ? WHERE id = ?", (bot_token, master_id))
    conn.commit()
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
