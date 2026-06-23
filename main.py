from fastapi import FastAPI, HTTPException, Depends, Request, Form, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List
import sqlite3
import httpx
import json
import secrets
import uuid
import base64
import shutil
import os
import requests
from datetime import datetime, timedelta
import asyncio
import logging
import traceback

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Beauty Bot API", version="3.0.0")

# === КОНФИГУРАЦИЯ ===
YKASSA_SHOP_ID = os.getenv("YKASSA_SHOP_ID", "1368786")
YKASSA_SECRET_KEY = os.getenv("YKASSA_SECRET_KEY", "live_aRHBYSr1irUAO8_dvzZCmQCih-vTF0q0NFfSvW5OOcs")
YKASSA_RETURN_URL = os.getenv("YKASSA_RETURN_URL", "https://t.me/pinkspotvelur_bot")
PAYMENT_COMMISSION = 0.07
CLEANING_TIME = 15
MASTER_BOT_TOKEN = os.getenv("MASTER_BOT_TOKEN", "8236516081:AAFjIjQBiAMs95XpURSCZZhuuYr5yDrcmlw")

# ✅ ТВОЙ TELEGRAM ID (для уведомлений админу)
ADMIN_CHAT_ID = "868528632"

# === ПУТЬ К БАЗЕ ===
DB_PATH = os.path.join(os.getcwd(), "data", "beauty.db")
PHOTO_DIR = os.path.join(os.getcwd(), "data", "photos")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
os.makedirs(PHOTO_DIR, exist_ok=True)

app.mount("/photos", StaticFiles(directory=PHOTO_DIR), name="photos")

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
    return JSONResponse(
        content={"message": "OK"}, 
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "*",
            "Access-Control-Allow-Headers": "*"
        }
    )

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

class ReviewIn(BaseModel):
    master_id: int
    booking_id: int
    client_name: str
    rating: int
    comment: Optional[str] = None

class WaitlistIn(BaseModel):
    master_id: int
    service_id: int
    client_telegram_id: str
    client_name: str
    desired_date: Optional[str] = None
    desired_time: Optional[str] = None

