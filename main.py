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
import os
import asyncio
import logging
import hashlib
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Beauty Bot API")

# === КОНФИГУРАЦИЯ ===
YKASSA_SHOP_ID = os.getenv("YKASSA_SHOP_ID", "1368786")
YKASSA_SECRET_KEY = os.getenv("YKASSA_SECRET_KEY", "live_aRHBYSr1irUAO8_dvzZCmQCih-vTF0q0NFfSvW5OOcs")
YKASSA_RETURN_URL = os.getenv("YKASSA_RETURN_URL", "https://t.me/pinkspotvelur_bot")
PAYMENT_COMMISSION = 0.07  # 7% депозит
CASHBACK_PERCENT = 0.07    # 7% кэшбэк
CLEANING_TIME = 15
MASTER_BOT_TOKEN = os.getenv("MASTER_BOT_TOKEN", "8236516081:AAFjIjQBiAMs95XpURSCZZhuuYr5yDrcmlw")
BOT_API_URL = os.getenv("BOT_API_URL", "http://localhost:8001")

DB_PATH = os.path.join(os.getcwd(), "data", "beauty.db")

# === CORS ===
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://project-ev8r3.vercel.app", "https://*.vercel.app", "http://localhost:3000", "http://localhost:8000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_cors_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"
    return response

@app.options("/{path:path}")
async def options_handler(path: str):
    return JSONResponse(content={"message": "OK"}, headers={"Access-Control-Allow-Origin": "*"})

DEFAULT_WORK_START = "09:00"
DEFAULT_WORK_END = "20:00"


# ========== МОДЕЛИ ==========
class BookingIn(BaseModel):
    master_id: int
    service_id: int
    client_name: str
    client_telegram_id: str
    client_phone: Optional[str] = None
    date: str
    time: str

class MessageIn(BaseModel):
    booking_id: int
    from_id: str
    to_id: str
    message: str = None

class LocationUpdate(BaseModel):
    lat: float
    lon: float

class WorkHoursUpdate(BaseModel):
    work_start: str
    work_end: str

class ServiceIn(BaseModel):
    name: str
    price: int
    duration_min: int

class UserRegister(BaseModel):
    telegram_id: str

class QuickReplyIn(BaseModel):
    title: str
    message: str

class PromoApply(BaseModel):
    user_id: str
    promo_code: str

class CreateDepositPayment(BaseModel):
    booking_id: int

class ReviewIn(BaseModel):
    booking_id: int
    rating: int
    comment: Optional[str] = None

class ClientSettingsUpdate(BaseModel):
    phone: Optional[str] = None
    email: Optional[str] = None
    push_enabled: Optional[int] = None
    tg_notify_enabled: Optional[int] = None
    quiet_hour_start: Optional[str] = None
    quiet_hour_end: Optional[str] = None


