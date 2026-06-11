from fastapi import FastAPI, HTTPException, Depends, Request, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List
import sqlite3
import httpx
import secrets
import uuid
import base64
from datetime import datetime, timedelta
import asyncio
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Beauty Bot API")

# === КОНФИГ ===
YKASSA_SHOP_ID = os.getenv("YKASSA_SHOP_ID", "1368786")
YKASSA_SECRET_KEY = os.getenv("YKASSA_SECRET_KEY", "live_aRHBYSr1irUAO8_dvzZCmQCih-vTF0q0NFfSvW5OOcs")
YKASSA_RETURN_URL = os.getenv("YKASSA_RETURN_URL", "https://t.me/pinkspotvelur_bot")
PAYMENT_COMMISSION = 0.07
CLEANING_TIME = 15
MASTER_BOT_TOKEN = os.getenv("MASTER_BOT_TOKEN", "8236516081:AAFjIjQBiAMs95XpURSCZZhuuYr5yDrcmlw")

DB_PATH = "beauty.db"

# === CORS ===
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========== БД ==========
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Masters
    c.execute("""CREATE TABLE IF NOT EXISTS masters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id TEXT UNIQUE,
        name TEXT DEFAULT '',
        address TEXT DEFAULT '',
        lat REAL DEFAULT 55.751244,
        lon REAL DEFAULT 37.618423,
        phone TEXT DEFAULT '',
        instagram TEXT DEFAULT '',
        work_start TEXT DEFAULT '09:00',
        work_end TEXT DEFAULT '20:00',
        bot_token TEXT DEFAULT '',
        description TEXT DEFAULT '',
        icon TEXT DEFAULT '💅',
        rating REAL DEFAULT 0
    )""")
    
    # Services
    c.execute("""CREATE TABLE IF NOT EXISTS services (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        master_id INTEGER,
        name TEXT,
        price INTEGER,
        duration_min INTEGER
    )""")
    
    # Bookings
    c.execute("""CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        master_id INTEGER,
        service_id INTEGER,
        client_name TEXT,
        client_telegram_id TEXT,
        client_phone TEXT,
        date TEXT,
        time TEXT,
        status TEXT DEFAULT 'pending_payment',
        deposit_amount REAL DEFAULT 0,
        payment_id TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        confirmed_at TEXT,
        cancelled_at TEXT
    )""")
    
    # Days off
    c.execute("""CREATE TABLE IF NOT EXISTS days_off (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        master_id INTEGER,
        date TEXT,
        UNIQUE(master_id, date)
    )""")
    
    # Chats
    c.execute("""CREATE TABLE IF NOT EXISTS chats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        booking_id INTEGER UNIQUE,
        master_id INTEGER,
        client_telegram_id TEXT,
        master_telegram_id TEXT,
        token TEXT UNIQUE
    )""")
    
    # Messages
    c.execute("""CREATE TABLE IF NOT EXISTS chat_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        booking_id INTEGER,
        from_id TEXT,
        to_id TEXT,
        message TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    
    # Favorites
    c.execute("""CREATE TABLE IF NOT EXISTS favorites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_telegram_id TEXT,
        master_id INTEGER,
        UNIQUE(client_telegram_id, master_id)
    )""")
    
    # Quick replies
    c.execute("""CREATE TABLE IF NOT EXISTS quick_replies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        master_id INTEGER,
        title TEXT,
        message TEXT
    )""")
    
    # Portfolio
    c.execute("""CREATE TABLE IF NOT EXISTS portfolio (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        master_id INTEGER,
        photo_url TEXT,
        description TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    
    # Тестовый мастер (Алина Козлова)
    c.execute("SELECT COUNT(*) FROM masters WHERE telegram_id = '868528632'")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO masters (telegram_id, name, address, lat, lon, phone, instagram, icon, work_start, work_end, bot_token, description) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  ("868528632", "Алина Козлова", "ул. Ленина, 12", 47.222078, 39.720358, "+79001234567", "@alina_nails", "💅", "09:00", "20:00", MASTER_BOT_TOKEN, "Мастер маникюра с 5-летним опытом"))
        c.execute("SELECT id FROM masters WHERE telegram_id = '868528632'")
        master_id = c.fetchone()[0]
        c.execute("INSERT INTO services (master_id, name, price, duration_min) VALUES (?,?,?,?)", (master_id, "Маникюр классический", 1200, 60))
        c.execute("INSERT INTO services (master_id, name, price, duration_min) VALUES (?,?,?,?)", (master_id, "Маникюр с покрытием", 2000, 90))
        c.execute("INSERT INTO services (master_id, name, price, duration_min) VALUES (?,?,?,?)", (master_id, "Педикюр", 2500, 120))
    
    conn.commit()
    conn.close()
    logger.info("✅ БД готова")

