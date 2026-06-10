from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List
import sqlite3
import os
import json
import secrets
from datetime import datetime, timedelta
import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Beauty Bot API")

# === КОНФИГУРАЦИЯ ===
PAYMENT_COMMISSION = 0.07
MASTER_BOT_TOKEN = os.getenv("MASTER_BOT_TOKEN", "8236516081:AAFjIjQBiAMs95XpURSCZZhuuYr5yDrcmlw")

# === CORS ===
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_cors_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "*"
    return response

@app.options("/{path:path}")
async def options_handler(path: str):
    return JSONResponse(content={"message": "OK"}, headers={"Access-Control-Allow-Origin": "*"})

DB_PATH = "beauty.db"
DEFAULT_WORK_START = "09:00"
DEFAULT_WORK_END = "20:00"

# ========== МОДЕЛИ ==========
class ServiceIn(BaseModel):
    name: str
    price: int
    duration_min: int

class MasterIn(BaseModel):
    name: str
    address: str
    lat: float = 47.222078
    lon: float = 39.720358
    phone: str = ""
    instagram: str = ""
    description: str = ""
    icon: str = "💅"
    telegram_id: str = None

class BookingIn(BaseModel):
    master_id: int
    service_id: int
    client_name: str
    client_telegram_id: str
    client_phone: Optional[str]
    date: str
    time: str

class MessageIn(BaseModel):
    booking_id: int
    from_id: str
    to_id: str
    message: str = None

class ReviewIn(BaseModel):
    master_id: int
    booking_id: int
    client_name: str
    rating: int
    comment: str = None

class LocationUpdate(BaseModel):
    lat: float
    lon: float

class WorkHoursUpdate(BaseModel):
    work_start: str
    work_end: str

class TelegramIdUpdate(BaseModel):
    telegram_id: str

class UserRegister(BaseModel):
    telegram_id: str

class DayOffRequest(BaseModel):
    date: str