# ========== БД ==========
def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Мастера
    c.execute("""CREATE TABLE IF NOT EXISTS masters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT DEFAULT '',
        address TEXT DEFAULT '',
        lat REAL DEFAULT 55.751244,
        lon REAL DEFAULT 37.618423,
        phone TEXT DEFAULT '',
        instagram TEXT DEFAULT '',
        telegram_id TEXT UNIQUE,
        work_start TEXT DEFAULT '09:00',
        work_end TEXT DEFAULT '20:00',
        bot_token TEXT DEFAULT '',
        description TEXT DEFAULT '',
        icon TEXT DEFAULT '💅',
        rating REAL DEFAULT 0
    )""")
    
    # Услуги
    c.execute("""CREATE TABLE IF NOT EXISTS services (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        master_id INTEGER,
        name TEXT,
        price INTEGER,
        duration_min INTEGER
    )""")
    
    # Бронирования
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
        total_amount REAL DEFAULT 0,
        payment_id TEXT,
        cashback_used REAL DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        confirmed_at TEXT,
        cancelled_at TEXT,
        reminder_sent INTEGER DEFAULT 0,
        review_sent INTEGER DEFAULT 0
    )""")
    
    # Выходные дни
    c.execute("""CREATE TABLE IF NOT EXISTS days_off (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        master_id INTEGER,
        date TEXT,
        UNIQUE(master_id, date)
    )""")
    
    # Чаты
    c.execute("""CREATE TABLE IF NOT EXISTS chats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        booking_id INTEGER UNIQUE,
        master_id INTEGER,
        client_telegram_id TEXT,
        master_telegram_id TEXT,
        token TEXT UNIQUE
    )""")
    
    # Сообщения
    c.execute("""CREATE TABLE IF NOT EXISTS chat_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        booking_id INTEGER,
        from_id TEXT,
        to_id TEXT,
        message TEXT,
        is_read INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    
    # Пользователи (клиенты) с расширенными полями
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id TEXT UNIQUE,
        phone TEXT DEFAULT '',
        email TEXT DEFAULT '',
        cashback_balance REAL DEFAULT 0,
        total_spent REAL DEFAULT 0,
        total_visits INTEGER DEFAULT 0,
        level TEXT DEFAULT 'Новичок',
        level_discount INTEGER DEFAULT 0,
        push_enabled INTEGER DEFAULT 1,
        tg_notify_enabled INTEGER DEFAULT 1,
        quiet_hour_start TEXT DEFAULT '22:00',
        quiet_hour_end TEXT DEFAULT '09:00',
        registered_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    
    # Быстрые ответы
    c.execute("""CREATE TABLE IF NOT EXISTS quick_replies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        master_id INTEGER,
        title TEXT,
        message TEXT
    )""")
    
    # Портфолио
    c.execute("""CREATE TABLE IF NOT EXISTS portfolio (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        master_id INTEGER,
        photo_url TEXT,
        description TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    
    # Избранное
    c.execute("""CREATE TABLE IF NOT EXISTS favorites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_telegram_id TEXT,
        master_id INTEGER,
        UNIQUE(client_telegram_id, master_id)
    )""")
    
    # Чёрный список
    c.execute("""CREATE TABLE IF NOT EXISTS blacklist (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        master_id INTEGER,
        client_telegram_id TEXT,
        reason TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    
    # Промокоды
    c.execute("""CREATE TABLE IF NOT EXISTS promocodes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE,
        discount INTEGER,
        expires_at TEXT,
        uses_limit INTEGER DEFAULT 1,
        used_count INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    
    # Отзывы
    c.execute("""CREATE TABLE IF NOT EXISTS reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        booking_id INTEGER UNIQUE,
        master_id INTEGER,
        client_telegram_id TEXT,
        rating INTEGER CHECK(rating >= 1 AND rating <= 5),
        comment TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    
    # Реферальные коды
    c.execute("""CREATE TABLE IF NOT EXISTS referrals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        referrer_telegram_id TEXT,
        referred_telegram_id TEXT,
        bonus_given INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    
    # Добавляем недостающие колонки
    for col in ['deposit_amount', 'total_amount', 'payment_id', 'cancelled_at', 'reminder_sent', 'review_sent', 'cashback_used']:
        try:
            if col in ['payment_id', 'cancelled_at']:
                c.execute(f"ALTER TABLE bookings ADD COLUMN {col} TEXT")
            else:
                c.execute(f"ALTER TABLE bookings ADD COLUMN {col} REAL DEFAULT 0")
        except:
            pass
    
    # Тестовый мастер
    c.execute("SELECT COUNT(*) FROM masters WHERE telegram_id = '868528632'")
    if c.fetchone()[0] == 0:
        c.execute("""INSERT INTO masters (name, address, lat, lon, phone, instagram, telegram_id, icon, work_start, work_end, bot_token, description, rating) 
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                  ("Алина Козлова", "ул. Ленина, 12", 47.222078, 39.720358, "+79001234567", "@alina_nails", "868528632", "💅", "09:00", "20:00", MASTER_BOT_TOKEN, "Мастер маникюра с 5-летним опытом", 4.9))
        c.execute("SELECT id FROM masters WHERE telegram_id = '868528632'")
        master_id = c.fetchone()[0]
        c.execute("INSERT INTO services (master_id, name, price, duration_min) VALUES (?,?,?,?)", (master_id, "Маникюр классический", 1200, 60))
        c.execute("INSERT INTO services (master_id, name, price, duration_min) VALUES (?,?,?,?)", (master_id, "Маникюр с покрытием гель-лак", 2000, 90))
        c.execute("INSERT INTO services (master_id, name, price, duration_min) VALUES (?,?,?,?)", (master_id, "Педикюр", 2500, 120))
    
    # Тестовый промокод
    c.execute("SELECT COUNT(*) FROM promocodes WHERE code = 'WELCOME10'")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO promocodes (code, discount, expires_at, uses_limit) VALUES ('WELCOME10', 10, ?, 100)", ((datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),))
    
    conn.commit()
    conn.close()
    logger.info("✅ БД готова")

init_db()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def time_to_minutes(time_str: str) -> int:
    h, m = map(int, time_str.split(':'))
    return h * 60 + m

def minutes_to_time(minutes: int) -> str:
    h = minutes // 60
    m = minutes % 60
    return f"{h:02d}:{m:02d}"

def generate_slots_with_duration(work_start: str, work_end: str, booked_slots: List[dict], service_duration: int, cleaning_time: int = 15) -> List[str]:
    start_min = time_to_minutes(work_start)
    end_min = time_to_minutes(work_end)
    interval = 30
    
    occupied_intervals = []
    for slot in booked_slots:
        slot_start = time_to_minutes(slot['time'])
        slot_duration = slot.get('duration_min', 60)
        slot_end = slot_start + slot_duration + cleaning_time
        occupied_intervals.append((slot_start, slot_end))
    
    occupied_intervals.sort()
    
    merged = []
    for interval in occupied_intervals:
        if not merged or merged[-1][1] < interval[0]:
            merged.append(list(interval))
        else:
            merged[-1][1] = max(merged[-1][1], interval[1])
    
    free_slots = []
    current_time = start_min
    
    for occ_start, occ_end in merged:
        while current_time + service_duration <= occ_start:
            free_slots.append(minutes_to_time(current_time))
            current_time += interval
        current_time = max(current_time, occ_end)
    
    while current_time + service_duration <= end_min:
        free_slots.append(minutes_to_time(current_time))
        current_time += interval
    
    return free_slots


async def send_telegram_message(chat_id: str, message: str, parse_mode: str = "Markdown"):
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"https://api.telegram.org/bot{MASTER_BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": message, "parse_mode": parse_mode}
            )
    except Exception as e:
        logger.error(f"Ошибка Telegram: {e}")

async def send_telegram_to_master(booking_data: dict):
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"https://api.telegram.org/bot{MASTER_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": booking_data.get("master_telegram_id"),
                    "text": f"🌸 *НОВАЯ ЗАПИСЬ!* 🌸\n\n👤 {booking_data.get('client_name')}\n💅 {booking_data.get('service_name')}\n💰 {booking_data.get('price')} ₽\n📅 {booking_data.get('date')} в {booking_data.get('time')}",
                    "parse_mode": "Markdown",
                    "reply_markup": {
                        "inline_keyboard": [
                            [{"text": "✅ Подтвердить", "callback_data": f"confirm_{booking_data.get('id')}"}],
                            [{"text": "❌ Отменить", "callback_data": f"cancel_{booking_data.get('id')}"}],
                            [{"text": "💬 Чат", "callback_data": f"chat_{booking_data.get('id')}"}]
                        ]
                    }
                }
            )
    except Exception as e:
        logger.error(f"Ошибка отправки мастеру: {e}")