init_db()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def time_to_minutes(t):
    h, m = map(int, t.split(':'))
    return h * 60 + m

def minutes_to_time(m):
    return f"{m//60:02d}:{m%60:02d}"

def generate_slots(work_start, work_end, booked_slots, service_duration, cleaning_time=15):
    start = time_to_minutes(work_start)
    end = time_to_minutes(work_end)
    interval = 30
    
    occupied = []
    for slot in booked_slots:
        s = time_to_minutes(slot['time'])
        e = s + slot.get('duration_min', 60) + cleaning_time
        occupied.append((s, e))
    occupied.sort()
    
    merged = []
    for o in occupied:
        if not merged or merged[-1][1] < o[0]:
            merged.append(list(o))
        else:
            merged[-1][1] = max(merged[-1][1], o[1])
    
    free = []
    current = start
    for o_start, o_end in merged:
        while current + service_duration <= o_start:
            free.append(minutes_to_time(current))
            current += interval
        current = max(current, o_end)
    
    while current + service_duration <= end:
        free.append(minutes_to_time(current))
        current += interval
    
    return free

async def send_tg(chat_id, msg):
    try:
        async with httpx.AsyncClient() as client:
            await client.post(f"https://api.telegram.org/bot{MASTER_BOT_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"})
    except Exception as e:
        logger.error(f"Ошибка отправки: {e}")

def confirm_booking(booking_id, conn):
    conn.execute("UPDATE bookings SET status='confirmed', confirmed_at=CURRENT_TIMESTAMP WHERE id=?", (booking_id,))
    conn.commit()
    
    b = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
    m = conn.execute("SELECT * FROM masters WHERE id=?", (b["master_id"],)).fetchone()
    s = conn.execute("SELECT * FROM services WHERE id=?", (b["service_id"],)).fetchone()
    
    token = secrets.token_urlsafe(16)
    conn.execute("INSERT OR IGNORE INTO chats (booking_id, master_id, client_telegram_id, master_telegram_id, token) VALUES (?,?,?,?,?)",
                (booking_id, m["id"], b["client_telegram_id"], m["telegram_id"], token))
    conn.commit()
    
    asyncio.create_task(send_tg(m["telegram_id"], f"🌸 *НОВАЯ ЗАПИСЬ ПОДТВЕРЖДЕНА!* 🌸\n\n👩 {b['client_name']}\n💅 {s['name']}\n💰 {s['price']} ₽\n📅 {b['date']} в {b['time']}"))
    asyncio.create_task(send_tg(b["client_telegram_id"], f"🌸 *ЗАПИСЬ ПОДТВЕРЖДЕНА!* 🌸\n\n💅 {m['name']}\n📍 {m['address']}\n💅 {s['name']}\n💰 {s['price']} ₽\n💸 Оплачено: {b['deposit_amount']} ₽\n💎 Остаток: {s['price']} ₽\n📅 {b['date']} в {b['time']}"))

