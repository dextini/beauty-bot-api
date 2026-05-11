from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import sqlite3
import os
import httpx
from datetime import datetime, timedelta

app = FastAPI(title="Beauty Bot API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "beauty.db"
MASTER_BOT_TOKEN = os.getenv("MASTER_BOT_TOKEN", "8236516081:AAFjIjQBiAMs95XpURSCZZhuuYr5yDrcmlw")
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
            bot_token TEXT,
            work_start TEXT DEFAULT '09:00',
            work_end TEXT DEFAULT '20:00',
            rating REAL DEFAULT 0,
            rating_count INTEGER DEFAULT 0
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
            reminder_sent INTEGER DEFAULT 0,
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
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER NOT NULL,
            master_id INTEGER NOT NULL,
            client_telegram_id TEXT NOT NULL,
            rating INTEGER NOT NULL,
            comment TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (booking_id) REFERENCES bookings(id),
            FOREIGN KEY (master_id) REFERENCES masters(id)
        )
    """)
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS promo_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            discount_percent INTEGER,
            valid_until TEXT,
            max_uses INTEGER,
            used_count INTEGER DEFAULT 0
        )
    """)
    
    for col in ["telegram_id TEXT", "work_start TEXT DEFAULT '09:00'", "work_end TEXT DEFAULT '20:00'", "bot_token TEXT", "rating REAL DEFAULT 0", "rating_count INTEGER DEFAULT 0"]:
        try:
            c.execute(f"ALTER TABLE masters ADD COLUMN {col}")
        except:
            pass
    
    try:
        c.execute("ALTER TABLE bookings ADD COLUMN reminder_sent INTEGER DEFAULT 0")
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
    
    c.execute("SELECT COUNT(*) FROM promo_codes")
    if c.fetchone()[0] == 0:
        future_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        c.execute("INSERT INTO promo_codes (code, discount_percent, valid_until, max_uses) VALUES (?,?,?,?)", ("WELCOME10", 10, future_date, 100))
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


async def notify_master(master_bot_token: str, master_telegram_id: str, message: str, booking_id: int = None):
    if not master_bot_token or not master_telegram_id:
        return
    try:
        async with httpx.AsyncClient() as client:
            reply_markup = None
            if booking_id:
                reply_markup = {
                    "inline_keyboard": [[
                        {"text": "✅ Подтвердить", "callback_data": f"confirm_{booking_id}"},
                        {"text": "❌ Отменить", "callback_data": f"cancel_{booking_id}"}
                    ]]
                }
            await client.post(
                f"https://api.telegram.org/bot{master_bot_token}/sendMessage",
                json={
                    "chat_id": master_telegram_id,
                    "text": message,
                    "parse_mode": "Markdown",
                    "reply_markup": reply_markup
                }
            )
    except Exception as e:
        print(f"Notify error: {e}")


async def send_message_to_client(telegram_id: str, message: str):
    if not telegram_id:
        return
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{MASTER_BOT_TOKEN}/sendMessage",
                json={"chat_id": telegram_id, "text": message, "parse_mode": "Markdown"}
            )
    except Exception as e:
        print(f"Send message error: {e}")


# ========== ОСНОВНЫЕ ЭНДПОИНТЫ ==========

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


@app.get("/masters/{master_id}")
def get_master(master_id: int, conn: sqlite3.Connection = Depends(get_db)):
    m = conn.execute("SELECT * FROM masters WHERE id = ?", (master_id,)).fetchone()
    if not m:
        raise HTTPException(status_code=404, detail="Master not found")
    services = conn.execute("SELECT * FROM services WHERE master_id = ?", (master_id,)).fetchall()
    master_dict = dict(m)
    master_dict["services"] = [dict(s) for s in services]
    return master_dict