def apply_cashback(client_telegram_id: str, amount: float, conn: sqlite3.Connection):
    cashback = round(amount * CASHBACK_PERCENT, 2)
    conn.execute("UPDATE users SET cashback_balance = cashback_balance + ? WHERE telegram_id = ?", (cashback, client_telegram_id))
    conn.commit()
    logger.info(f"💰 Начислен кэшбэк {cashback}₽ пользователю {client_telegram_id}")
    return cashback

def get_level_info(completed):
    if completed >= 50: return {"level": "Платина", "discount": 20, "badge": "💎", "next": 0}
    if completed >= 20: return {"level": "Золото", "discount": 15, "badge": "🥇", "next": 50}
    if completed >= 10: return {"level": "Серебро", "discount": 10, "badge": "🥈", "next": 20}
    if completed >= 5: return {"level": "Бронза", "discount": 5, "badge": "🥉", "next": 10}
    return {"level": "Новичок", "discount": 0, "badge": "🌱", "next": 5}

def confirm_booking(booking_id: int, conn: sqlite3.Connection):
    conn.execute("UPDATE bookings SET status='confirmed', confirmed_at=CURRENT_TIMESTAMP WHERE id=?", (booking_id,))
    conn.commit()
    
    booking = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
    master = conn.execute("SELECT * FROM masters WHERE id=?", (booking["master_id"],)).fetchone()
    service = conn.execute("SELECT * FROM services WHERE id=?", (booking["service_id"],)).fetchone()
    
    token = secrets.token_urlsafe(16)
    conn.execute("INSERT OR IGNORE INTO chats (booking_id, master_id, client_telegram_id, master_telegram_id, token) VALUES (?,?,?,?,?)",
                (booking_id, master["id"], booking["client_telegram_id"], master["telegram_id"], token))
    conn.commit()
    
    # Начисляем кэшбэк
    apply_cashback(booking["client_telegram_id"], service["price"], conn)
    
    # Обновляем статистику клиента
    conn.execute("UPDATE users SET total_visits = total_visits + 1, total_spent = total_spent + ? WHERE telegram_id = ?", (service["price"], booking["client_telegram_id"]))
    
    # Обновляем уровень клиента
    user = conn.execute("SELECT total_visits FROM users WHERE telegram_id = ?", (booking["client_telegram_id"],)).fetchone()
    level_info = get_level_info(user["total_visits"] if user else 0)
    conn.execute("UPDATE users SET level = ?, level_discount = ? WHERE telegram_id = ?", (level_info["level"], level_info["discount"], booking["client_telegram_id"]))
    conn.commit()
    
    master_msg = f"🌸 *ЗАПИСЬ ПОДТВЕРЖДЕНА!* 🌸\n\n👩 {booking['client_name']}\n📞 {booking['client_phone'] or 'не указан'}\n💅 {service['name']}\n💰 {service['price']} ₽\n📅 {booking['date']} в {booking['time']}"
    client_msg = f"🌸 *ЗАПИСЬ ПОДТВЕРЖДЕНА!* 🌸\n\n💅 {master['name']}\n📍 {master['address']}\n💅 {service['name']}\n💰 {service['price']} ₽\n💸 Оплачено: {booking['deposit_amount']} ₽\n🎁 Кэшбэк: {round(service['price'] * CASHBACK_PERCENT, 2)} ₽\n📅 {booking['date']} в {booking['time']}\n\n⭐ После сеанса вы сможете оставить отзыв!"
    
    asyncio.create_task(send_telegram_message(master["telegram_id"], master_msg))
    asyncio.create_task(send_telegram_message(booking["client_telegram_id"], client_msg))
    logger.info(f"✅ Бронь {booking_id} подтверждена, начислен кэшбэк")

async def create_ykassa_payment(amount: float, description: str, return_url: str, booking_id: int) -> dict:
    if not YKASSA_SHOP_ID or not YKASSA_SECRET_KEY:
        return {"confirmation_url": "https://yandex.ru", "payment_id": f"test_{booking_id}"}
    
    idempotence_key = str(uuid.uuid4())
    auth = base64.b64encode(f"{YKASSA_SHOP_ID}:{YKASSA_SECRET_KEY}".encode()).decode()
    
    payment_data = {
        "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
        "confirmation": {"type": "redirect", "return_url": return_url},
        "description": description[:120],
        "capture": True,
        "metadata": {"booking_id": str(booking_id)}
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.yookassa.ru/v3/payments",
                json=payment_data,
                headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json", "Idempotence-Key": idempotence_key}
            )
            if response.status_code == 200:
                data = response.json()
                return {"confirmation_url": data["confirmation"]["confirmation_url"], "payment_id": data["id"]}
            else:
                logger.error(f"ЮKassa ошибка: {response.status_code} - {response.text}")
                return {"confirmation_url": "https://yandex.ru", "payment_id": f"error_{booking_id}"}
    except Exception as e:
        logger.error(f"ЮKassa исключение: {e}")
        return {"confirmation_url": "https://yandex.ru", "payment_id": f"fallback_{booking_id}"}


# ========== ОСНОВНЫЕ ЭНДПОИНТЫ ==========

@app.get("/masters")
def get_masters(conn=Depends(get_db)):
    masters = conn.execute("SELECT * FROM masters WHERE name != '' AND address != ''").fetchall()
    result = []
    for m in masters:
        services = conn.execute("SELECT * FROM services WHERE master_id=?", (m["id"],)).fetchall()
        reviews = conn.execute("SELECT AVG(rating) as avg_rating, COUNT(*) as count FROM reviews WHERE master_id=?", (m["id"],)).fetchone()
        d = dict(m)
        d["services"] = [dict(s) for s in services]
        d["reviews_avg"] = reviews["avg_rating"] or 0
        d["reviews_count"] = reviews["count"] or 0
        result.append(d)
    return result

