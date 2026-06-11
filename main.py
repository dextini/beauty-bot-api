from fastapi import FastAPI, HTTPException, Depends, Request, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List
import sqlite3
import httpx
import json
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

# === КОНФИГУРАЦИЯ ===
YKASSA_SHOP_ID = os.getenv("YKASSA_SHOP_ID", "1368786")
YKASSA_SECRET_KEY = os.getenv("YKASSA_SECRET_KEY", "")
YKASSA_RETURN_URL = os.getenv("YKASSA_RETURN_URL", "https://t.me/pinkspotvelur_bot")
PAYMENT_COMMISSION = 0.07
CLEANING_TIME = 15
MASTER_BOT_TOKEN = os.getenv("MASTER_BOT_TOKEN", "8236516081:AAFjIjQBiAMs95XpURSCZZhuuYr5yDrcmlw")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY", "")
SMS_API_KEY = os.getenv("SMS_API_KEY", "")

# === ПУТЬ К БАЗЕ ДАННЫХ ===
DB_PATH = "beauty.db"

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

DEFAULT_WORK_START = "09:00"
DEFAULT_WORK_END = "20:00"

# ========== МОДЕЛИ ==========
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

class PortfolioIn(BaseModel):
    photo_url: str
    description: str = ""

# ========== БД ==========
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Таблица мастеров
    c.execute("""CREATE TABLE IF NOT EXISTS masters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, address TEXT, lat REAL, lon REAL,
        phone TEXT, instagram TEXT, telegram_id TEXT,
        work_start TEXT DEFAULT '09:00', work_end TEXT DEFAULT '20:00',
        bot_token TEXT, description TEXT, icon TEXT DEFAULT '💅', rating REAL DEFAULT 0
    )""")
    
    # Таблица услуг
    c.execute("""CREATE TABLE IF NOT EXISTS services (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        master_id INTEGER, name TEXT, price INTEGER, duration_min INTEGER
    )""")
    
    # Таблица записей
    c.execute("""CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        master_id INTEGER, service_id INTEGER,
        client_name TEXT, client_telegram_id TEXT, client_phone TEXT,
        date TEXT, time TEXT,
        status TEXT DEFAULT 'pending_payment',
        deposit_amount REAL DEFAULT 0,
        total_amount REAL DEFAULT 0,
        payment_id TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        confirmed_at TEXT,
        cancelled_at TEXT,
        reminder_24h_sent INTEGER DEFAULT 0,
        reminder_1h_sent INTEGER DEFAULT 0,
        sms_sent INTEGER DEFAULT 0
    )""")
    
    # Таблица выходных дней
    c.execute("""CREATE TABLE IF NOT EXISTS days_off (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        master_id INTEGER, date TEXT, UNIQUE(master_id, date)
    )""")
    
    # Таблица чатов
    c.execute("""CREATE TABLE IF NOT EXISTS chats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        booking_id INTEGER UNIQUE, master_id INTEGER,
        client_telegram_id TEXT, master_telegram_id TEXT, token TEXT UNIQUE
    )""")
    
    # Таблица сообщений чата
    c.execute("""CREATE TABLE IF NOT EXISTS chat_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        booking_id INTEGER, from_id TEXT, to_id TEXT,
        message TEXT, is_read INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    
    # Таблица пользователей
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id TEXT UNIQUE, registered_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    
    # Таблица быстрых ответов
    c.execute("""CREATE TABLE IF NOT EXISTS quick_replies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        master_id INTEGER,
        title TEXT,
        message TEXT,
        FOREIGN KEY (master_id) REFERENCES masters(id)
    )""")
    
    # Таблица портфолио
    c.execute("""CREATE TABLE IF NOT EXISTS portfolio (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        master_id INTEGER,
        photo_url TEXT,
        description TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (master_id) REFERENCES masters(id)
    )""")
    
    # Таблица избранного
    c.execute("""CREATE TABLE IF NOT EXISTS favorites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_telegram_id TEXT,
        master_id INTEGER,
        UNIQUE(client_telegram_id, master_id),
        FOREIGN KEY (master_id) REFERENCES masters(id)
    )""")
    
    # Таблица чёрного списка
    c.execute("""CREATE TABLE IF NOT EXISTS blacklist (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        master_id INTEGER,
        client_telegram_id TEXT,
        reason TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (master_id) REFERENCES masters(id)
    )""")
    
    # ПРИНУДИТЕЛЬНОЕ ДОБАВЛЕНИЕ ВСЕХ НУЖНЫХ КОЛОНОК (для существующей БД)
    required_columns = {
        'deposit_amount': 'REAL DEFAULT 0',
        'total_amount': 'REAL DEFAULT 0',
        'payment_id': 'TEXT',
        'cancelled_at': 'TEXT',
        'reminder_24h_sent': 'INTEGER DEFAULT 0',
        'reminder_1h_sent': 'INTEGER DEFAULT 0',
        'sms_sent': 'INTEGER DEFAULT 0'
    }
    
    for col_name, col_type in required_columns.items():
        try:
            c.execute(f"ALTER TABLE bookings ADD COLUMN {col_name} {col_type}")
            logger.info(f"✅ Добавлена колонка {col_name}")
        except Exception as e:
            logger.info(f"Колонка {col_name} уже есть: {e}")
    
    # Тестовые данные (только Алина Козлова в Ростове-на-Дону)
    c.execute("SELECT COUNT(*) FROM masters")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO masters (name, address, lat, lon, phone, instagram, icon, work_start, work_end, telegram_id, bot_token) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  ("Алина Козлова", "ул. Ленина, 12", 47.222078, 39.720358, "+79001234567", "@alina_nails", "💅", "09:00", "20:00", "868528632", MASTER_BOT_TOKEN))
        c.execute("SELECT id FROM masters")
        master_id = c.fetchone()[0]
        c.execute("INSERT INTO services (master_id, name, price, duration_min) VALUES (?,?,?,?)", (master_id, "Маникюр классический", 1200, 60))
        c.execute("INSERT INTO services (master_id, name, price, duration_min) VALUES (?,?,?,?)", (master_id, "Маникюр с покрытием гель-лак", 2000, 90))
        c.execute("INSERT INTO services (master_id, name, price, duration_min) VALUES (?,?,?,?)", (master_id, "Педикюр", 2500, 120))
        
        # Быстрые ответы
        quick_replies = [
            ("Цена", "💅 Стоимость услуги: {price} ₽"),
            ("Адрес", "📍 Я нахожусь по адресу: {address}"),
            ("Как добраться", "🚇 Ближайшая станция метро - Пушкинская"),
            ("Продолжительность", "⏱️ Услуга займёт примерно {duration} минут"),
        ]
        for title, msg in quick_replies:
            c.execute("INSERT INTO quick_replies (master_id, title, message) VALUES (?,?,?)", (master_id, title, msg))
    
    conn.commit()
    conn.close()
    logger.info("✅ БД готова")

init_db()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

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
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{MASTER_BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": message, "parse_mode": parse_mode}
            )
            logger.info(f"✅ Сообщение отправлено в Telegram: {chat_id}")
    except Exception as e:
        logger.error(f"❌ Ошибка отправки в Telegram: {e}")

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
    
    master_msg = f"🌸 *НОВАЯ ЗАПИСЬ ПОДТВЕРЖДЕНА!* 🌸\n\n✅ Статус: Оплачен\n👩 Клиент: {booking['client_name']}\n📞 Телефон: {booking['client_phone'] or 'не указан'}\n💅 Услуга: {service['name']}\n💰 Стоимость услуги: {service['price']} ₽\n💸 Депозит 7%: {booking['deposit_amount']} ₽\n📅 Дата: {booking['date']}\n🕐 Время: {booking['time']}"
    client_msg = f"🌸 *ЗАПИСЬ ПОДТВЕРЖДЕНА!* 🌸\n\n✅ Статус: Подтверждено\n💅 Мастер: {master['name']}\n📍 Адрес: {master['address']}\n💅 Услуга: {service['name']}\n💰 Стоимость: {service['price']} ₽\n💸 Оплачено (депозит 7%): {booking['deposit_amount']} ₽\n💎 Остаток на месте: {service['price']} ₽\n📅 Дата: {booking['date']}\n🕐 Время: {booking['time']}"
    
    asyncio.create_task(send_telegram_message(master["telegram_id"], master_msg))
    asyncio.create_task(send_telegram_message(booking["client_telegram_id"], client_msg))
    logger.info(f"✅ Бронирование {booking_id} подтверждено")

async def create_ykassa_payment(amount: float, description: str, return_url: str, booking_id: int) -> dict:
    if not YKASSA_SHOP_ID or not YKASSA_SECRET_KEY:
        logger.warning("ЮKassa не настроена, тестовый режим")
        return {
            "confirmation_url": "https://yandex.ru",
            "payment_id": f"test_{booking_id}"
        }
    
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
                headers={
                    "Authorization": f"Basic {auth}",
                    "Content-Type": "application/json",
                    "Idempotence-Key": idempotence_key
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"✅ Платёж создан: {data['id']}")
                return {
                    "confirmation_url": data["confirmation"]["confirmation_url"],
                    "payment_id": data["id"]
                }
            else:
                logger.error(f"ЮKassa ошибка: {response.text}")
                return {
                    "confirmation_url": "https://yandex.ru",
                    "payment_id": f"error_{booking_id}"
                }
    except Exception as e:
        logger.error(f"Payment error: {e}")
        return {
            "confirmation_url": "https://yandex.ru",
            "payment_id": f"fallback_{booking_id}"
        }

# ========== ЭНДПОИНТЫ ==========

@app.get("/masters")
def get_masters(conn=Depends(get_db)):
    masters = conn.execute("SELECT * FROM masters").fetchall()
    result = []
    for m in masters:
        services = conn.execute("SELECT * FROM services WHERE master_id=?", (m["id"],)).fetchall()
        d = dict(m)
        d["services"] = [dict(s) for s in services]
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
    d = dict(m)
    d["services"] = [dict(s) for s in services]
    d["portfolio"] = [dict(p) for p in portfolio]
    return d

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
        # ПРЯМОЕ ДОБАВЛЕНИЕ КОЛОНОК (на случай если их нет)
        try:
            conn.execute("ALTER TABLE bookings ADD COLUMN deposit_amount REAL DEFAULT 0")
            logger.info("✅ deposit_amount добавлена")
        except: pass
        try:
            conn.execute("ALTER TABLE bookings ADD COLUMN total_amount REAL DEFAULT 0")
            logger.info("✅ total_amount добавлена")
        except: pass
        try:
            conn.execute("ALTER TABLE bookings ADD COLUMN payment_id TEXT")
            logger.info("✅ payment_id добавлена")
        except: pass
        conn.commit()
        
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
        
        deposit_amount = round(service["price"] * PAYMENT_COMMISSION, 2)
        total_with_commission = service["price"] + deposit_amount
        
        cur = conn.execute("""
            INSERT INTO bookings (master_id, service_id, client_name, client_telegram_id, client_phone, date, time, deposit_amount, total_amount)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (data.master_id, data.service_id, data.client_name, data.client_telegram_id, data.client_phone, data.date, data.time, deposit_amount, total_with_commission))
        conn.commit()
        booking_id = cur.lastrowid
        
        logger.info(f"📝 Бронь {booking_id}: {data.client_name} -> {service['name']} | Услуга: {service['price']} ₽ | Депозит 7%: {deposit_amount} ₽")
        
        payment = await create_ykassa_payment(
            amount=deposit_amount,
            description=f"Бронь услуги {service['name']} (депозит {deposit_amount}₽, остаток {service['price']}₽ мастеру)",
            return_url=f"{YKASSA_RETURN_URL}?booking_id={booking_id}",
            booking_id=booking_id
        )
        
        conn.execute("UPDATE bookings SET payment_id=? WHERE id=?", (payment["payment_id"], booking_id))
        conn.commit()
        
        master_msg = f"💳 *НОВАЯ ЗАЯВКА (ОЖИДАЕТ ОПЛАТЫ)* 💳\n\n👩 Клиент: {data.client_name}\n📞 Телефон: {data.client_phone or 'не указан'}\n💅 Услуга: {service['name']}\n💰 Стоимость услуги: {service['price']} ₽\n💸 Депозит 7%: {deposit_amount} ₽\n📅 Дата: {data.date}\n🕐 Время: {data.time}"
        asyncio.create_task(send_telegram_message(master["telegram_id"], master_msg))
        
        return {
            "booking_id": booking_id,
            "payment_url": payment["confirmation_url"],
            "deposit_amount": deposit_amount,
            "service_price": service["price"],
            "total_with_commission": total_with_commission,
            "status": "pending_payment"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        raise HTTPException(500, detail=str(e))
    finally:
        conn.close()

@app.post("/ykassa-webhook")
async def ykassa_webhook(notification: dict):
    logger.info(f"Webhook received")
    if notification.get("type") == "notification":
        payment_obj = notification.get("object", {})
        payment_id = payment_obj.get("id")
        payment_status = payment_obj.get("status")
        
        if payment_status == "succeeded":
            conn = get_db()
            try:
                booking = conn.execute("SELECT id FROM bookings WHERE payment_id=?", (payment_id,)).fetchone()
                if booking:
                    confirm_booking(booking["id"], conn)
                    logger.info(f"✅ Платёж {payment_id} успешен, запись {booking['id']} подтверждена")
            finally:
                conn.close()
    return {"status": "ok"}

# ========== ОТМЕНА ЗАПИСИ (ТОЛЬКО МАСТЕР) ==========
@app.patch("/bookings/{booking_id}/status")
def update_booking_status(booking_id: int, status: str, conn: sqlite3.Connection = Depends(get_db)):
    booking = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    if status not in ["confirmed", "cancelled"]:
        raise HTTPException(status_code=400, detail="Invalid status")
    
    conn.execute("UPDATE bookings SET status=? WHERE id=?", (status, booking_id))
    if status == "cancelled":
        conn.execute("UPDATE bookings SET cancelled_at = CURRENT_TIMESTAMP WHERE id=?", (booking_id,))
    conn.commit()
    
    if status == "cancelled":
        booking = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
        master = conn.execute("SELECT * FROM masters WHERE id=?", (booking["master_id"],)).fetchone()
        service = conn.execute("SELECT * FROM services WHERE id=?", (booking["service_id"],)).fetchone()
        
        client_msg = f"❌ *Запись отменена* мастером\n\n📅 Дата: {booking['date']}\n🕐 Время: {booking['time']}\n💅 Услуга: {service['name']}\n\n💸 Депозит будет возвращён в течение 3-7 дней."
        asyncio.create_task(send_telegram_message(booking["client_telegram_id"], client_msg))
    
    return {"status": "ok", "booking_id": booking_id, "new_status": status}

# ========== ШАБЛОНЫ ОТВЕТОВ ==========
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
@app.post("/master/{telegram_id}/portfolio")
async def add_portfolio_photo(telegram_id: str, photo_url: str = Form(...), description: str = Form(""), conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    conn.execute("INSERT INTO portfolio (master_id, photo_url, description) VALUES (?,?,?)",
                (master["id"], photo_url, description))
    conn.commit()
    return {"status": "ok", "message": "Фото добавлено в портфолио"}

@app.delete("/master/{telegram_id}/portfolio/{photo_id}")
def delete_portfolio_photo(telegram_id: str, photo_id: int, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    conn.execute("DELETE FROM portfolio WHERE id=? AND master_id=?", (photo_id, master["id"]))
    conn.commit()
    return {"status": "ok"}

# ========== ИЗБРАННЫЕ МАСТЕРА ==========
@app.post("/favorites/{master_id}")
def add_favorite(master_id: int, client_telegram_id: str, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("INSERT OR IGNORE INTO favorites (client_telegram_id, master_id) VALUES (?,?)",
                (client_telegram_id, master_id))
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
        WHERE f.client_telegram_id = ?
    """, (client_telegram_id,)).fetchall()
    return [dict(f) for f in favorites]

# ========== ОСТАЛЬНЫЕ ЭНДПОИНТЫ ==========

@app.get("/bookings/client/{telegram_id}")
def get_client_bookings(telegram_id: str, conn: sqlite3.Connection = Depends(get_db)):
    bookings = conn.execute("""
        SELECT b.*, m.name as master_name, s.name as service_name, s.price
        FROM bookings b JOIN masters m ON b.master_id=m.id JOIN services s ON b.service_id=s.id
        WHERE b.client_telegram_id=? ORDER BY b.date DESC, b.time DESC
    """, (telegram_id,)).fetchall()
    return [dict(b) for b in bookings]

@app.get("/bookings/master/{master_id}")
def get_master_bookings(master_id: int, conn: sqlite3.Connection = Depends(get_db)):
    bookings = conn.execute("""
        SELECT b.*, s.name as service_name, s.price
        FROM bookings b JOIN services s ON b.service_id=s.id
        WHERE b.master_id=? ORDER BY b.date DESC, b.time DESC
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
    return {"completed_bookings": confirmed, "pending_payment": pending, "revenue": revenue}

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

@app.patch("/master/{telegram_id}/work-hours")
def update_work_hours(telegram_id: str, data: WorkHoursUpdate, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("UPDATE masters SET work_start=?, work_end=? WHERE telegram_id=?", (data.work_start, data.work_end, telegram_id))
    conn.commit()
    return {"status": "ok"}

@app.patch("/master/{telegram_id}/location")
def update_location(telegram_id: str, data: LocationUpdate, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("UPDATE masters SET lat=?, lon=? WHERE telegram_id=?", (data.lat, data.lon, telegram_id))
    conn.commit()
    return {"status": "ok"}

@app.post("/user/register")
def register_user(data: UserRegister, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("INSERT OR IGNORE INTO users (telegram_id) VALUES (?)", (data.telegram_id,))
    conn.commit()
    return {"status": "ok"}

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

@app.post("/masters/{master_id}/days_off")
def add_day_off(master_id: int, date: str, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("INSERT OR IGNORE INTO days_off (master_id, date) VALUES (?,?)", (master_id, date))
    conn.commit()
    return {"status": "ok"}

@app.delete("/masters/{master_id}/days_off/{date}")
def remove_day_off(master_id: int, date: str, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("DELETE FROM days_off WHERE master_id=? AND date=?", (master_id, date))
    conn.commit()
    return {"status": "ok"}

@app.get("/")
def root():
    return {"status": "Beauty Bot API running 🌸", "version": "3.0.0"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