@app.get("/masters/{master_id}/schedule")
def get_schedule(master_id: int, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT * FROM masters WHERE id = ?", (master_id,)).fetchone()
    if not master:
        raise HTTPException(status_code=404, detail="Master not found")
    
    result = []
    today = datetime.now()
    for i in range(7):
        day = (today + timedelta(days=i)).strftime("%Y-%m-%d")
        day_off = conn.execute("SELECT id FROM days_off WHERE master_id=? AND date=?", (master_id, day)).fetchone()
        bookings = conn.execute(
            """SELECT b.time, b.status, b.client_name, b.client_phone, s.name as service_name
               FROM bookings b JOIN services s ON b.service_id=s.id
               WHERE b.master_id=? AND b.date=? AND b.status!='cancelled' ORDER BY b.time""",
            (master_id, day)
        ).fetchall()
        result.append({"date": day, "day_off": bool(day_off), "bookings": [dict(b) for b in bookings]})
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


@app.post("/masters/{master_id}/services")
def add_service(master_id: int, service_data: dict, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT * FROM masters WHERE id = ?", (master_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    
    conn.execute(
        "INSERT INTO services (master_id, name, price, duration_min) VALUES (?,?,?,?)",
        (master_id, service_data["name"], service_data["price"], service_data["duration_min"])
    )
    conn.commit()
    return {"status": "ok", "service": service_data}


@app.delete("/services/{service_id}")
def delete_service(service_id: int, conn: sqlite3.Connection = Depends(get_db)):
    service = conn.execute("SELECT * FROM services WHERE id = ?", (service_id,)).fetchone()
    if not service:
        raise HTTPException(404, "Service not found")
    
    conn.execute("DELETE FROM services WHERE id = ?", (service_id,))
    conn.commit()
    return {"status": "ok"}


@app.get("/services/master/{master_id}")
def get_master_services(master_id: int, conn: sqlite3.Connection = Depends(get_db)):
    services = conn.execute("SELECT * FROM services WHERE master_id = ?", (master_id,)).fetchall()
    return [dict(s) for s in services]


@app.post("/masters/{master_id}/days_off")
def add_day_off(master_id: int, date: str, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("INSERT OR IGNORE INTO days_off (master_id, date) VALUES (?,?)", (master_id, date))
    conn.commit()
    return {"status": "ok", "date": date}


@app.delete("/masters/{master_id}/days_off/{date}")
def remove_day_off(master_id: int, date: str, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("DELETE FROM days_off WHERE master_id=? AND date=?", (master_id, date))
    conn.commit()
    return {"status": "ok", "date": date}


@app.patch("/masters/{master_id}/work-hours")
def set_work_hours(master_id: int, work_start: str, work_end: str, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("UPDATE masters SET work_start=?, work_end=? WHERE id=?", (work_start, work_end, master_id))
    conn.commit()
    return {"status": "ok"}


@app.patch("/masters/{master_id}/bot-token")
def set_master_bot_token(master_id: int, bot_token: str, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("UPDATE masters SET bot_token = ? WHERE id = ?", (bot_token, master_id))
    conn.commit()
    return {"status": "ok"}


@app.patch("/masters/{master_id}/telegram")
def set_master_telegram(master_id: int, telegram_id: str, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("UPDATE masters SET telegram_id = ? WHERE id = ?", (telegram_id, master_id))
    conn.commit()
    return {"status": "ok"}


# ========== РЕГИСТРАЦИЯ ==========

@app.post("/register-request")
def register_request(data: dict, conn: sqlite3.Connection = Depends(get_db)):
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


# ========== ЗАПИСИ ==========

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
    
    if master["bot_token"] and master["telegram_id"]:
        message = (
            f"🌸 *Новая запись!*\n\n"
            f"👩 Клиент: {data['client_name']}\n"
            f"💅 Услуга: {service['name']}\n"
            f"💰 Цена: {service['price']} ₽\n"
            f"📅 Дата: {data['date']}\n"
            f"🕐 Время: {data['time']}"
        )
        await notify_master(master["bot_token"], master["telegram_id"], message, booking_id)
    
    booking = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    return dict(booking)


@app.get("/bookings/{booking_id}")
def get_booking(booking_id: int, conn: sqlite3.Connection = Depends(get_db)):
    booking = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    if not booking:
        raise HTTPException(404, "Booking not found")
    return dict(booking)


@app.patch("/bookings/{booking_id}/status")
async def update_master_booking_status(booking_id: int, status: str, conn: sqlite3.Connection = Depends(get_db)):
    booking = conn.execute(
        """SELECT b.*, m.name as master_name, m.bot_token, s.name as service_name 
           FROM bookings b 
           JOIN masters m ON b.master_id = m.id 
           JOIN services s ON b.service_id = s.id 
           WHERE b.id = ?""",
        (booking_id,)
    ).fetchone()
    if not booking:
        raise HTTPException(404, "Booking not found")
    
    conn.execute("UPDATE bookings SET status = ? WHERE id = ?", (status, booking_id))
    conn.commit()
    
    if status == "confirmed":
        await send_message_to_client(
            booking["client_telegram_id"],
            f"🎉 *Запись подтверждена!*\n\n💅 {booking['service_name']}\n👩 {booking['master_name']}\n📅 {booking['date']} в {booking['time']}\n\nЖдём вас! ✨"
        )
    elif status == "cancelled":
        await send_message_to_client(
            booking["client_telegram_id"],
            f"😔 *Запись отменена*\n\n💅 {booking['service_name']}\n📅 {booking['date']} в {booking['time']}\n\nВы можете записаться снова. 🌸"
        )
    
    return {"status": "ok", "booking_id": booking_id, "new_status": status}


@app.get("/bookings/master/{master_id}")
def get_master_bookings(master_id: int, conn: sqlite3.Connection = Depends(get_db)):
    bookings = conn.execute(
        """SELECT b.*, s.name as service_name, s.price FROM bookings b
           JOIN services s ON b.service_id=s.id
           WHERE b.master_id=? AND b.status!='cancelled' ORDER BY b.date, b.time""",
        (master_id,)
    ).fetchall()
    return [dict(b) for b in bookings]


@app.get("/bookings/client/{telegram_id}")
def get_client_bookings(telegram_id: str, conn: sqlite3.Connection = Depends(get_db)):
    bookings = conn.execute(
        """SELECT b.*, m.name as master_name, s.name as service_name, s.price
           FROM bookings b JOIN masters m ON b.master_id=m.id JOIN services s ON b.service_id=s.id
           WHERE b.client_telegram_id=? ORDER BY b.date DESC, b.time DESC""",
        (telegram_id,)
    ).fetchall()
    return [dict(b) for b in bookings]


# ========== ИННОВАЦИИ ==========

@app.post("/reviews")
def add_review(data: dict, conn: sqlite3.Connection = Depends(get_db)):
    booking = conn.execute("SELECT * FROM bookings WHERE id = ?", (data["booking_id"],)).fetchone()
    if not booking or booking["status"] != "confirmed":
        raise HTTPException(400, "Можно оценить только подтверждённую запись")
    
    conn.execute(
        "INSERT INTO reviews (booking_id, master_id, client_telegram_id, rating, comment) VALUES (?,?,?,?,?)",
        (data["booking_id"], booking["master_id"], booking["client_telegram_id"], data["rating"], data.get("comment"))
    )
    
    avg_rating = conn.execute(
        "SELECT AVG(rating) as avg_r, COUNT(*) as cnt FROM reviews WHERE master_id=?",
        (booking["master_id"],)
    ).fetchone()
    
    conn.execute(
        "UPDATE masters SET rating=?, rating_count=? WHERE id=?",
        (avg_rating["avg_r"] or 0, avg_rating["cnt"], booking["master_id"])
    )
    conn.commit()
    return {"status": "ok"}


@app.get("/masters/{master_id}/reviews")
def get_master_reviews(master_id: int, conn: sqlite3.Connection = Depends(get_db)):
    reviews = conn.execute(
        "SELECT * FROM reviews WHERE master_id=? ORDER BY created_at DESC LIMIT 20",
        (master_id,)
    ).fetchall()
    return [dict(r) for r in reviews]


@app.post("/apply-promo")
def apply_promo(data: dict, conn: sqlite3.Connection = Depends(get_db)):
    promo = conn.execute(
        "SELECT * FROM promo_codes WHERE code=? AND valid_until >= date('now') AND (max_uses IS NULL OR used_count < max_uses)",
        (data["code"],)
    ).fetchone()
    if not promo:
        raise HTTPException(404, "Промокод недействителен")
    
    conn.execute("UPDATE promo_codes SET used_count = used_count + 1 WHERE id = ?", (promo["id"],))
    conn.commit()
    
    return {"status": "ok", "discount_percent": promo["discount_percent"]}


@app.get("/send-reminders")
async def send_reminders(conn: sqlite3.Connection = Depends(get_db)):
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    bookings = conn.execute(
        "SELECT b.*, m.name as master_name FROM bookings b JOIN masters m ON b.master_id=m.id WHERE b.date=? AND b.status='confirmed' AND b.reminder_sent=0",
        (tomorrow,)
    ).fetchall()
    
    for booking in bookings:
        await send_message_to_client(
            booking["client_telegram_id"],
            f"⏰ *Напоминание!*\n\nЗавтра {booking['date']} в {booking['time']} запись к {booking['master_name']}.\n\nЖдём вас! ✨"
        )
        conn.execute("UPDATE bookings SET reminder_sent=1 WHERE id=?", (booking["id"],))
    conn.commit()
    return {"sent": len(bookings)}


@app.get("/masters/{master_id}/stats")
def get_master_stats(master_id: int, conn: sqlite3.Connection = Depends(get_db)):
    total_bookings = conn.execute(
        "SELECT COUNT(*) as total FROM bookings WHERE master_id=? AND status='confirmed'",
        (master_id,)
    ).fetchone()
    
    monthly = conn.execute(
        "SELECT COUNT(*) as count, SUM(s.price) as revenue FROM bookings b JOIN services s ON b.service_id=s.id WHERE b.master_id=? AND b.status='confirmed' AND strftime('%Y-%m', b.date) = strftime('%Y-%m', 'now')",
        (master_id,)
    ).fetchone()
    
    popular_service = conn.execute(
        "SELECT s.name, COUNT(*) as cnt FROM bookings b JOIN services s ON b.service_id=s.id WHERE b.master_id=? GROUP BY s.id ORDER BY cnt DESC LIMIT 1",
        (master_id,)
    ).fetchone()
    
    return {
        "total_bookings": total_bookings["total"],
        "monthly_bookings": monthly["count"],
        "monthly_revenue": monthly["revenue"] or 0,
        "popular_service": popular_service["name"] if popular_service else None
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