@app.get("/masters/by_telegram/{telegram_id}")
def get_master_by_telegram(telegram_id: str, conn=Depends(get_db)):
    m = conn.execute("SELECT * FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not m:
        raise HTTPException(404, "Master not found")
    return dict(m)

@app.get("/masters/{master_id}")
def get_master_by_id(master_id: int, conn=Depends(get_db)):
    m = conn.execute("SELECT * FROM masters WHERE id=?", (master_id,)).fetchone()
    if not m:
        raise HTTPException(404, "Master not found")
    services = conn.execute("SELECT * FROM services WHERE master_id=?", (master_id,)).fetchall()
    portfolio = conn.execute("SELECT * FROM portfolio WHERE master_id=? ORDER BY created_at DESC", (master_id,)).fetchall()
    reviews = conn.execute("SELECT r.*, b.client_name FROM reviews r JOIN bookings b ON r.booking_id = b.id WHERE r.master_id=? ORDER BY r.created_at DESC", (master_id,)).fetchall()
    d = dict(m)
    d["services"] = [dict(s) for s in services]
    d["portfolio"] = [dict(p) for p in portfolio]
    d["reviews"] = [dict(r) for r in reviews]
    return d

@app.get("/masters/{master_id}/days_off")
def get_days_off(master_id: int, conn=Depends(get_db)):
    days = conn.execute("SELECT date FROM days_off WHERE master_id=?", (master_id,)).fetchall()
    return [dict(d) for d in days]

@app.delete("/masters/{master_id}/days_off/{date}")
def remove_day_off(master_id: int, date: str, conn=Depends(get_db)):
    conn.execute("DELETE FROM days_off WHERE master_id=? AND date=?", (master_id, date))
    conn.commit()
    return {"status": "ok"}

@app.post("/masters/{master_id}/days_off")
def add_day_off(master_id: int, date: str, conn=Depends(get_db)):
    conn.execute("INSERT OR IGNORE INTO days_off (master_id, date) VALUES (?,?)", (master_id, date))
    conn.commit()
    return {"status": "ok"}

@app.get("/masters/{master_id}/slots")
def get_slots(master_id: int, date: str, service_id: int, conn=Depends(get_db)):
    master = conn.execute("SELECT * FROM masters WHERE id=?", (master_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    
    service = conn.execute("SELECT duration_min FROM services WHERE id=? AND master_id=?", (service_id, master_id)).fetchone()
    if not service:
        raise HTTPException(404, "Service not found")
    
    service_duration = service["duration_min"]
    
    day_off = conn.execute("SELECT id FROM days_off WHERE master_id=? AND date=?", (master_id, date)).fetchone()
    if day_off:
        return {"date": date, "slots": [], "day_off": True}
    
    work_start = master["work_start"] or DEFAULT_WORK_START
    work_end = master["work_end"] or DEFAULT_WORK_END
    
    booked = conn.execute("""
        SELECT b.time, s.duration_min 
        FROM bookings b 
        JOIN services s ON b.service_id = s.id 
        WHERE b.master_id=? AND b.date=? AND b.status IN ('pending_payment', 'confirmed')
    """, (master_id, date)).fetchall()
    
    booked_slots = [{"time": b["time"], "duration_min": b["duration_min"]} for b in booked]
    free_slots = generate_slots_with_duration(work_start, work_end, booked_slots, service_duration, CLEANING_TIME)
    
    today = datetime.now().strftime("%Y-%m-%d")
    now_time = datetime.now().strftime("%H:%M")
    now_minutes = time_to_minutes(now_time)
    
    if date == today:
        free_slots = [s for s in free_slots if time_to_minutes(s) > now_minutes]
    
    return {"date": date, "slots": free_slots, "day_off": False}


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
        
        existing = conn.execute("SELECT id FROM bookings WHERE master_id=? AND date=? AND time=? AND status IN ('pending_payment', 'confirmed')", 
                               (data.master_id, data.date, data.time)).fetchone()
        if existing:
            raise HTTPException(409, "Slot already booked")
        
        # Проверяем кэшбэк пользователя
        user = conn.execute("SELECT cashback_balance, level_discount FROM users WHERE telegram_id = ?", (data.client_telegram_id,)).fetchone()
        user_discount = user["level_discount"] if user else 0
        cashback_to_use = min(user["cashback_balance"] if user else 0, service["price"] * 0.3) if user else 0
        
        final_price = service["price"]
        final_price_with_discount = final_price * (100 - user_discount) / 100
        final_price_with_cashback = final_price_with_discount - cashback_to_use
        deposit_amount = round(max(final_price_with_cashback * PAYMENT_COMMISSION, 50), 2)
        deposit_amount = min(deposit_amount, final_price_with_cashback)
        
        cur = conn.execute("""
            INSERT INTO bookings (master_id, service_id, client_name, client_telegram_id, client_phone, date, time, deposit_amount, total_amount, cashback_used)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (data.master_id, data.service_id, data.client_name, data.client_telegram_id, data.client_phone, data.date, data.time, deposit_amount, final_price_with_cashback, cashback_to_use))
        conn.commit()
        booking_id = cur.lastrowid
        
        if cashback_to_use > 0:
            conn.execute("UPDATE users SET cashback_balance = cashback_balance - ? WHERE telegram_id = ?", (cashback_to_use, data.client_telegram_id))
            conn.commit()
        
        logger.info(f"📝 Бронь {booking_id}: {data.client_name} -> {service['name']}")
        
        # Уведомление мастеру
        booking_data = {
            "id": booking_id,
            "master_id": data.master_id,
            "master_telegram_id": master["telegram_id"],
            "client_name": data.client_name,
            "service_name": service["name"],
            "price": final_price_with_cashback,
            "date": data.date,
            "time": data.time,
            "deposit_amount": deposit_amount
        }
        asyncio.create_task(send_telegram_to_master(booking_data))
        
        # Уведомление клиенту
        client_msg = f"🌸 *ЗАЯВКА ОТПРАВЛЕНА!* 🌸\n\n💅 {service['name']}\n💰 {final_price_with_cashback} ₽\n💸 Депозит: {deposit_amount} ₽\n🎁 Скидка по уровню: {user_discount}%\n🎁 Списано кэшбэка: {cashback_to_use} ₽\n📅 {data.date} в {data.time}\n\n⏳ Ожидайте подтверждения мастера"
        asyncio.create_task(send_telegram_message(data.client_telegram_id, client_msg))
        
        payment = await create_ykassa_payment(
            amount=deposit_amount,
            description=f"Бронь {service['name']} (депозит {deposit_amount}₽)",
            return_url=f"{YKASSA_RETURN_URL}?booking_id={booking_id}",
            booking_id=booking_id
        )
        
        conn.execute("UPDATE bookings SET payment_id=? WHERE id=?", (payment["payment_id"], booking_id))
        conn.commit()
        
        return {
            "booking_id": booking_id,
            "payment_url": payment["confirmation_url"],
            "deposit_amount": deposit_amount,
            "service_price": final_price_with_cashback,
            "discount_applied": user_discount,
            "cashback_used": cashback_to_use,
            "status": "pending_payment"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        raise HTTPException(500, detail=str(e))
    finally:
        conn.close()


@app.patch("/bookings/{booking_id}/status")
def update_booking_status(booking_id: int, status: str, conn=Depends(get_db)):
    booking = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    if not booking:
        raise HTTPException(404, "Booking not found")
    
    if status == "confirmed":
        confirm_booking(booking_id, conn)
    elif status == "cancelled":
        conn.execute("UPDATE bookings SET status='cancelled', cancelled_at=CURRENT_TIMESTAMP WHERE id=?", (booking_id,))
        conn.commit()
        
        # Возвращаем кэшбэк если был использован
        if booking["cashback_used"] > 0:
            conn.execute("UPDATE users SET cashback_balance = cashback_balance + ? WHERE telegram_id = ?", (booking["cashback_used"], booking["client_telegram_id"]))
            conn.commit()
        
        master = conn.execute("SELECT * FROM masters WHERE id=?", (booking["master_id"],)).fetchone()
        service = conn.execute("SELECT * FROM services WHERE id=?", (booking["service_id"],)).fetchone()
        
        client_msg = f"❌ *ЗАПИСЬ ОТМЕНЕНА*\n\n📅 {booking['date']} в {booking['time']}\n💅 {service['name']}\n💸 Возвращено кэшбэка: {booking['cashback_used']} ₽\n\n💸 Депозит вернётся в течение 3-7 дней."
        asyncio.create_task(send_telegram_message(booking["client_telegram_id"], client_msg))
    else:
        raise HTTPException(400, "Invalid status")
    
    return {"status": "ok"}


# ========== ПРОФИЛЬ И СТАТИСТИКА КЛИЕНТА ==========
@app.get("/client/profile/{telegram_id}")
def get_client_profile(telegram_id: str, conn: sqlite3.Connection = Depends(get_db)):
    user = conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
    if not user:
        conn.execute("INSERT INTO users (telegram_id, cashback_balance, total_spent, total_visits, level, level_discount) VALUES (?, 0, 0, 0, 'Новичок', 0)", (telegram_id,))
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
    
    # Получаем все подтверждённые записи
    bookings = conn.execute("""
        SELECT b.*, s.price, m.name as master_name, s.name as service_name,
               CASE WHEN r.id IS NOT NULL THEN 1 ELSE 0 END as review_given
        FROM bookings b
        JOIN services s ON b.service_id = s.id
        JOIN masters m ON b.master_id = m.id
        LEFT JOIN reviews r ON b.id = r.booking_id
        WHERE b.client_telegram_id = ? AND b.status = 'confirmed'
        ORDER BY b.date DESC
    """, (telegram_id,)).fetchall()
    
    # Подсчёт статистики
    total_visits = len(bookings)
    total_spent = sum(b["price"] for b in bookings) if bookings else 0
    reviews_count = conn.execute("SELECT COUNT(*) FROM reviews WHERE client_telegram_id = ?", (telegram_id,)).fetchone()[0]
    
    # Получаем следующую запись
    next_booking = conn.execute("""
        SELECT b.*, m.name as master_name, s.name as service_name, s.price
        FROM bookings b
        JOIN masters m ON b.master_id = m.id
        JOIN services s ON b.service_id = s.id
        WHERE b.client_telegram_id = ? AND b.status = 'confirmed' AND b.date >= date('now')
        ORDER BY b.date, b.time LIMIT 1
    """, (telegram_id,)).fetchone()
    
    # Получаем активные промокоды
    promos = conn.execute("""
        SELECT * FROM promocodes 
        WHERE expires_at >= date('now') AND used_count < uses_limit
        ORDER BY discount DESC LIMIT 3
    """).fetchall()
    
    # Уровень клиента
    level_info = get_level_info(total_visits)
    visits_to_next = level_info["next"] - total_visits if level_info["next"] > 0 else 0
    next_level_name = ""
    if visits_to_next > 0:
        levels = ["Новичок", "Бронза", "Серебро", "Золото", "Платина"]
        current_idx = levels.index(level_info["level"])
        next_level_name = levels[current_idx + 1] if current_idx + 1 < len(levels) else "MAX"
    
    # Обновляем данные пользователя
    conn.execute("UPDATE users SET total_visits=?, total_spent=?, level=?, level_discount=? WHERE telegram_id=?", 
                (total_visits, total_spent, level_info["level"], level_info["discount"], telegram_id))
    conn.commit()
    
    return {
        "user": dict(user),
        "stats": {
            "total_visits": total_visits,
            "reviews_count": reviews_count,
            "total_spent": total_spent,
            "cashback_balance": user["cashback_balance"] or 0,
            "level": level_info["level"],
            "level_discount": level_info["discount"],
            "level_badge": level_info["badge"],
            "visits_to_next_level": visits_to_next,
            "next_level_name": next_level_name
        },
        "next_booking": dict(next_booking) if next_booking else None,
        "recent_bookings": [dict(b) for b in bookings[:5]],
        "available_promos": [dict(p) for p in promos]
    }

@app.patch("/client/settings/{telegram_id}")
def update_client_settings(telegram_id: str, data: ClientSettingsUpdate, conn: sqlite3.Connection = Depends(get_db)):
    for field, value in data.dict(exclude_none=True).items():
        conn.execute(f"UPDATE users SET {field}=? WHERE telegram_id=?", (value, telegram_id))
    conn.commit()
    return {"status": "ok"}

@app.get("/client/referral/{telegram_id}")
def get_referral_link(telegram_id: str):
    code = hashlib.md5(telegram_id.encode()).hexdigest()[:8].upper()
    return {"code": code, "link": f"https://t.me/pinkspotvelur_bot?start=ref_{code}", "bonus": 500}


# ========== ОТЗЫВЫ ==========
@app.post("/reviews")
def add_review(data: ReviewIn, conn: sqlite3.Connection = Depends(get_db)):
    booking = conn.execute("""
        SELECT b.*, m.id as master_id 
        FROM bookings b 
        JOIN masters m ON b.master_id = m.id 
        WHERE b.id = ? AND b.status = 'confirmed'
    """, (data.booking_id,)).fetchone()
    
    if not booking:
        raise HTTPException(404, "Booking not found or not confirmed")
    
    if booking["date"] > datetime.now().strftime("%Y-%m-%d"):
        raise HTTPException(400, "Cannot review future appointments")
    
    existing = conn.execute("SELECT id FROM reviews WHERE booking_id = ?", (data.booking_id,)).fetchone()
    if existing:
        raise HTTPException(400, "Review already exists")
    
    conn.execute("""
        INSERT INTO reviews (booking_id, master_id, client_telegram_id, rating, comment)
        VALUES (?, ?, ?, ?, ?)
    """, (data.booking_id, booking["master_id"], booking["client_telegram_id"], data.rating, data.comment))
    
    conn.execute("""
        UPDATE masters 
        SET rating = (SELECT AVG(rating) FROM reviews WHERE master_id = ?)
        WHERE id = ?
    """, (booking["master_id"], booking["master_id"]))
    
    conn.commit()
    return {"status": "ok"}

@app.get("/masters/{master_id}/reviews")
def get_master_reviews(master_id: int, conn: sqlite3.Connection = Depends(get_db)):
    reviews = conn.execute("""
        SELECT r.*, b.client_name 
        FROM reviews r
        JOIN bookings b ON r.booking_id = b.id
        WHERE r.master_id = ?
        ORDER BY r.created_at DESC
    """, (master_id,)).fetchall()
    return [dict(r) for r in reviews]


# ========== ПРОФИЛЬ МАСТЕРА ==========
@app.patch("/master/{telegram_id}/profile")
def update_master_profile(telegram_id: str, data: dict, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    
    for key in ['name', 'address', 'phone', 'instagram', 'description', 'work_start', 'work_end', 'lat', 'lon']:
        if key in data and data[key]:
            conn.execute(f"UPDATE masters SET {key}=? WHERE id=?", (data[key], master["id"]))
    conn.commit()
    return {"status": "ok"}

@app.get("/master/{telegram_id}/profile")
def get_master_profile(telegram_id: str, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT * FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    return dict(master)

@app.patch("/master/{telegram_id}/location")
def update_location(telegram_id: str, data: LocationUpdate, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("UPDATE masters SET lat=?, lon=? WHERE telegram_id=?", (data.lat, data.lon, telegram_id))
    conn.commit()
    return {"status": "ok"}

@app.patch("/master/{telegram_id}/work-hours")
def update_work_hours(telegram_id: str, data: WorkHoursUpdate, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("UPDATE masters SET work_start=?, work_end=? WHERE telegram_id=?", (data.work_start, data.work_end, telegram_id))
    conn.commit()
    return {"status": "ok"}


# ========== УСЛУГИ ==========
@app.post("/master/{telegram_id}/services")
def add_service(telegram_id: str, data: ServiceIn, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    conn.execute("INSERT INTO services (master_id, name, price, duration_min) VALUES (?,?,?,?)",
                (master["id"], data.name, data.price, data.duration_min))
    conn.commit()
    return {"status": "ok"}

@app.delete("/master/{telegram_id}/services/{service_id}")
def delete_service(telegram_id: str, service_id: int, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    conn.execute("DELETE FROM services WHERE id=? AND master_id=?", (service_id, master["id"]))
    conn.commit()
    return {"status": "ok"}

@app.get("/master/{telegram_id}/services")
def get_master_services(telegram_id: str, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    services = conn.execute("SELECT * FROM services WHERE master_id=?", (master["id"],)).fetchall()
    return [dict(s) for s in services]


# ========== БЫСТРЫЕ ОТВЕТЫ ==========
@app.post("/master/{telegram_id}/quick-replies")
def add_quick_reply(telegram_id: str, data: QuickReplyIn, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    conn.execute("INSERT INTO quick_replies (master_id, title, message) VALUES (?,?,?)",
                (master["id"], data.title, data.message))
    conn.commit()
    return {"status": "ok"}

@app.get("/master/{telegram_id}/quick-replies")
def get_quick_replies(telegram_id: str, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    replies = conn.execute("SELECT * FROM quick_replies WHERE master_id=?", (master["id"],)).fetchall()
    return [dict(r) for r in replies]

@app.delete("/master/{telegram_id}/quick-replies/{reply_id}")
def delete_quick_reply(telegram_id: str, reply_id: int, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    conn.execute("DELETE FROM quick_replies WHERE id=? AND master_id=?", (reply_id, master["id"]))
    conn.commit()
    return {"status": "ok"}


# ========== ПОРТФОЛИО ==========
@app.get("/masters/{master_id}/portfolio")
def get_master_portfolio(master_id: int, conn: sqlite3.Connection = Depends(get_db)):
    portfolio = conn.execute("SELECT * FROM portfolio WHERE master_id = ? ORDER BY created_at DESC", (master_id,)).fetchall()
    return [dict(p) for p in portfolio]

@app.post("/master/{telegram_id}/portfolio")
async def add_portfolio_photo(
    telegram_id: str,
    photo_url: str = Form(...),
    description: str = Form(""),
    conn: sqlite3.Connection = Depends(get_db)
):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    
    if not photo_url.startswith(('http://', 'https://')):
        raise HTTPException(400, "Invalid photo URL")
    
    existing = conn.execute("SELECT id FROM portfolio WHERE master_id=? AND photo_url=?", (master["id"], photo_url)).fetchone()
    if existing:
        raise HTTPException(400, "Photo already exists")
    
    conn.execute("""
        INSERT INTO portfolio (master_id, photo_url, description, created_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
    """, (master["id"], photo_url, description))
    conn.commit()
    
    return {"status": "ok", "message": "Photo added"}

@app.delete("/master/{telegram_id}/portfolio/{photo_id}")
def delete_portfolio_photo(telegram_id: str, photo_id: int, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    conn.execute("DELETE FROM portfolio WHERE id = ? AND master_id = ?", (photo_id, master["id"]))
    conn.commit()
    return {"status": "ok"}


# ========== ИЗБРАННОЕ ==========
@app.post("/favorites/{master_id}")
def add_favorite(master_id: int, client_telegram_id: str, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("INSERT OR IGNORE INTO favorites (client_telegram_id, master_id) VALUES (?,?)", (client_telegram_id, master_id))
    conn.commit()
    return {"status": "ok"}

@app.delete("/favorites/{master_id}")
def remove_favorite(master_id: int, client_telegram_id: str, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("DELETE FROM favorites WHERE client_telegram_id=? AND master_id=?", (client_telegram_id, master_id))
    conn.commit()
    return {"status": "ok"}

@app.get("/favorites/{client_telegram_id}")
def get_favorites(client_telegram_id: str, conn: sqlite3.Connection = Depends(get_db)):
    favorites = conn.execute("""
        SELECT m.* FROM masters m
        JOIN favorites f ON m.id = f.master_id
        WHERE f.client_telegram_id = ? AND m.name != '' AND m.address != ''
    """, (client_telegram_id,)).fetchall()
    return [dict(f) for f in favorites]


# ========== ЗАПИСИ ==========
@app.get("/bookings/client/{telegram_id}")
def get_client_bookings(telegram_id: str, conn: sqlite3.Connection = Depends(get_db)):
    bookings = conn.execute("""
        SELECT b.*, m.name as master_name, s.name as service_name, s.price,
               CASE WHEN r.id IS NOT NULL THEN 1 ELSE 0 END as review_given
        FROM bookings b 
        JOIN masters m ON b.master_id = m.id 
        JOIN services s ON b.service_id = s.id
        LEFT JOIN reviews r ON b.id = r.booking_id
        WHERE b.client_telegram_id = ? 
        ORDER BY b.date DESC, b.time DESC
    """, (telegram_id,)).fetchall()
    return [dict(b) for b in bookings]

@app.get("/bookings/master/{master_id}")
def get_master_bookings(master_id: int, date: str = None, conn: sqlite3.Connection = Depends(get_db)):
    if date:
        bookings = conn.execute("""
            SELECT b.*, s.name as service_name, s.price
            FROM bookings b 
            JOIN services s ON b.service_id = s.id
            WHERE b.master_id = ? AND b.date = ? 
            ORDER BY b.time
        """, (master_id, date)).fetchall()
    else:
        bookings = conn.execute("""
            SELECT b.*, s.name as service_name, s.price
            FROM bookings b 
            JOIN services s ON b.service_id = s.id
            WHERE b.master_id = ? AND b.date >= date('now') 
            ORDER BY b.date, b.time
        """, (master_id,)).fetchall()
    return [dict(b) for b in bookings]

@app.get("/master/{telegram_id}/stats")
def get_stats(telegram_id: str, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    confirmed = conn.execute("SELECT COUNT(*) FROM bookings WHERE master_id=? AND status='confirmed'", (master["id"],)).fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM bookings WHERE master_id=? AND status='pending_payment'", (master["id"],)).fetchone()[0]
    revenue = conn.execute("SELECT SUM(price) FROM bookings b JOIN services s ON b.service_id=s.id WHERE b.master_id=? AND b.status='confirmed'", (master["id"],)).fetchone()[0] or 0
    return {"completed": confirmed, "pending": pending, "revenue": revenue}


# ========== ЧАТ ==========
@app.post("/chat/send")
def send_message(data: MessageIn, conn: sqlite3.Connection = Depends(get_db)):
    booking = conn.execute("SELECT status FROM bookings WHERE id=?", (data.booking_id,)).fetchone()
    if not booking or booking["status"] != "confirmed":
        raise HTTPException(403, "Chat available only after payment")
    conn.execute("INSERT INTO chat_messages (booking_id, from_id, to_id, message) VALUES (?,?,?,?)",
                (data.booking_id, data.from_id, data.to_id, data.message))
    conn.commit()
    return {"status": "ok"}

@app.get("/chat/messages/{booking_id}")
def get_messages(booking_id: int, user_id: str, conn: sqlite3.Connection = Depends(get_db)):
    messages = conn.execute("SELECT * FROM chat_messages WHERE booking_id=? ORDER BY created_at ASC", (booking_id,)).fetchall()
    return [dict(m) for m in messages]

@app.get("/chat/{token}")
def get_chat_by_token(token: str, conn: sqlite3.Connection = Depends(get_db)):
    chat = conn.execute("SELECT * FROM chats WHERE token = ?", (token,)).fetchone()
    if not chat:
        raise HTTPException(404, "Chat not found")
    return dict(chat)


# ========== ПОЛЬЗОВАТЕЛИ ==========
@app.post("/user/register")
def register_user(data: UserRegister, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("INSERT OR IGNORE INTO users (telegram_id) VALUES (?)", (data.telegram_id,))
    conn.commit()
    return {"status": "ok"}


# ========== АДМИН-ПАНЕЛЬ ==========
@app.post("/admin/add-master")
def admin_add_master(data: dict, conn: sqlite3.Connection = Depends(get_db)):
    telegram_id = data.get("telegram_id")
    if not telegram_id:
        raise HTTPException(400, "telegram_id required")
    
    existing = conn.execute("SELECT id FROM masters WHERE telegram_id = ?", (telegram_id,)).fetchone()
    if existing:
        raise HTTPException(400, "Master already exists")
    
    conn.execute("INSERT INTO masters (telegram_id, name, work_start, work_end) VALUES (?, '', '09:00', '20:00')", (telegram_id,))
    conn.commit()
    return {"status": "ok", "master_id": conn.execute("SELECT last_insert_rowid()").fetchone()[0]}

@app.get("/admin/masters")
def admin_get_masters(conn: sqlite3.Connection = Depends(get_db)):
    masters = conn.execute("""
        SELECT id, name, telegram_id, phone, instagram, icon, rating,
               CASE WHEN name IS NULL OR name = '' THEN 'Не заполнен' ELSE 'Заполнен' END as status
        FROM masters ORDER BY id DESC
    """).fetchall()
    return [dict(m) for m in masters]

@app.delete("/admin/delete-master/{master_id}")
def admin_delete_master(master_id: int, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("DELETE FROM services WHERE master_id = ?", (master_id,))
    conn.execute("DELETE FROM bookings WHERE master_id = ?", (master_id,))
    conn.execute("DELETE FROM days_off WHERE master_id = ?", (master_id,))
    conn.execute("DELETE FROM quick_replies WHERE master_id = ?", (master_id,))
    conn.execute("DELETE FROM portfolio WHERE master_id = ?", (master_id,))
    conn.execute("DELETE FROM favorites WHERE master_id = ?", (master_id,))
    conn.execute("DELETE FROM reviews WHERE master_id = ?", (master_id,))
    conn.execute("DELETE FROM masters WHERE id = ?", (master_id,))
    conn.commit()
    return {"status": "ok"}

@app.post("/admin/add-promo")
def admin_add_promo(data: dict, conn: sqlite3.Connection = Depends(get_db)):
    code = data.get("code", "").upper()
    discount = data.get("discount", 10)
    valid_until = data.get("valid_until")
    max_uses = data.get("max_uses", 100)
    
    existing = conn.execute("SELECT id FROM promocodes WHERE code = ?", (code,)).fetchone()
    if existing:
        raise HTTPException(400, "Promocode already exists")
    
    conn.execute("INSERT INTO promocodes (code, discount, expires_at, uses_limit) VALUES (?, ?, ?, ?)", (code, discount, valid_until, max_uses))
    conn.commit()
    return {"status": "ok"}

@app.get("/admin/stats")
def admin_get_stats(conn: sqlite3.Connection = Depends(get_db)):
    masters = conn.execute("SELECT COUNT(*) FROM masters").fetchone()[0]
    bookings = conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
    confirmed = conn.execute("SELECT COUNT(*) FROM bookings WHERE status='confirmed'").fetchone()[0]
    revenue = conn.execute("SELECT SUM(price) FROM bookings b JOIN services s ON b.service_id=s.id WHERE b.status='confirmed'").fetchone()[0] or 0
    users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    return {"masters": masters, "total_bookings": bookings, "confirmed": confirmed, "revenue": revenue, "users": users}


# ========== ПРОМОКОДЫ ==========
@app.post("/apply-promo")
def apply_promo(data: PromoApply, conn: sqlite3.Connection = Depends(get_db)):
    promo = conn.execute("""
        SELECT * FROM promocodes 
        WHERE code = ? AND (expires_at IS NULL OR expires_at > date('now')) 
        AND used_count < uses_limit
    """, (data.promo_code,)).fetchone()
    
    if not promo:
        raise HTTPException(400, "Промокод недействителен")
    
    conn.execute("UPDATE promocodes SET used_count = used_count + 1 WHERE id = ?", (promo["id"],))
    conn.commit()
    
    return {"status": "ok", "discount_percent": promo["discount"], "valid_until": promo["expires_at"]}


@app.get("/")
def root():
    return {"status": "Beauty Bot API running 🌸", "version": "4.0.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