# ========== БД ==========
def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("""CREATE TABLE IF NOT EXISTS masters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT DEFAULT '',
        address TEXT DEFAULT '',
        lat REAL DEFAULT 47.222078,
        lon REAL DEFAULT 39.720358,
        phone TEXT DEFAULT '',
        instagram TEXT DEFAULT '',
        telegram_id TEXT UNIQUE,
        work_start TEXT DEFAULT '09:00',
        work_end TEXT DEFAULT '20:00',
        bot_token TEXT DEFAULT '',
        description TEXT DEFAULT '',
        icon TEXT DEFAULT '💅',
        rating REAL DEFAULT 0,
        avatar TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS services (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        master_id INTEGER,
        name TEXT,
        price INTEGER,
        duration_min INTEGER
    )""")
    
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
        payment_status TEXT DEFAULT 'pending',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        confirmed_at TEXT,
        cancelled_at TEXT,
        reminder_24h_sent INTEGER DEFAULT 0,
        reminder_1h_sent INTEGER DEFAULT 0,
        reminder_sent INTEGER DEFAULT 0,
        sms_sent INTEGER DEFAULT 0,
        review_given INTEGER DEFAULT 0
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS days_off (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        master_id INTEGER,
        date TEXT,
        UNIQUE(master_id, date)
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS chats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        booking_id INTEGER UNIQUE,
        master_id INTEGER,
        client_telegram_id TEXT,
        master_telegram_id TEXT,
        token TEXT UNIQUE
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS chat_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        booking_id INTEGER,
        from_id TEXT,
        to_id TEXT,
        message TEXT,
        is_read INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id TEXT UNIQUE,
        registered_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS quick_replies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        master_id INTEGER,
        title TEXT,
        message TEXT
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS portfolio (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        master_id INTEGER,
        photo_url TEXT,
        description TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS master_before_after (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        master_id INTEGER,
        before_photo TEXT,
        after_photo TEXT,
        description TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS favorites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_telegram_id TEXT,
        master_id INTEGER,
        UNIQUE(client_telegram_id, master_id)
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS blacklist (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        master_id INTEGER,
        client_telegram_id TEXT,
        reason TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS promocodes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE,
        discount INTEGER,
        expires_at TEXT,
        uses_limit INTEGER DEFAULT 1,
        used_count INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        master_id INTEGER,
        booking_id INTEGER,
        client_name TEXT,
        rating INTEGER,
        comment TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (master_id) REFERENCES masters(id),
        FOREIGN KEY (booking_id) REFERENCES bookings(id)
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS waitlist (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        master_id INTEGER,
        service_id INTEGER,
        client_telegram_id TEXT,
        client_name TEXT,
        desired_date TEXT,
        desired_time TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        notified INTEGER DEFAULT 0,
        FOREIGN KEY (master_id) REFERENCES masters(id),
        FOREIGN KEY (service_id) REFERENCES services(id)
    )""")
    
    for col in ['reminder_24h_sent', 'reminder_1h_sent', 'reminder_sent']:
        try:
            c.execute(f"ALTER TABLE bookings ADD COLUMN {col} INTEGER DEFAULT 0")
        except: pass
    
    for col in ['avatar']:
        try:
            c.execute(f"ALTER TABLE masters ADD COLUMN {col} TEXT")
        except: pass
    
    for col in ['payment_status']:
        try:
            c.execute(f"ALTER TABLE bookings ADD COLUMN {col} TEXT DEFAULT 'pending'")
        except: pass
    
    for col in ['review_given']:
        try:
            c.execute(f"ALTER TABLE bookings ADD COLUMN {col} INTEGER DEFAULT 0")
        except: pass
    
    try:
        c.execute("ALTER TABLE masters ADD COLUMN created_at TEXT DEFAULT CURRENT_TIMESTAMP")
    except: pass
    
    c.execute("SELECT COUNT(*) FROM masters")
    count = c.fetchone()[0]
    if count == 0:
        logger.info("🔄 БД пуста, добавляем тестового мастера...")
        c.execute("""INSERT INTO masters (name, address, lat, lon, phone, instagram, telegram_id, icon, work_start, work_end, bot_token, description) 
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                  ("Алина Козлова", "ул. Ленина, 12", 47.222078, 39.720358, "+79001234567", "@alina_nails", "868528632", "💅", "09:00", "20:00", MASTER_BOT_TOKEN, "Мастер маникюра с 5-летним опытом"))
        c.execute("SELECT id FROM masters WHERE telegram_id = '868528632'")
        master_id = c.fetchone()[0]
        c.execute("INSERT INTO services (master_id, name, price, duration_min) VALUES (?,?,?,?)", (master_id, "Маникюр классический", 1200, 60))
        c.execute("INSERT INTO services (master_id, name, price, duration_min) VALUES (?,?,?,?)", (master_id, "Маникюр с покрытием гель-лак", 2000, 90))
        c.execute("INSERT INTO services (master_id, name, price, duration_min) VALUES (?,?,?,?)", (master_id, "Педикюр", 2500, 120))
        
        c.execute("INSERT INTO portfolio (master_id, photo_url, description) VALUES (?, ?, ?)", 
                  (master_id, "/photos/test1.jpg", "Маникюр с дизайном 🌸"))
        c.execute("INSERT INTO portfolio (master_id, photo_url, description) VALUES (?, ?, ?)", 
                  (master_id, "/photos/test2.jpg", "Френч с блестками ✨"))
        c.execute("INSERT INTO portfolio (master_id, photo_url, description) VALUES (?, ?, ?)", 
                  (master_id, "/photos/test3.jpg", "Маникюр в нюдовых тонах 💅"))
        
        logger.info("✅ Тестовый мастер и портфолио добавлены")
    else:
        logger.info(f"✅ БД уже содержит {count} мастеров, ничего не удаляем")
    
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
    
    if booked_slots is None:
        booked_slots = []
    
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

# ========== ФУНКЦИИ ДЛЯ ОТПРАВКИ В TELEGRAM ==========
async def send_telegram_message(chat_id: str, message: str, parse_mode: str = "Markdown"):
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{MASTER_BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": message, "parse_mode": parse_mode}
            )
            if response.status_code == 200:
                logger.info(f"✅ Сообщение отправлено в Telegram: {chat_id}")
            else:
                logger.error(f"❌ Ошибка: {response.status_code}")
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")

def send_telegram_message_sync(chat_id: str, message: str, parse_mode: str = "Markdown"):
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{MASTER_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": parse_mode},
            timeout=10
        )
        if response.status_code == 200:
            logger.info(f"✅ Сообщение отправлено в Telegram: {chat_id}")
        else:
            logger.error(f"❌ Ошибка: {response.status_code} - {response.text}")
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")

# ========== АВТОМАТИЧЕСКИЕ УВЕДОМЛЕНИЯ ==========
def get_all_masters_telegram_ids(conn):
    """Автоматически получает Telegram ID всех мастеров из БД"""
    try:
        masters = conn.execute(
            "SELECT id, name, telegram_id FROM masters WHERE telegram_id IS NOT NULL AND telegram_id != ''"
        ).fetchall()
        return [dict(m) for m in masters]
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return []

def send_notification_to_all_masters(message: str, conn):
    """Автоматически отправляет уведомление ВСЕМ мастерам из БД"""
    try:
        masters = get_all_masters_telegram_ids(conn)
        if not masters:
            logger.warning("⚠️ Нет мастеров в БД")
            return 0
        
        sent_count = 0
        for master in masters:
            if master.get("telegram_id"):
                send_telegram_message_sync(master["telegram_id"], message)
                sent_count += 1
                logger.info(f"✅ Уведомление отправлено мастеру {master['name']}")
        
        logger.info(f"✅ Уведомления отправлены {sent_count} мастерам")
        return sent_count
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return 0

def send_notification_to_admin_sync(message: str):
    """Отправка уведомления админу (тебе)"""
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{MASTER_BOT_TOKEN}/sendMessage",
            json={"chat_id": ADMIN_CHAT_ID, "text": message, "parse_mode": "Markdown"},
            timeout=10
        )
        if response.status_code == 200:
            logger.info(f"✅ Уведомление отправлено админу {ADMIN_CHAT_ID}")
            return True
        else:
            logger.error(f"❌ Ошибка: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return False

# ========== СОЗДАНИЕ ПЛАТЕЖА ==========
async def create_ykassa_payment(amount: float, description: str, return_url: str, booking_id: int) -> dict:
    if not YKASSA_SHOP_ID or not YKASSA_SECRET_KEY:
        logger.warning("⚠️ ЮKassa не настроена, тестовый режим")
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
                headers={
                    "Authorization": f"Basic {auth}",
                    "Content-Type": "application/json",
                    "Idempotence-Key": idempotence_key
                }
            )
            if response.status_code == 200:
                data = response.json()
                return {"confirmation_url": data["confirmation"]["confirmation_url"], "payment_id": data["id"]}
            else:
                return {"confirmation_url": "https://yandex.ru", "payment_id": f"error_{booking_id}"}
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return {"confirmation_url": "https://yandex.ru", "payment_id": f"fallback_{booking_id}"}

# ========== ПОДТВЕРЖДЕНИЕ БРОНИ ==========
def confirm_booking(booking_id: int, conn: sqlite3.Connection):
    try:
        booking = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
        if not booking:
            logger.error(f"❌ Бронь {booking_id} не найдена")
            return
        
        if booking["status"] == "confirmed":
            logger.info(f"ℹ️ Бронь {booking_id} уже подтверждена")
            return
        
        master = conn.execute("SELECT * FROM masters WHERE id=?", (booking["master_id"],)).fetchone()
        service = conn.execute("SELECT * FROM services WHERE id=?", (booking["service_id"],)).fetchone()
        
        if not master or not service:
            logger.error(f"❌ Мастер или услуга не найдены")
            return
        
        conn.execute("UPDATE bookings SET status='confirmed', confirmed_at=CURRENT_TIMESTAMP WHERE id=?", (booking_id,))
        conn.commit()
        
        token = secrets.token_urlsafe(16)
        conn.execute("INSERT OR IGNORE INTO chats (booking_id, master_id, client_telegram_id, master_telegram_id, token) VALUES (?,?,?,?,?)",
                    (booking_id, master["id"], booking["client_telegram_id"], master["telegram_id"], token))
        conn.commit()
        
        # ✅ УВЕДОМЛЕНИЕ МАСТЕРУ
        master_msg = f"""🌸 *НОВАЯ ЗАПИСЬ ПОДТВЕРЖДЕНА!* 🌸

👩 {booking['client_name']}
📞 {booking['client_phone'] or 'не указан'}
💅 {service['name']}
💰 {service['price']} ₽
💸 Депозит: {booking['deposit_amount']} ₽
📅 {booking['date']} в {booking['time']}"""
        
        if master.get("telegram_id"):
            send_telegram_message_sync(master["telegram_id"], master_msg)
        
        # ✅ УВЕДОМЛЕНИЕ КЛИЕНТУ
        client_msg = f"""🌸 *ЗАПИСЬ ПОДТВЕРЖДЕНА!* 🌸

💅 {master['name']}
📍 {master['address']}
💅 {service['name']}
💰 {service['price']} ₽
💸 Оплачено: {booking['deposit_amount']} ₽
📅 {booking['date']} в {booking['time']}"""
        
        if booking.get("client_telegram_id"):
            send_telegram_message_sync(booking["client_telegram_id"], client_msg)
        
        # ✅ АВТОМАТИЧЕСКОЕ УВЕДОМЛЕНИЕ ВСЕМ МАСТЕРАМ
        all_masters_msg = f"""🌸 *НОВАЯ ОПЛАЧЕННАЯ ЗАПИСЬ!* 🌸

👤 Клиент: {booking['client_name']}
💅 Услуга: {service['name']}
💰 {service['price']} ₽
📅 {booking['date']}
⏰ {booking['time']}
👩‍💼 Мастер: {master['name']}
🆔 ID: {booking_id}"""
        
        send_notification_to_all_masters(all_masters_msg, conn)
        
        # ✅ УВЕДОМЛЕНИЕ АДМИНУ (ТЕБЕ)
        admin_msg = f"""🌸 *НОВАЯ ОПЛАЧЕННАЯ ЗАПИСЬ!* 🌸

👤 Клиент: {booking['client_name']}
💅 Услуга: {service['name']}
💰 {service['price']} ₽
📅 {booking['date']}
⏰ {booking['time']}
👩‍💼 Мастер: {master['name']}
🆔 ID: {booking_id}"""
        
        send_notification_to_admin_sync(admin_msg)
        
        logger.info(f"✅ Бронь {booking_id} подтверждена")
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        traceback.print_exc()

# ========== НАПОМИНАНИЯ ==========
async def send_reminders():
    conn = get_db()
    try:
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        
        reminders_24h = conn.execute("""
            SELECT b.*, m.name as master_name, m.address, s.name as service_name
            FROM bookings b
            JOIN masters m ON b.master_id = m.id
            JOIN services s ON b.service_id = s.id
            WHERE b.status = 'confirmed' AND b.date = ? AND b.reminder_24h_sent = 0
        """, (tomorrow,)).fetchall()
        
        for b in reminders_24h:
            msg = f"🌸 *Напоминание о записи!* 🌸\n\nЗавтра в *{b['time']}* у вас запись к {b['master_name']} на *{b['service_name']}*.\n📍 Адрес: {b['address']}\n\nЖдём вас! 🎀"
            await send_telegram_message(b['client_telegram_id'], msg)
            conn.execute("UPDATE bookings SET reminder_24h_sent = 1 WHERE id = ?", (b['id'],))
        
        hour_later = (now + timedelta(hours=1)).strftime("%H:%M")
        reminders_1h = conn.execute("""
            SELECT b.*, m.name as master_name, s.name as service_name
            FROM bookings b
            JOIN masters m ON b.master_id = m.id
            JOIN services s ON b.service_id = s.id
            WHERE b.status = 'confirmed' AND b.date = ? AND b.time = ? AND b.reminder_1h_sent = 0
        """, (today, hour_later)).fetchall()
        
        for b in reminders_1h:
            msg = f"🌸 *Скоро запись!* 🌸\n\nЧерез час у вас запись к {b['master_name']} на *{b['service_name']}*.\n\nНе опаздывайте! 🚗"
            await send_telegram_message(b['client_telegram_id'], msg)
            conn.execute("UPDATE bookings SET reminder_1h_sent = 1 WHERE id = ?", (b['id'],))
        
        conn.commit()
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
    finally:
        conn.close()

async def check_repeat_reminders():
    conn = get_db()
    try:
        bookings = conn.execute("""
            SELECT b.*, s.name as service_name, m.name as master_name
            FROM bookings b
            JOIN services s ON b.service_id = s.id
            JOIN masters m ON b.master_id = m.id
            WHERE b.status = 'confirmed' 
            AND b.date <= date('now', '-20 days')
            AND b.date >= date('now', '-25 days')
            AND b.reminder_sent = 0
        """).fetchall()
        
        for b in bookings:
            days_ago = (datetime.now() - datetime.strptime(b['date'], "%Y-%m-%d")).days
            msg = f"💅 *Пора повторить!* 💅\n\n{b['service_name']} вы делали {days_ago} дней назад.\n✨ *Время обновить!* Запишитесь прямо сейчас!"
            await send_telegram_message(b['client_telegram_id'], msg)
            conn.execute("UPDATE bookings SET reminder_sent = 1 WHERE id = ?", (b['id'],))
        
        conn.commit()
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
    finally:
        conn.close()

async def run_background_tasks():
    while True:
        await send_reminders()
        await asyncio.sleep(1800)

async def run_daily_tasks():
    while True:
        await check_repeat_reminders()
        await asyncio.sleep(86400)

@app.on_event("startup")
async def start_background_tasks():
    asyncio.create_task(run_background_tasks())
    asyncio.create_task(run_daily_tasks())

# ========== ОСНОВНЫЕ ЭНДПОИНТЫ ==========

@app.get("/masters")
def get_masters(conn=Depends(get_db)):
    masters = conn.execute("SELECT * FROM masters WHERE name != '' AND address != ''").fetchall()
    result = []
    for m in masters:
        services = conn.execute("SELECT * FROM services WHERE master_id=?", (m["id"],)).fetchall()
        reviews_count = conn.execute("SELECT COUNT(*) FROM reviews WHERE master_id=?", (m["id"],)).fetchone()[0] or 0
        d = dict(m)
        d["services"] = [dict(s) for s in services]
        d["reviews_count"] = reviews_count
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
    reviews = conn.execute("SELECT * FROM reviews WHERE master_id=? ORDER BY created_at DESC LIMIT 10", (master_id,)).fetchall()
    reviews_count = conn.execute("SELECT COUNT(*) FROM reviews WHERE master_id=?", (master_id,)).fetchone()[0] or 0
    d = dict(m)
    d["services"] = [dict(s) for s in services]
    d["portfolio"] = [dict(p) for p in portfolio]
    d["reviews"] = [dict(r) for r in reviews]
    d["reviews_count"] = reviews_count
    return d

@app.get("/masters/{master_id}/portfolio")
def get_master_portfolio(master_id: int, conn: sqlite3.Connection = Depends(get_db)):
    try:
        portfolio = conn.execute("""
            SELECT id, photo_url, description, created_at
            FROM portfolio 
            WHERE master_id = ? 
            ORDER BY created_at DESC
        """, (master_id,)).fetchall()
        return [dict(p) for p in portfolio]
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        return []

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

# ========== СОЗДАНИЕ БРОНИ ==========
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
        
        deposit_amount = round(service["price"] * PAYMENT_COMMISSION, 2)
        total_with_commission = service["price"] + deposit_amount
        
        cur = conn.execute("""
            INSERT INTO bookings (master_id, service_id, client_name, client_telegram_id, client_phone, date, time, deposit_amount, total_amount, payment_status)
            VALUES (?,?,?,?,?,?,?,?,?, 'pending')
        """, (data.master_id, data.service_id, data.client_name, data.client_telegram_id, data.client_phone, data.date, data.time, deposit_amount, total_with_commission))
        conn.commit()
        booking_id = cur.lastrowid
        
        logger.info(f"📝 Бронь {booking_id}: {data.client_name} -> {service['name']}")
        
        payment = await create_ykassa_payment(
            amount=deposit_amount,
            description=f"Бронь {service['name']} (депозит {deposit_amount}₽)",
            return_url=f"{YKASSA_RETURN_URL}?booking_id={booking_id}",
            booking_id=booking_id
        )
        
        conn.execute("UPDATE bookings SET payment_id=? WHERE id=?", (payment["payment_id"], booking_id))
        conn.commit()
        
        # ✅ УВЕДОМЛЕНИЕ МАСТЕРУ
        master_msg = f"💳 *НОВАЯ ЗАЯВКА* 💳\n\n👩 {data.client_name}\n📞 {data.client_phone or 'не указан'}\n💅 {service['name']}\n💰 {service['price']} ₽\n💸 Депозит: {deposit_amount} ₽\n📅 {data.date} в {data.time}"
        asyncio.create_task(send_telegram_message(master["telegram_id"], master_msg))
        
        # ✅ АВТОМАТИЧЕСКОЕ УВЕДОМЛЕНИЕ ВСЕМ МАСТЕРАМ
        all_masters_msg = f"""💳 *НОВАЯ ЗАЯВКА НА ЗАПИСЬ!* 💳

👤 Клиент: {data.client_name}
💅 Услуга: {service['name']}
💰 {service['price']} ₽
💸 Депозит: {deposit_amount} ₽
📅 {data.date}
⏰ {data.time}
👩‍💼 Мастер: {master['name']}
🆔 ID: {booking_id}

📌 Статус: ОЖИДАЕТ ОПЛАТЫ ⏳"""
        
        send_notification_to_all_masters(all_masters_msg, conn)
        
        # ✅ УВЕДОМЛЕНИЕ АДМИНУ (ТЕБЕ)
        admin_msg = f"""💳 *НОВАЯ ЗАЯВКА НА ЗАПИСЬ!* 💳

👤 Клиент: {data.client_name}
💅 Услуга: {service['name']}
💰 {service['price']} ₽
💸 Депозит: {deposit_amount} ₽
📅 {data.date}
⏰ {data.time}
👩‍💼 Мастер: {master['name']}
🆔 ID: {booking_id}

📌 Статус: ОЖИДАЕТ ОПЛАТЫ ⏳"""
        
        asyncio.create_task(send_telegram_message(ADMIN_CHAT_ID, admin_msg))
        
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

@app.post("/payment-callback")
def payment_callback(data: dict, conn: sqlite3.Connection = Depends(get_db)):
    booking_id = data.get("booking_id")
    payment_id = data.get("payment_id")
    
    if not booking_id:
        return {"status": "error", "message": "booking_id required"}
    
    booking = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    if not booking:
        return {"status": "error", "message": "Booking not found"}
    
    if booking["status"] == "confirmed":
        return {"status": "ok", "message": "Already confirmed"}
    
    try:
        conn.execute("""
            UPDATE bookings 
            SET status = 'confirmed', 
                payment_status = 'paid',
                confirmed_at = CURRENT_TIMESTAMP,
                payment_id = ?
            WHERE id = ?
        """, (payment_id or booking["payment_id"], booking_id))
        conn.commit()
        confirm_booking(booking_id, conn)
        return {"status": "ok", "message": "Payment confirmed"}
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/ykassa-webhook")
async def ykassa_webhook(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    try:
        body = await request.body()
        raw_body = body.decode('utf-8')
        
        try:
            notification = json.loads(raw_body)
        except:
            return {"status": "error", "detail": "Invalid JSON"}
        
        event_type = notification.get("event")
        
        if event_type == "payment.succeeded":
            metadata = notification.get("object", {}).get("metadata", {})
            booking_id = metadata.get("booking_id")
            
            if booking_id:
                booking = conn.execute("SELECT id, status FROM bookings WHERE id = ?", (booking_id,)).fetchone()
                if booking and booking["status"] != "confirmed":
                    conn.execute("UPDATE bookings SET status='confirmed', confirmed_at=CURRENT_TIMESTAMP WHERE id=?", (booking_id,))
                    conn.commit()
                    confirm_booking(booking_id, conn)
                    logger.info(f"✅ [WEBHOOK] Бронь {booking_id} подтверждена!")
    except Exception as e:
        logger.error(f"❌ [WEBHOOK] Ошибка: {e}")
    
    return {"status": "ok"}

@app.patch("/bookings/{booking_id}/status")
def update_booking_status(booking_id: int, status: str, conn: sqlite3.Connection = Depends(get_db)):
    booking = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
    if not booking:
        raise HTTPException(404, "Booking not found")
    
    if status not in ["confirmed", "cancelled"]:
        raise HTTPException(400, "Invalid status")
    
    conn.execute("UPDATE bookings SET status=? WHERE id=?", (status, booking_id))
    if status == "cancelled":
        conn.execute("UPDATE bookings SET cancelled_at = CURRENT_TIMESTAMP WHERE id=?", (booking_id,))
        check_waitlist(booking["master_id"], booking["service_id"], booking["date"], conn)
    conn.commit()
    
    if status == "cancelled":
        booking = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
        service = conn.execute("SELECT * FROM services WHERE id=?", (booking["service_id"],)).fetchone()
        client_msg = f"❌ *Запись отменена*\n\n📅 {booking['date']} в {booking['time']}\n💅 {service['name']}\n\n💸 Депозит вернётся в течение 3-7 дней."
        asyncio.create_task(send_telegram_message(booking["client_telegram_id"], client_msg))
    
    return {"status": "ok"}

def check_waitlist(master_id: int, service_id: int, date: str, conn: sqlite3.Connection):
    waitlist = conn.execute("""
        SELECT * FROM waitlist 
        WHERE master_id = ? AND service_id = ? AND notified = 0 
        ORDER BY created_at ASC LIMIT 1
    """, (master_id, service_id)).fetchone()
    
    if waitlist:
        msg = f"🌸 *Слот освободился!* 🌸\n\nНа {date} появилось свободное время! Спешите записаться!"
        asyncio.create_task(send_telegram_message(waitlist["client_telegram_id"], msg))
        conn.execute("UPDATE waitlist SET notified = 1 WHERE id = ?", (waitlist["id"],))
        conn.commit()

# ========== ОТЗЫВЫ ==========
@app.post("/reviews")
def submit_review(data: ReviewIn, conn: sqlite3.Connection = Depends(get_db)):
    try:
        logger.info(f"📝 Получен отзыв: {data}")
        
        booking = conn.execute("SELECT * FROM bookings WHERE id = ?", (data.booking_id,)).fetchone()
        if not booking:
            raise HTTPException(404, "Запись не найдена")
        
        existing = conn.execute("SELECT id FROM reviews WHERE booking_id = ?", (data.booking_id,)).fetchone()
        if existing:
            raise HTTPException(400, "Отзыв уже оставлен")
        
        if booking["status"] != "confirmed":
            raise HTTPException(400, "Отзыв можно оставить только после подтверждённой записи")
        
        master = conn.execute("SELECT id FROM masters WHERE id = ?", (data.master_id,)).fetchone()
        if not master:
            raise HTTPException(404, "Мастер не найден")
        
        conn.execute("""
            INSERT INTO reviews (master_id, booking_id, client_name, rating, comment)
            VALUES (?, ?, ?, ?, ?)
        """, (data.master_id, data.booking_id, data.client_name, data.rating, data.comment))
        conn.commit()
        
        conn.execute("""
            UPDATE masters SET rating = (
                SELECT AVG(rating) FROM reviews WHERE master_id = ?
            ) WHERE id = ?
        """, (data.master_id, data.master_id))
        conn.commit()
        
        conn.execute("UPDATE bookings SET review_given = 1 WHERE id = ?", (data.booking_id,))
        conn.commit()
        
        logger.info(f"✅ Отзыв сохранён для booking_id={data.booking_id}")
        return {"status": "ok", "message": "Спасибо за отзыв! ❤️"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        raise HTTPException(500, detail=str(e))

@app.get("/reviews/master/{master_id}")
def get_master_reviews(master_id: int, conn: sqlite3.Connection = Depends(get_db)):
    reviews = conn.execute("""
        SELECT * FROM reviews WHERE master_id = ? ORDER BY created_at DESC LIMIT 20
    """, (master_id,)).fetchall()
    return [dict(r) for r in reviews]

# ========== ЛИСТ ОЖИДАНИЯ ==========
@app.post("/waitlist")
def add_to_waitlist(data: WaitlistIn, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("""
        INSERT INTO waitlist (master_id, service_id, client_telegram_id, client_name, desired_date, desired_time)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (data.master_id, data.service_id, data.client_telegram_id, data.client_name, data.desired_date, data.desired_time))
    conn.commit()
    return {"status": "ok", "message": "Вы добавлены в лист ожидания. Мы уведомим вас при освобождении слота! 🌸"}

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

# ========== АВАТАР ==========
@app.post("/master/{telegram_id}/upload-avatar")
async def upload_avatar(telegram_id: str, file: UploadFile = File(...)):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    try:
        master = conn.execute("SELECT id FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
        if not master:
            raise HTTPException(404, "Master not found")
        
        if not file.content_type.startswith('image/'):
            raise HTTPException(400, "File must be an image")
        
        file.file.seek(0, 2)
        size = file.file.tell()
        file.file.seek(0)
        if size > 5 * 1024 * 1024:
            raise HTTPException(400, "File too large (max 5MB)")
        
        ext = file.filename.split(".")[-1] if "." in file.filename else "jpg"
        filename = f"avatar_{master['id']}_{int(datetime.now().timestamp())}.{ext}"
        filepath = os.path.join(PHOTO_DIR, filename)
        
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        avatar_url = f"/photos/{filename}"
        conn.execute("UPDATE masters SET avatar = ? WHERE id = ?", (avatar_url, master["id"]))
        conn.commit()
        
        return {"avatar_url": avatar_url, "status": "ok"}
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        raise HTTPException(500, str(e))
    finally:
        conn.close()

@app.get("/master/{telegram_id}/avatar")
def get_avatar(telegram_id: str, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT avatar FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master or not master["avatar"]:
        return {"avatar_url": None}
    return {"avatar_url": master["avatar"]}

# ========== ПОРТФОЛИО ==========
@app.get("/master/{telegram_id}/portfolio")
def get_portfolio(telegram_id: str, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    rows = conn.execute("SELECT id, photo_url, description FROM portfolio WHERE master_id = ? ORDER BY created_at DESC", (master["id"],)).fetchall()
    return [dict(r) for r in rows]

@app.post("/master/{telegram_id}/upload-portfolio")
async def upload_portfolio(telegram_id: str, file: UploadFile = File(...), description: str = Form("")):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    try:
        master = conn.execute("SELECT id FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
        if not master:
            raise HTTPException(404, "Master not found")
        
        if not file.content_type.startswith('image/'):
            raise HTTPException(400, "File must be an image")
        
        file.file.seek(0, 2)
        size = file.file.tell()
        file.file.seek(0)
        if size > 10 * 1024 * 1024:
            raise HTTPException(400, "File too large (max 10MB)")
        
        ext = file.filename.split(".")[-1] if "." in file.filename else "jpg"
        filename = f"portfolio_{master['id']}_{int(datetime.now().timestamp())}.{ext}"
        filepath = os.path.join(PHOTO_DIR, filename)
        
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        photo_url = f"/photos/{filename}"
        conn.execute("INSERT INTO portfolio (master_id, photo_url, description) VALUES (?, ?, ?)", (master["id"], photo_url, description))
        conn.commit()
        
        return {"photo_url": photo_url, "status": "ok"}
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        raise HTTPException(500, str(e))
    finally:
        conn.close()

@app.delete("/master/{telegram_id}/portfolio/{photo_id}")
def delete_portfolio_photo(telegram_id: str, photo_id: int, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    
    photo = conn.execute("SELECT photo_url FROM portfolio WHERE id = ? AND master_id = ?", (photo_id, master["id"])).fetchone()
    if photo and photo["photo_url"]:
        filename = photo["photo_url"].replace("/photos/", "")
        filepath = os.path.join(PHOTO_DIR, filename)
        if os.path.exists(filepath):
            os.remove(filepath)
    
    conn.execute("DELETE FROM portfolio WHERE id = ? AND master_id = ?", (photo_id, master["id"]))
    conn.commit()
    return {"status": "ok"}

# ========== ПОРТФОЛИО "ДО/ПОСЛЕ" ==========
@app.get("/masters/{master_id}/before-after")
def get_before_after(master_id: int, conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute("""
        SELECT id, before_photo, after_photo, description
        FROM master_before_after
        WHERE master_id = ?
        ORDER BY created_at DESC
    """, (master_id,)).fetchall()
    return [dict(r) for r in rows]

@app.post("/master/{telegram_id}/before-after")
async def add_before_after(telegram_id: str, data: dict):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    try:
        master = conn.execute("SELECT id FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
        if not master:
            raise HTTPException(404, "Master not found")
        
        conn.execute("""
            INSERT INTO master_before_after (master_id, before_photo, after_photo, description)
            VALUES (?, ?, ?, ?)
        """, (master["id"], data["before_photo"], data["after_photo"], data.get("description", "")))
        conn.commit()
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        raise HTTPException(500, str(e))
    finally:
        conn.close()

@app.delete("/master/{telegram_id}/before-after/{item_id}")
def delete_before_after(telegram_id: str, item_id: int, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    conn.execute("DELETE FROM master_before_after WHERE id = ? AND master_id = ?", (item_id, master["id"]))
    conn.commit()
    return {"status": "ok"}

# ========== ДНИ ОТДЫХА ==========
@app.get("/masters/{master_id}/days_off")
def get_days_off(master_id: int, conn: sqlite3.Connection = Depends(get_db)):
    try:
        rows = conn.execute("SELECT date FROM days_off WHERE master_id = ? ORDER BY date", (master_id,)).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        return []

@app.post("/masters/{master_id}/days_off")
def add_day_off(master_id: int, date: str, conn: sqlite3.Connection = Depends(get_db)):
    try:
        conn.execute("INSERT OR IGNORE INTO days_off (master_id, date) VALUES (?, ?)", (master_id, date))
        conn.commit()
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        raise HTTPException(500, str(e))

@app.delete("/masters/{master_id}/days_off/{date}")
def remove_day_off(master_id: int, date: str, conn: sqlite3.Connection = Depends(get_db)):
    try:
        conn.execute("DELETE FROM days_off WHERE master_id = ? AND date = ?", (master_id, date))
        conn.commit()
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        raise HTTPException(500, str(e))

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
        JOIN masters m ON b.master_id=m.id 
        JOIN services s ON b.service_id=s.id
        LEFT JOIN reviews r ON r.booking_id = b.id
        WHERE b.client_telegram_id=? 
        ORDER BY b.date DESC, b.time DESC
    """, (telegram_id,)).fetchall()
    return [dict(b) for b in bookings]

@app.get("/bookings/master/{master_id}")
def get_master_bookings(master_id: int, date: str = None, conn: sqlite3.Connection = Depends(get_db)):
    if date:
        bookings = conn.execute("""
            SELECT b.*, s.name as service_name, s.price
            FROM bookings b JOIN services s ON b.service_id=s.id
            WHERE b.master_id=? AND b.date=? ORDER BY b.time
        """, (master_id, date)).fetchall()
    else:
        bookings = conn.execute("""
            SELECT b.*, s.name as service_name, s.price
            FROM bookings b JOIN services s ON b.service_id=s.id
            WHERE b.master_id=? AND b.date >= date('now') ORDER BY b.date, b.time
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
    rating = conn.execute("SELECT AVG(rating) FROM reviews WHERE master_id=?", (master["id"],)).fetchone()[0] or 0
    return {"completed": confirmed, "pending": pending, "revenue": revenue, "rating": round(rating, 1)}

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
    telegram_id = data.get("telegram_id", "").strip()
    if not telegram_id:
        raise HTTPException(400, "Telegram ID обязателен")
    
    existing = conn.execute("SELECT id FROM masters WHERE telegram_id = ?", (telegram_id,)).fetchone()
    if existing:
        raise HTTPException(400, f"Мастер с ID {telegram_id} уже существует")
    
    conn.execute("""
        INSERT INTO masters (telegram_id, name, address, lat, lon, phone, instagram, description, icon, work_start, work_end, bot_token)
        VALUES (?, 'Новый мастер', '', 47.222078, 39.720358, '', '', '', '💅', '09:00', '20:00', '')
    """, (telegram_id,))
    conn.commit()
    
    master_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    return {"status": "ok", "master_id": master_id, "telegram_id": telegram_id}

@app.post("/admin/add-master-full")
def admin_add_master_full(data: dict, conn: sqlite3.Connection = Depends(get_db)):
    try:
        name = data.get("name", "").strip()
        address = data.get("address", "").strip()
        phone = data.get("phone", "").strip()
        instagram = data.get("instagram", "").strip()
        description = data.get("description", "").strip()
        telegram_id = data.get("telegram_id", "").strip()
        
        if not name:
            raise HTTPException(400, "Имя обязательно")
        if not telegram_id:
            raise HTTPException(400, "Telegram ID обязателен")
        
        existing = conn.execute("SELECT id FROM masters WHERE telegram_id = ?", (telegram_id,)).fetchone()
        if existing:
            raise HTTPException(400, f"Мастер с Telegram ID {telegram_id} уже существует")
        
        conn.execute("""
            INSERT INTO masters (name, address, phone, instagram, description, telegram_id, lat, lon, icon, work_start, work_end)
            VALUES (?, ?, ?, ?, ?, ?, 47.222078, 39.720358, '💅', '09:00', '20:00')
        """, (name, address, phone, instagram, description, telegram_id))
        conn.commit()
        
        master_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        
        return {
            "status": "ok", 
            "master_id": master_id, 
            "telegram_id": telegram_id,
            "name": name,
            "message": f"Мастер {name} успешно добавлен!"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        raise HTTPException(500, detail=str(e))

@app.get("/admin/masters")
def admin_get_masters(conn: sqlite3.Connection = Depends(get_db)):
    masters = conn.execute("""
        SELECT id, telegram_id, name, phone, icon,
               CASE WHEN name = 'Новый мастер' OR name = '' THEN 'Не заполнен' ELSE 'Заполнен' END as status
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
    conn.execute("DELETE FROM master_before_after WHERE master_id = ?", (master_id,))
    conn.execute("DELETE FROM favorites WHERE master_id = ?", (master_id,))
    conn.execute("DELETE FROM blacklist WHERE master_id = ?", (master_id,))
    conn.execute("DELETE FROM reviews WHERE master_id = ?", (master_id,))
    conn.execute("DELETE FROM waitlist WHERE master_id = ?", (master_id,))
    conn.execute("DELETE FROM masters WHERE id = ?", (master_id,))
    conn.commit()
    return {"status": "ok"}

@app.get("/admin/stats")
def admin_get_stats(conn: sqlite3.Connection = Depends(get_db)):
    masters = conn.execute("SELECT COUNT(*) FROM masters").fetchone()[0]
    bookings = conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
    confirmed = conn.execute("SELECT COUNT(*) FROM bookings WHERE status='confirmed'").fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM bookings WHERE status='pending_payment'").fetchone()[0]
    reviews = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
    revenue = conn.execute("SELECT SUM(price) FROM bookings b JOIN services s ON b.service_id=s.id WHERE b.status='confirmed'").fetchone()[0] or 0
    return {"masters": masters, "total_bookings": bookings, "confirmed": confirmed, "pending": pending, "reviews": reviews, "revenue": revenue}

# ========== ПРОВЕРКА ПЛАТЕЖА ==========
@app.post("/bookings/{booking_id}/check-payment")
def check_payment(booking_id: int, conn: sqlite3.Connection = Depends(get_db)):
    try:
        logger.info(f"🔍 Проверка платежа для booking_id={booking_id}")
        
        booking = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        if not booking:
            raise HTTPException(404, "Booking not found")
        
        if booking["status"] == "confirmed":
            return {"status": "confirmed", "booking_id": booking_id, "payment_status": booking.get("payment_status", "paid")}
        
        if booking["payment_id"] and booking["payment_id"].startswith('test_'):
            conn.execute("UPDATE bookings SET status='confirmed', payment_status='paid', confirmed_at=CURRENT_TIMESTAMP WHERE id=?", (booking_id,))
            conn.commit()
            confirm_booking(booking_id, conn)
            return {"status": "confirmed", "booking_id": booking_id}
        
        if booking["payment_id"] and not booking["payment_id"].startswith('error_'):
            try:
                auth = base64.b64encode(f"{YKASSA_SHOP_ID}:{YKASSA_SECRET_KEY}".encode()).decode()
                with httpx.Client(timeout=10.0) as client:
                    response = client.get(
                        f"https://api.yookassa.ru/v3/payments/{booking['payment_id']}",
                        headers={"Authorization": f"Basic {auth}"}
                    )
                    if response.status_code == 200:
                        data = response.json()
                        if data.get("status") == "succeeded":
                            conn.execute("UPDATE bookings SET status='confirmed', payment_status='paid', confirmed_at=CURRENT_TIMESTAMP WHERE id=?", (booking_id,))
                            conn.commit()
                            confirm_booking(booking_id, conn)
                            return {"status": "confirmed", "booking_id": booking_id}
                        else:
                            return {"status": booking["status"], "booking_id": booking_id, "payment_status": data.get("status")}
            except Exception as e:
                logger.error(f"❌ Ошибка: {e}")
        
        return {"status": booking["status"], "booking_id": booking_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        raise HTTPException(500, detail=str(e))

# ========== ДОПОЛНИТЕЛЬНЫЕ ЭНДПОИНТЫ ==========
@app.post("/masters")
def create_master(data: dict, conn: sqlite3.Connection = Depends(get_db)):
    telegram_id = data.get("telegram_id")
    name = data.get("name", "Новый мастер")
    lat = data.get("lat", 47.222078)
    lon = data.get("lon", 39.720358)
    description = data.get("description", "")
    
    if telegram_id:
        existing = conn.execute("SELECT id FROM masters WHERE telegram_id = ?", (telegram_id,)).fetchone()
        if existing:
            raise HTTPException(400, f"Мастер с Telegram ID {telegram_id} уже существует")
    
    cur = conn.execute("INSERT INTO masters (telegram_id, name, lat, lon, description) VALUES (?, ?, ?, ?, ?)", (telegram_id, name, lat, lon, description))
    conn.commit()
    master_id = cur.lastrowid
    return {"id": master_id, "status": "created"}

@app.patch("/masters/{master_id}")
def update_master_admin(master_id: int, data: dict, conn: sqlite3.Connection = Depends(get_db)):
    updates = []
    params = []
    
    if "telegram_id" in data and data["telegram_id"]:
        updates.append("telegram_id = ?")
        params.append(data["telegram_id"])
    if "name" in data and data["name"]:
        updates.append("name = ?")
        params.append(data["name"])
    if "description" in data:
        updates.append("description = ?")
        params.append(data["description"])
    
    if updates:
        params.append(master_id)
        conn.execute(f"UPDATE masters SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
    
    return {"status": "updated"}

@app.delete("/masters/{master_id}")
def delete_master_admin(master_id: int, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("DELETE FROM services WHERE master_id = ?", (master_id,))
    conn.execute("DELETE FROM bookings WHERE master_id = ?", (master_id,))
    conn.execute("DELETE FROM days_off WHERE master_id = ?", (master_id,))
    conn.execute("DELETE FROM quick_replies WHERE master_id = ?", (master_id,))
    conn.execute("DELETE FROM portfolio WHERE master_id = ?", (master_id,))
    conn.execute("DELETE FROM master_before_after WHERE master_id = ?", (master_id,))
    conn.execute("DELETE FROM favorites WHERE master_id = ?", (master_id,))
    conn.execute("DELETE FROM blacklist WHERE master_id = ?", (master_id,))
    conn.execute("DELETE FROM reviews WHERE master_id = ?", (master_id,))
    conn.execute("DELETE FROM waitlist WHERE master_id = ?", (master_id,))
    conn.execute("DELETE FROM masters WHERE id = ?", (master_id,))
    conn.commit()
    return {"status": "deleted"}

@app.post("/promocodes")
def create_promocode(data: dict, conn: sqlite3.Connection = Depends(get_db)):
    code = data.get("code", "").upper()
    discount_percent = data.get("discount_percent")
    expires_at = data.get("expires_at")
    max_uses = data.get("max_uses", 100)
    
    if not code or not discount_percent or not expires_at:
        raise HTTPException(400, "code, discount_percent, expires_at required")
    
    conn.execute("INSERT OR REPLACE INTO promocodes (code, discount, expires_at, uses_limit, used_count) VALUES (?, ?, ?, ?, 0)", (code, discount_percent, expires_at, max_uses))
    conn.commit()
    return {"status": "created"}

@app.get("/promocodes")
def get_promocodes(conn: sqlite3.Connection = Depends(get_db)):
    promos = conn.execute("SELECT * FROM promocodes ORDER BY created_at DESC").fetchall()
    return [dict(p) for p in promos]

@app.get("/client/profile/{telegram_id}")
def get_client_profile(telegram_id: str, conn: sqlite3.Connection = Depends(get_db)):
    bookings = conn.execute("""
        SELECT COUNT(*) as total, 
               SUM(CASE WHEN status = 'confirmed' THEN 1 ELSE 0 END) as confirmed,
               SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) as cancelled
        FROM bookings WHERE client_telegram_id = ?
    """, (telegram_id,)).fetchone()
    
    next_booking = conn.execute("""
        SELECT b.*, m.name as master_name, s.name as service_name
        FROM bookings b
        JOIN masters m ON b.master_id = m.id
        JOIN services s ON b.service_id = s.id
        WHERE b.client_telegram_id = ? AND b.status = 'confirmed' AND b.date >= date('now')
        ORDER BY b.date ASC, b.time ASC LIMIT 1
    """, (telegram_id,)).fetchone()
    
    recent = conn.execute("""
        SELECT b.*, m.name as master_name, s.name as service_name
        FROM bookings b
        JOIN masters m ON b.master_id = m.id
        JOIN services s ON b.service_id = s.id
        WHERE b.client_telegram_id = ? AND b.status = 'confirmed'
        ORDER BY b.date DESC, b.time DESC LIMIT 5
    """, (telegram_id,)).fetchall()
    
    return {
        "stats": dict(bookings) if bookings else {"total": 0, "confirmed": 0, "cancelled": 0},
        "next_booking": dict(next_booking) if next_booking else None,
        "recent_bookings": [dict(r) for r in recent],
        "level": "Новичок",
        "level_discount": 0,
        "level_badge": "🌱"
    }

@app.get("/api/reminder")
def test_reminder_endpoint():
    return {"status": "ok", "message": "Reminder endpoint works"}

@app.post("/api/reminder")
async def send_reminder_api(data: dict):
    user_id = data.get("user_id")
    hours_before = data.get("hours_before")
    message = data.get("message")
    logger.info(f"REMINDER: to {user_id} ({hours_before}h): {message}")
    if user_id:
        await send_telegram_message(str(user_id), message)
    return {"status": "sent"}

@app.post("/api/waitlist/add")
def add_waitlist_api(data: dict, conn: sqlite3.Connection = Depends(get_db)):
    user_id = data.get("user_id")
    service = data.get("service")
    master_id = data.get("master_id")
    conn.execute("INSERT OR IGNORE INTO waitlist (client_telegram_id, service_id, master_id, desired_date) VALUES (?, ?, ?, date('now'))", (user_id, None, master_id))
    conn.commit()
    return {"status": "added"}

@app.post("/api/review")
def add_review_api(data: dict, conn: sqlite3.Connection = Depends(get_db)):
    user_id = data.get("user_id")
    master_id = data.get("master_id")
    rating = data.get("rating")
    comment = data.get("comment", "")
    conn.execute("INSERT INTO reviews (master_id, client_name, rating, comment) VALUES (?, ?, ?, ?)", (master_id, str(user_id), rating, comment))
    conn.commit()
    conn.execute("UPDATE masters SET rating = (SELECT AVG(rating) FROM reviews WHERE master_id = ?) WHERE id = ?", (master_id, master_id))
    conn.commit()
    return {"status": "created"}

@app.post("/api/repeat/trigger")
async def repeat_trigger_api(data: dict):
    user_id = data.get("user_id")
    msg = "💅 *Пора повторить процедуру!* 💅\n\nВы делали маникюр 3 недели назад. Время обновить покрытие! Запишитесь прямо сейчас! 🌸"
    if user_id:
        await send_telegram_message(str(user_id), msg)
    return {"status": "triggered"}

@app.get("/bookings/{booking_id}")
def get_booking(booking_id: int, conn: sqlite3.Connection = Depends(get_db)):
    booking = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
    if not booking:
        raise HTTPException(404, "Booking not found")
    return dict(booking)

@app.post("/bookings/{booking_id}/confirm")
async def confirm_booking_by_id(booking_id: int):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        booking = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
        if not booking:
            raise HTTPException(404, "Booking not found")
        if booking["status"] == "confirmed":
            return {"status": "already_confirmed", "booking_id": booking_id}
        confirm_booking(booking_id, conn)
        return {"status": "confirmed", "booking_id": booking_id}
    finally:
        conn.close()

@app.get("/health")
def health_check():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}

@app.get("/")
def root():
    return {"status": "Beauty Bot API running 🌸", "version": "3.0.0"}

@app.get("/photos/{filename}")
async def get_photo(filename: str):
    file_path = os.path.join(PHOTO_DIR, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path)
    raise HTTPException(404, "Photo not found")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True, log_level="info")