# ========== БД ==========
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS masters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, photo_url TEXT, description TEXT, address TEXT,
            lat REAL, lon REAL, phone TEXT, instagram TEXT, telegram_id TEXT,
            work_start TEXT DEFAULT '09:00', work_end TEXT DEFAULT '20:00',
            registered_at TEXT DEFAULT CURRENT_TIMESTAMP,
            bot_token TEXT, photos TEXT, rating REAL DEFAULT 0, icon TEXT DEFAULT '💅'
        )
    """)
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            master_id INTEGER, name TEXT, price INTEGER, duration_min INTEGER,
            FOREIGN KEY (master_id) REFERENCES masters(id)
        )
    """)
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            master_id INTEGER, service_id INTEGER,
            client_name TEXT, client_telegram_id TEXT, client_phone TEXT,
            date TEXT, time TEXT,
            status TEXT DEFAULT 'pending_payment',
            payment_status TEXT DEFAULT 'pending',
            deposit_amount REAL DEFAULT 0,
            payment_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            confirmed_at TEXT,
            FOREIGN KEY (master_id) REFERENCES masters(id),
            FOREIGN KEY (service_id) REFERENCES services(id)
        )
    """)
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS days_off (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            master_id INTEGER, date TEXT,
            UNIQUE(master_id, date)
        )
    """)
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER UNIQUE,
            master_id INTEGER,
            client_telegram_id TEXT,
            master_telegram_id TEXT,
            token TEXT UNIQUE
        )
    """)
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            master_id INTEGER, booking_id INTEGER UNIQUE,
            client_name TEXT, rating INTEGER, comment TEXT,
            master_reply TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id TEXT UNIQUE,
            registered_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER, amount REAL,
            status TEXT DEFAULT 'pending',
            payment_id TEXT UNIQUE,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER, from_id TEXT, to_id TEXT,
            message TEXT, photo_url TEXT, is_read INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    
    # Добавляем колонки если нет
    try:
        c.execute("ALTER TABLE bookings ADD COLUMN deposit_amount REAL DEFAULT 0")
    except: pass
    try:
        c.execute("ALTER TABLE bookings ADD COLUMN payment_id TEXT")
    except: pass
    try:
        c.execute("ALTER TABLE bookings ADD COLUMN confirmed_at TEXT")
    except: pass
    try:
        c.execute("ALTER TABLE masters ADD COLUMN work_start TEXT DEFAULT '09:00'")
    except: pass
    try:
        c.execute("ALTER TABLE masters ADD COLUMN work_end TEXT DEFAULT '20:00'")
    except: pass
    
    # Тестовые данные
    c.execute("SELECT COUNT(*) FROM masters")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO masters (name, address, lat, lon, phone, instagram, icon) VALUES (?,?,?,?,?,?,?)",
                  ("Алина Козлова", "ул. Ленина, 12", 47.222078, 39.720358, "+79001234567", "@alina_nails", "💅"))
        c.execute("INSERT INTO masters (name, address, lat, lon, phone, instagram, icon) VALUES (?,?,?,?,?,?,?)",
                  ("Мария Иванова", "пр. Мира, 45", 47.223078, 39.721358, "+79009876543", "@maria_beauty", "👁️"))
        c.execute("INSERT INTO masters (name, address, lat, lon, phone, instagram, icon) VALUES (?,?,?,?,?,?,?)",
                  ("Екатерина Смирнова", "ул. Садовая, 8", 47.221078, 39.719358, "+79005551234", "@kate_lashes", "👀"))
        
        c.execute("SELECT id FROM masters")
        ids = [row[0] for row in c.fetchall()]
        c.executemany("INSERT INTO services (master_id, name, price, duration_min) VALUES (?,?,?,?)", [
            (ids[0], "Маникюр", 1200, 60), (ids[0], "Педикюр", 2500, 120),
            (ids[1], "Макияж", 2500, 60), (ids[1], "Коррекция бровей", 800, 30),
            (ids[2], "Наращивание ресниц", 3000, 120), (ids[2], "Ламинирование ресниц", 2500, 90)
        ])
        conn.commit()
    
    conn.close()
    logger.info("✅ БД готова")

init_db()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def generate_slots(work_start, work_end):
    slots = []
    start = datetime.strptime(work_start, "%H:%M")
    end = datetime.strptime(work_end, "%H:%M")
    current = start
    while current < end:
        slots.append(current.strftime("%H:%M"))
        current += timedelta(minutes=30)
    return slots

async def notify_master(token, tg_id, msg):
    if not token or not tg_id: return
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            await client.post(f"https://api.telegram.org/bot{token}/sendMessage",
                            json={"chat_id": tg_id, "text": msg, "parse_mode": "Markdown"})
    except: pass

def confirm_booking(booking_id, conn):
    conn.execute("UPDATE bookings SET status='confirmed', payment_status='paid', confirmed_at=CURRENT_TIMESTAMP WHERE id=?", (booking_id,))
    booking = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
    master = conn.execute("SELECT * FROM masters WHERE id=?", (booking["master_id"],)).fetchone()
    service = conn.execute("SELECT * FROM services WHERE id=?", (booking["service_id"],)).fetchone()
    token = secrets.token_urlsafe(16)
    conn.execute("INSERT OR IGNORE INTO chats (booking_id, master_id, client_telegram_id, master_telegram_id, token) VALUES (?,?,?,?,?)",
                (booking_id, master["id"], booking["client_telegram_id"], master["telegram_id"], token))
    conn.commit()
    
    asyncio.create_task(notify_master(master["bot_token"], master["telegram_id"],
        f"✅ *Запись подтверждена!*\n👩 {booking['client_name']}\n💅 {service['name']}\n💰 {service['price']} ₽\n📅 {booking['date']} в {booking['time']}"))
    logger.info(f"✅ Бронирование {booking_id} подтверждено")

# ========== ГЛАВНАЯ ФУНКЦИЯ - ВСЕГДА ВОЗВРАЩАЕТ ЯНДЕКС ==========
async def create_payment(amount: float, booking_id: int) -> dict:
    """Всегда возвращает Яндекс для теста"""
    logger.info(f"💳 Создан платёж на {amount}₽ для брони {booking_id}")
    return {
        "confirmation_url": "https://yandex.ru",
        "payment_id": f"test_{booking_id}"
    }

# ========== ЭНДПОИНТЫ ==========

@app.get("/masters")
def get_masters(conn=Depends(get_db)):
    masters = conn.execute("SELECT * FROM masters").fetchall()
    result = []
    for m in masters:
        completed = conn.execute("SELECT COUNT(*) FROM bookings WHERE master_id=? AND status='confirmed'", (m["id"],)).fetchone()[0]
        services = conn.execute("SELECT * FROM services WHERE master_id=?", (m["id"],)).fetchall()
        d = dict(m)
        d["services"] = [dict(s) for s in services]
        d["completed_bookings"] = completed
        d["photos"] = []
        result.append(d)
    return result

@app.get("/masters/{master_id}")
def get_master(master_id: int, conn=Depends(get_db)):
    m = conn.execute("SELECT * FROM masters WHERE id=?", (master_id,)).fetchone()
    if not m:
        raise HTTPException(404, "Master not found")
    completed = conn.execute("SELECT COUNT(*) FROM bookings WHERE master_id=? AND status='confirmed'", (master_id,)).fetchone()[0]
    services = conn.execute("SELECT * FROM services WHERE master_id=?", (master_id,)).fetchall()
    d = dict(m)
    d["services"] = [dict(s) for s in services]
    d["completed_bookings"] = completed
    d["photos"] = []
    return d

@app.get("/masters/by_telegram/{telegram_id}")
def get_master_by_telegram(telegram_id: str, conn=Depends(get_db)):
    m = conn.execute("SELECT * FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not m:
        raise HTTPException(404, "Master not found")
    return dict(m)

@app.patch("/master/{telegram_id}/location")
def update_location(telegram_id: str, data: LocationUpdate, conn=Depends(get_db)):
    conn.execute("UPDATE masters SET lat=?, lon=? WHERE telegram_id=?", (data.lat, data.lon, telegram_id))
    conn.commit()
    return {"status": "ok"}

@app.patch("/master/{telegram_id}/work-hours")
def update_work_hours(telegram_id: str, data: WorkHoursUpdate, conn=Depends(get_db)):
    conn.execute("UPDATE masters SET work_start=?, work_end=? WHERE telegram_id=?", (data.work_start, data.work_end, telegram_id))
    conn.commit()
    return {"status": "ok"}

@app.get("/masters/{master_id}/slots")
def get_slots(master_id: int, date: str, conn=Depends(get_db)):
    master = conn.execute("SELECT * FROM masters WHERE id=?", (master_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    
    day_off = conn.execute("SELECT id FROM days_off WHERE master_id=? AND date=?", (master_id, date)).fetchone()
    if day_off:
        return {"date": date, "slots": [], "day_off": True}
    
    work_start = master["work_start"] or "09:00"
    work_end = master["work_end"] or "20:00"
    all_slots = generate_slots(work_start, work_end)
    
    booked = conn.execute("SELECT time FROM bookings WHERE master_id=? AND date=? AND status IN ('pending_payment', 'confirmed')", (master_id, date)).fetchall()
    booked_times = {b["time"] for b in booked}
    
    today = datetime.now().strftime("%Y-%m-%d")
    now_time = datetime.now().strftime("%H:%M")
    free = [s for s in all_slots if s not in booked_times and not (date == today and s <= now_time)]
    return {"date": date, "slots": free, "day_off": False}

@app.post("/masters/{master_id}/days_off")
def add_day_off(master_id: int, data: DayOffRequest, conn=Depends(get_db)):
    conn.execute("INSERT OR IGNORE INTO days_off (master_id, date) VALUES (?,?)", (master_id, data.date))
    conn.commit()
    return {"status": "ok"}

@app.delete("/masters/{master_id}/days_off/{date}")
def remove_day_off(master_id: int, date: str, conn=Depends(get_db)):
    conn.execute("DELETE FROM days_off WHERE master_id=? AND date=?", (master_id, date))
    conn.commit()
    return {"status": "ok"}

@app.get("/master/{telegram_id}/services")
def get_services(telegram_id: str, conn=Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    services = conn.execute("SELECT * FROM services WHERE master_id=?", (master["id"],)).fetchall()
    return [dict(s) for s in services]

@app.post("/master/{telegram_id}/services")
def add_service(telegram_id: str, data: ServiceIn, conn=Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    cur = conn.execute("INSERT INTO services (master_id, name, price, duration_min) VALUES (?,?,?,?)",
                      (master["id"], data.name, data.price, data.duration_min))
    conn.commit()
    return {"status": "ok", "service_id": cur.lastrowid}

@app.delete("/master/{telegram_id}/services/{service_id}")
def delete_service(telegram_id: str, service_id: int, conn=Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    conn.execute("DELETE FROM services WHERE id=? AND master_id=?", (service_id, master["id"]))
    conn.commit()
    return {"status": "ok"}

# ========== ОСНОВНОЙ ЭНДПОИНТ ЗАПИСИ ==========

@app.post("/bookings")
async def create_booking(data: BookingIn):
    conn = get_db()
    try:
        master = conn.execute("SELECT * FROM masters WHERE id=?", (data.master_id,)).fetchone()
        if not master:
            raise HTTPException(404, "Master not found")
        
        service = conn.execute("SELECT * FROM services WHERE id=? AND master_id=?", (data.service_id, data.master_id)).fetchone()
        if not service:
            raise HTTPException(404, "Service not found")
        
        day_off = conn.execute("SELECT id FROM days_off WHERE master_id=? AND date=?", (data.master_id, data.date)).fetchone()
        if day_off:
            raise HTTPException(409, "Master is off")
        
        existing = conn.execute("SELECT id FROM bookings WHERE master_id=? AND date=? AND time=? AND status IN ('pending_payment', 'confirmed')", 
                               (data.master_id, data.date, data.time)).fetchone()
        if existing:
            raise HTTPException(409, "Slot already booked")
        
        deposit_amount = round(service["price"] * PAYMENT_COMMISSION, 2)
        
        cur = conn.execute("""
            INSERT INTO bookings (master_id, service_id, client_name, client_telegram_id, client_phone, date, time, status, deposit_amount)
            VALUES (?,?,?,?,?,?,?, 'pending_payment', ?)
        """, (data.master_id, data.service_id, data.client_name, data.client_telegram_id, data.client_phone, data.date, data.time, deposit_amount))
        conn.commit()
        booking_id = cur.lastrowid
        
        logger.info(f"📝 Бронь {booking_id}: {data.client_name} -> {service['name']} на {data.date} {data.time}")
        
        # СОЗДАЁМ ПЛАТЁЖ (ВСЕГДА ВОЗВРАЩАЕТ ЯНДЕКС)
        payment = await create_payment(deposit_amount, booking_id)
        
        conn.execute("UPDATE bookings SET payment_id=? WHERE id=?", (payment["payment_id"], booking_id))
        conn.commit()
        
        # Уведомление мастеру
        await notify_master(master["bot_token"], master["telegram_id"],
            f"💳 *Новая заявка*\n👩 {data.client_name}\n💅 {service['name']}\n💰 {service['price']} ₽ (депозит {deposit_amount}₽)\n📅 {data.date} в {data.time}")
        
        return {
            "booking_id": booking_id,
            "payment_url": payment["confirmation_url"],
            "deposit_amount": deposit_amount,
            "total_price": service["price"],
            "status": "pending_payment"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        raise HTTPException(500, detail=str(e))
    finally:
        conn.close()

# ========== ОСТАЛЬНЫЕ ЭНДПОИНТЫ ==========

@app.get("/bookings/client/{telegram_id}")
def get_client_bookings(telegram_id: str, conn=Depends(get_db)):
    bookings = conn.execute("""
        SELECT b.*, m.name as master_name, s.name as service_name, s.price
        FROM bookings b JOIN masters m ON b.master_id=m.id JOIN services s ON b.service_id=s.id
        WHERE b.client_telegram_id=? ORDER BY b.date DESC, b.time DESC
    """, (telegram_id,)).fetchall()
    return [dict(b) for b in bookings]

@app.get("/master/{telegram_id}/bookings")
def get_master_bookings(telegram_id: str, conn=Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    bookings = conn.execute("""
        SELECT b.*, s.name as service_name, s.price
        FROM bookings b JOIN services s ON b.service_id=s.id
        WHERE b.master_id=? ORDER BY b.date DESC, b.time DESC
    """, (master["id"],)).fetchall()
    return [dict(b) for b in bookings]

@app.get("/master/{telegram_id}/stats")
def get_stats(telegram_id: str, conn=Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    confirmed = conn.execute("SELECT COUNT(*) FROM bookings WHERE master_id=? AND status='confirmed'", (master["id"],)).fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM bookings WHERE master_id=? AND status='pending_payment'", (master["id"],)).fetchone()[0]
    revenue = conn.execute("SELECT SUM(s.price) FROM bookings b JOIN services s ON b.service_id=s.id WHERE b.master_id=? AND b.status='confirmed'", (master["id"],)).fetchone()[0] or 0
    return {"completed_bookings": confirmed, "pending_payment": pending, "revenue": revenue, "total": confirmed + pending}

@app.post("/chat/send")
def send_message(data: MessageIn, conn=Depends(get_db)):
    booking = conn.execute("SELECT status FROM bookings WHERE id=?", (data.booking_id,)).fetchone()
    if not booking or booking["status"] != "confirmed":
        raise HTTPException(403, "Chat available only after payment")
    conn.execute("INSERT INTO chat_messages (booking_id, from_id, to_id, message) VALUES (?,?,?,?)",
                (data.booking_id, data.from_id, data.to_id, data.message))
    conn.commit()
    return {"status": "ok"}

@app.get("/chat/messages/{booking_id}")
def get_messages(booking_id: int, user_id: str, conn=Depends(get_db)):
    booking = conn.execute("SELECT b.client_telegram_id, m.telegram_id as master_telegram_id FROM bookings b LEFT JOIN masters m ON b.master_id=m.id WHERE b.id=?", (booking_id,)).fetchone()
    if not booking or (user_id != booking["client_telegram_id"] and user_id != booking["master_telegram_id"]):
        return []
    messages = conn.execute("SELECT * FROM chat_messages WHERE booking_id=? ORDER BY created_at ASC", (booking_id,)).fetchall()
    return [dict(m) for m in messages]

@app.post("/reviews")
def create_review(data: ReviewIn, conn=Depends(get_db)):
    existing = conn.execute("SELECT id FROM reviews WHERE booking_id=?", (data.booking_id,)).fetchone()
    if existing:
        raise HTTPException(400, "Review already exists")
    conn.execute("INSERT INTO reviews (master_id, booking_id, client_name, rating, comment) VALUES (?,?,?,?,?)",
                (data.master_id, data.booking_id, data.client_name, data.rating, data.comment))
    conn.commit()
    conn.execute("UPDATE masters SET rating = (SELECT AVG(rating) FROM reviews WHERE master_id=?) WHERE id=?", (data.master_id, data.master_id))
    conn.commit()
    return {"status": "ok"}

@app.get("/reviews/master/{master_id}")
def get_reviews(master_id: int, conn=Depends(get_db)):
    reviews = conn.execute("SELECT * FROM reviews WHERE master_id=? ORDER BY created_at DESC", (master_id,)).fetchall()
    return [dict(r) for r in reviews]

@app.post("/user/register")
def register_user(data: UserRegister, conn=Depends(get_db)):
    conn.execute("INSERT OR IGNORE INTO users (telegram_id) VALUES (?)", (data.telegram_id,))
    conn.commit()
    return {"status": "ok"}

@app.get("/payment-status/{booking_id}")
def payment_status(booking_id: int, conn=Depends(get_db)):
    booking = conn.execute("SELECT status, payment_status, deposit_amount FROM bookings WHERE id=?", (booking_id,)).fetchone()
    if not booking:
        raise HTTPException(404, "Booking not found")
    return dict(booking)

@app.post("/ykassa-webhook")
async def ykassa_webhook(notification: dict):
    logger.info(f"Webhook: {notification}")
    return {"status": "ok"}

@app.get("/")
def root():
    return {"status": "Beauty Bot API running 🌸", "version": "3.0.0", "test_mode": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