async def create_payment(amount, description, return_url, booking_id):
    if not YKASSA_SHOP_ID or not YKASSA_SECRET_KEY:
        return {"confirmation_url": "https://yandex.ru", "payment_id": f"test_{booking_id}"}
    
    auth = base64.b64encode(f"{YKASSA_SHOP_ID}:{YKASSA_SECRET_KEY}".encode()).decode()
    data = {
        "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
        "confirmation": {"type": "redirect", "return_url": return_url},
        "description": description[:120],
        "capture": True,
        "metadata": {"booking_id": str(booking_id)}
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post("https://api.yookassa.ru/v3/payments", json=data, headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json", "Idempotence-Key": str(uuid.uuid4())})
            if r.status_code == 200:
                d = r.json()
                return {"confirmation_url": d["confirmation"]["confirmation_url"], "payment_id": d["id"]}
    except:
        pass
    return {"confirmation_url": "https://yandex.ru", "payment_id": f"error_{booking_id}"}

# ========== ЭНДПОИНТЫ ДЛЯ КЛИЕНТОВ ==========

@app.get("/masters")
def get_masters(conn=Depends(get_db)):
    masters = conn.execute("SELECT * FROM masters WHERE name != '' AND address != ''").fetchall()
    result = []
    for m in masters:
        services = conn.execute("SELECT * FROM services WHERE master_id=?", (m["id"],)).fetchall()
        d = dict(m)
        d["services"] = [dict(s) for s in services]
        result.append(d)
    return result

@app.get("/masters/{master_id}")
def get_master(master_id: int, conn=Depends(get_db)):
    m = conn.execute("SELECT * FROM masters WHERE id=?", (master_id,)).fetchone()
    if not m:
        raise HTTPException(404, "Master not found")
    services = conn.execute("SELECT * FROM services WHERE master_id=?", (master_id,)).fetchall()
    portfolio = conn.execute("SELECT * FROM portfolio WHERE master_id=?", (master_id,)).fetchall()
    d = dict(m)
    d["services"] = [dict(s) for s in services]
    d["portfolio"] = [dict(p) for p in portfolio]
    return d

@app.get("/masters/by_telegram/{telegram_id}")
def get_master_by_tg(telegram_id: str, conn=Depends(get_db)):
    m = conn.execute("SELECT * FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not m:
        raise HTTPException(404, "Master not found")
    return dict(m)

@app.get("/masters/{master_id}/slots")
def get_slots(master_id: int, date: str, service_id: int, conn=Depends(get_db)):
    master = conn.execute("SELECT * FROM masters WHERE id=?", (master_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    
    service = conn.execute("SELECT duration_min FROM services WHERE id=? AND master_id=?", (service_id, master_id)).fetchone()
    if not service:
        raise HTTPException(404, "Service not found")
    
    day_off = conn.execute("SELECT id FROM days_off WHERE master_id=? AND date=?", (master_id, date)).fetchone()
    if day_off:
        return {"date": date, "slots": [], "day_off": True}
    
    booked = conn.execute("""
        SELECT b.time, s.duration_min FROM bookings b 
        JOIN services s ON b.service_id = s.id 
        WHERE b.master_id=? AND b.date=? AND b.status IN ('pending_payment', 'confirmed')
    """, (master_id, date)).fetchall()
    
    free = generate_slots(master["work_start"], master["work_end"], [dict(b) for b in booked], service["duration_min"], CLEANING_TIME)
    
    today = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now().strftime("%H:%M")
    if date == today:
        free = [s for s in free if time_to_minutes(s) > time_to_minutes(now)]
    
    return {"date": date, "slots": free, "day_off": False}

@app.post("/bookings")
async def create_booking(data: dict, conn=Depends(get_db)):
    try:
        master = conn.execute("SELECT * FROM masters WHERE id=?", (data.get("master_id"),)).fetchone()
        if not master:
            raise HTTPException(404, "Master not found")
        
        service = conn.execute("SELECT * FROM services WHERE id=? AND master_id=?", (data.get("service_id"), data.get("master_id"))).fetchone()
        if not service:
            raise HTTPException(404, "Service not found")
        
        existing = conn.execute("SELECT id FROM bookings WHERE master_id=? AND date=? AND time=? AND status IN ('pending_payment', 'confirmed')",
                               (data.get("master_id"), data.get("date"), data.get("time"))).fetchone()
        if existing:
            raise HTTPException(409, "Slot already booked")
        
        deposit = round(service["price"] * PAYMENT_COMMISSION, 2)
        
        cur = conn.execute("""
            INSERT INTO bookings (master_id, service_id, client_name, client_telegram_id, client_phone, date, time, deposit_amount)
            VALUES (?,?,?,?,?,?,?,?)
        """, (data.get("master_id"), data.get("service_id"), data.get("client_name"), data.get("client_telegram_id"), data.get("client_phone"), data.get("date"), data.get("time"), deposit))
        conn.commit()
        booking_id = cur.lastrowid
        
        payment = await create_payment(deposit, f"Бронь {service['name']}", f"{YKASSA_RETURN_URL}?booking_id={booking_id}", booking_id)
        
        conn.execute("UPDATE bookings SET payment_id=? WHERE id=?", (payment["payment_id"], booking_id))
        conn.commit()
        
        await send_tg(master["telegram_id"], f"💳 *НОВАЯ ЗАЯВКА*\n\n👩 {data.get('client_name')}\n💅 {service['name']}\n💰 {service['price']} ₽\n📅 {data.get('date')} в {data.get('time')}")
        
        return {
            "booking_id": booking_id,
            "payment_url": payment["confirmation_url"],
            "deposit_amount": deposit,
            "service_price": service["price"],
            "status": "pending_payment"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        raise HTTPException(500, str(e))

@app.post("/ykassa-webhook")
async def webhook(notification: dict, conn=Depends(get_db)):
    if notification.get("type") == "notification":
        payment_id = notification.get("object", {}).get("id")
        if notification.get("object", {}).get("status") == "succeeded":
            booking = conn.execute("SELECT id FROM bookings WHERE payment_id=?", (payment_id,)).fetchone()
            if booking:
                confirm_booking(booking["id"], conn)
    return {"status": "ok"}

@app.patch("/bookings/{booking_id}/status")
def cancel_booking(booking_id: int, status: str, conn=Depends(get_db)):
    booking = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
    if not booking:
        raise HTTPException(404, "Booking not found")
    conn.execute("UPDATE bookings SET status=?, cancelled_at=CURRENT_TIMESTAMP WHERE id=?", (status, booking_id))
    conn.commit()
    return {"status": "ok"}

@app.get("/bookings/client/{telegram_id}")
def client_bookings(telegram_id: str, conn=Depends(get_db)):
    bookings = conn.execute("""
        SELECT b.*, m.name as master_name, s.name as service_name, s.price
        FROM bookings b JOIN masters m ON b.master_id=m.id JOIN services s ON b.service_id=s.id
        WHERE b.client_telegram_id=? ORDER BY b.date DESC, b.time DESC
    """, (telegram_id,)).fetchall()
    return [dict(b) for b in bookings]

@app.get("/master/{telegram_id}/bookings")
def master_bookings(telegram_id: str, conn=Depends(get_db)):
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
def master_stats(telegram_id: str, conn=Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    confirmed = conn.execute("SELECT COUNT(*) FROM bookings WHERE master_id=? AND status='confirmed'", (master["id"],)).fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM bookings WHERE master_id=? AND status='pending_payment'", (master["id"],)).fetchone()[0]
    revenue = conn.execute("SELECT SUM(price) FROM bookings b JOIN services s ON b.service_id=s.id WHERE b.master_id=? AND b.status='confirmed'", (master["id"],)).fetchone()[0] or 0
    return {"confirmed": confirmed, "pending": pending, "revenue": revenue}

# ========== ПРОФИЛЬ МАСТЕРА ==========
@app.patch("/master/{telegram_id}/profile")
def update_profile(telegram_id: str, data: dict, conn=Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    
    for key in ['name', 'address', 'phone', 'instagram', 'description', 'work_start', 'work_end', 'lat', 'lon']:
        if key in data and data[key]:
            conn.execute(f"UPDATE masters SET {key}=? WHERE id=?", (data[key], master["id"]))
    conn.commit()
    return {"status": "ok"}

@app.get("/master/{telegram_id}/profile")
def get_profile(telegram_id: str, conn=Depends(get_db)):
    master = conn.execute("SELECT * FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    return dict(master)

@app.patch("/master/{telegram_id}/location")
def update_location(telegram_id: str, data: dict, conn=Depends(get_db)):
    conn.execute("UPDATE masters SET lat=?, lon=? WHERE telegram_id=?", (data.get("lat"), data.get("lon"), telegram_id))
    conn.commit()
    return {"status": "ok"}

@app.patch("/master/{telegram_id}/work-hours")
def update_hours(telegram_id: str, data: dict, conn=Depends(get_db)):
    conn.execute("UPDATE masters SET work_start=?, work_end=? WHERE telegram_id=?", (data.get("work_start"), data.get("work_end"), telegram_id))
    conn.commit()
    return {"status": "ok"}

# ========== УСЛУГИ ==========
@app.post("/master/{telegram_id}/services")
def add_service(telegram_id: str, data: dict, conn=Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    conn.execute("INSERT INTO services (master_id, name, price, duration_min) VALUES (?,?,?,?)",
                (master["id"], data["name"], data["price"], data["duration_min"]))
    conn.commit()
    return {"status": "ok"}

@app.delete("/master/{telegram_id}/services/{service_id}")
def delete_service(telegram_id: str, service_id: int, conn=Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    conn.execute("DELETE FROM services WHERE id=? AND master_id=?", (service_id, master["id"]))
    conn.commit()
    return {"status": "ok"}

@app.get("/master/{telegram_id}/services")
def get_services(telegram_id: str, conn=Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    services = conn.execute("SELECT * FROM services WHERE master_id=?", (master["id"],)).fetchall()
    return [dict(s) for s in services]

# ========== БЫСТРЫЕ ОТВЕТЫ ==========
@app.post("/master/{telegram_id}/quick-replies")
def add_reply(telegram_id: str, data: dict, conn=Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    conn.execute("INSERT INTO quick_replies (master_id, title, message) VALUES (?,?,?)",
                (master["id"], data["title"], data["message"]))
    conn.commit()
    return {"status": "ok"}

@app.get("/master/{telegram_id}/quick-replies")
def get_replies(telegram_id: str, conn=Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    replies = conn.execute("SELECT * FROM quick_replies WHERE master_id=?", (master["id"],)).fetchall()
    return [dict(r) for r in replies]

@app.delete("/master/{telegram_id}/quick-replies/{reply_id}")
def delete_reply(telegram_id: str, reply_id: int, conn=Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    conn.execute("DELETE FROM quick_replies WHERE id=? AND master_id=?", (reply_id, master["id"]))
    conn.commit()
    return {"status": "ok"}

# ========== ПОРТФОЛИО ==========
@app.post("/master/{telegram_id}/portfolio")
def add_photo(telegram_id: str, photo_url: str = Form(...), description: str = Form(""), conn=Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    conn.execute("INSERT INTO portfolio (master_id, photo_url, description) VALUES (?,?,?)",
                (master["id"], photo_url, description))
    conn.commit()
    return {"status": "ok"}

@app.delete("/master/{telegram_id}/portfolio/{photo_id}")
def delete_photo(telegram_id: str, photo_id: int, conn=Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    conn.execute("DELETE FROM portfolio WHERE id=? AND master_id=?", (photo_id, master["id"]))
    conn.commit()
    return {"status": "ok"}

# ========== ИЗБРАННОЕ ==========
@app.post("/favorites/{master_id}")
def add_favorite(master_id: int, client_telegram_id: str, conn=Depends(get_db)):
    conn.execute("INSERT OR IGNORE INTO favorites (client_telegram_id, master_id) VALUES (?,?)", (client_telegram_id, master_id))
    conn.commit()
    return {"status": "ok"}

@app.delete("/favorites/{master_id}")
def remove_favorite(master_id: int, client_telegram_id: str, conn=Depends(get_db)):
    conn.execute("DELETE FROM favorites WHERE client_telegram_id=? AND master_id=?", (client_telegram_id, master_id))
    conn.commit()
    return {"status": "ok"}

@app.get("/favorites/{client_telegram_id}")
def get_favorites(client_telegram_id: str, conn=Depends(get_db)):
    favorites = conn.execute("""
        SELECT m.* FROM masters m
        JOIN favorites f ON m.id = f.master_id
        WHERE f.client_telegram_id = ? AND m.name != '' AND m.address != ''
    """, (client_telegram_id,)).fetchall()
    return [dict(f) for f in favorites]

# ========== ДНИ ОТДЫХА ==========
@app.post("/masters/{master_id}/days_off")
def add_day_off(master_id: int, date: str, conn=Depends(get_db)):
    conn.execute("INSERT OR IGNORE INTO days_off (master_id, date) VALUES (?,?)", (master_id, date))
    conn.commit()
    return {"status": "ok"}

@app.delete("/masters/{master_id}/days_off/{date}")
def remove_day_off(master_id: int, date: str, conn=Depends(get_db)):
    conn.execute("DELETE FROM days_off WHERE master_id=? AND date=?", (master_id, date))
    conn.commit()
    return {"status": "ok"}

# ========== ПОЛЬЗОВАТЕЛИ ==========
@app.post("/user/register")
def register_user(data: dict, conn=Depends(get_db)):
    conn.execute("INSERT OR IGNORE INTO users (telegram_id) VALUES (?)", (data.get("telegram_id"),))
    conn.commit()
    return {"status": "ok"}

# ========== ЧАТ ==========
@app.post("/chat/send")
def send_message(data: dict, conn=Depends(get_db)):
    booking = conn.execute("SELECT status FROM bookings WHERE id=?", (data.get("booking_id"),)).fetchone()
    if not booking or booking["status"] != "confirmed":
        raise HTTPException(403, "Chat available only after payment")
    conn.execute("INSERT INTO chat_messages (booking_id, from_id, to_id, message) VALUES (?,?,?,?)",
                (data.get("booking_id"), data.get("from_id"), data.get("to_id"), data.get("message")))
    conn.commit()
    return {"status": "ok"}

@app.get("/chat/messages/{booking_id}")
def get_messages(booking_id: int, user_id: str, conn=Depends(get_db)):
    messages = conn.execute("SELECT * FROM chat_messages WHERE booking_id=? ORDER BY created_at ASC", (booking_id,)).fetchall()
    return [dict(m) for m in messages]

# ========== АДМИН-ПАНЕЛЬ (ТОЛЬКО TELEGRAM ID) ==========
@app.post("/admin/add-master")
def admin_add_master(data: dict, conn=Depends(get_db)):
    """Добавление мастера - только Telegram ID"""
    tg_id = data.get("telegram_id", "").strip()
    if not tg_id:
        raise HTTPException(400, "Telegram ID обязателен")
    
    existing = conn.execute("SELECT id FROM masters WHERE telegram_id = ?", (tg_id,)).fetchone()
    if existing:
        raise HTTPException(400, f"Мастер с Telegram ID {tg_id} уже существует")
    
    conn.execute("""
        INSERT INTO masters (telegram_id, name, address, lat, lon, phone, instagram, description, icon, work_start, work_end, bot_token)
        VALUES (?, 'Новый мастер', '', 55.751244, 37.618423, '', '', '', '💅', '09:00', '20:00', '')
    """, (tg_id,))
    conn.commit()
    
    master_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    return {"status": "ok", "master_id": master_id, "telegram_id": tg_id, "message": f"Мастер с Telegram ID {tg_id} добавлен"}

@app.get("/admin/masters")
def admin_get_masters(conn=Depends(get_db)):
    """Список всех мастеров"""
    masters = conn.execute("""
        SELECT id, telegram_id, name, phone, icon,
               CASE WHEN name = 'Новый мастер' OR name = '' THEN 'Не заполнен' ELSE 'Заполнен' END as status
        FROM masters ORDER BY id DESC
    """).fetchall()
    return [dict(m) for m in masters]

@app.delete("/admin/delete-master/{master_id}")
def admin_delete_master(master_id: int, conn=Depends(get_db)):
    """Удаление мастера"""
    master = conn.execute("SELECT id, name FROM masters WHERE id = ?", (master_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    
    conn.execute("DELETE FROM services WHERE master_id = ?", (master_id,))
    conn.execute("DELETE FROM bookings WHERE master_id = ?", (master_id,))
    conn.execute("DELETE FROM days_off WHERE master_id = ?", (master_id,))
    conn.execute("DELETE FROM quick_replies WHERE master_id = ?", (master_id,))
    conn.execute("DELETE FROM portfolio WHERE master_id = ?", (master_id,))
    conn.execute("DELETE FROM favorites WHERE master_id = ?", (master_id,))
    conn.execute("DELETE FROM masters WHERE id = ?", (master_id,))
    conn.commit()
    return {"status": "ok", "message": "Мастер удалён"}

@app.get("/admin/stats")
def admin_get_stats(conn=Depends(get_db)):
    """Статистика"""
    masters = conn.execute("SELECT COUNT(*) FROM masters").fetchone()[0]
    bookings = conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
    confirmed = conn.execute("SELECT COUNT(*) FROM bookings WHERE status='confirmed'").fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM bookings WHERE status='pending_payment'").fetchone()[0]
    revenue = conn.execute("SELECT SUM(price) FROM bookings b JOIN services s ON b.service_id=s.id WHERE b.status='confirmed'").fetchone()[0] or 0
    return {"masters": masters, "total_bookings": bookings, "confirmed": confirmed, "pending": pending, "revenue": revenue}

# ========== ЗАПУСК ==========
@app.get("/")
def root():
    return {"status": "Beauty Bot API running 🌸", "version": "3.0.0"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
