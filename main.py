from fastapi import FastAPI, HTTPException, Depends, Request, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List
import sqlite3
import os
import httpx
import json
import secrets
import uuid
import base64
from datetime import datetime, timedelta
import asyncio
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Beauty Bot API", version="3.0.0")

# === КОНФИГУРАЦИЯ ЮKASSA ===
YKASSA_SHOP_ID = os.getenv("YKASSA_SHOP_ID", "1368786")
YKASSA_SECRET_KEY = os.getenv("YKASSA_SECRET_KEY", "live_aRHBYSr1irUAO8_dvzZCmQCih-vTF0q0NFfSvW5OOcs")
YKASSA_RETURN_URL = os.getenv("YKASSA_RETURN_URL", "https://t.me/pinkspotvelur_bot")
PAYMENT_COMMISSION = 0.07  # 7% от суммы чека
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
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"
    return response

@app.options("/{path:path}")
async def options_handler(path: str):
    return JSONResponse(
        content={"message": "OK"},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "*",
        },
    )

DB_PATH = "beauty.db"
DEFAULT_WORK_START = "09:00"
DEFAULT_WORK_END = "20:00"
SLOT_INTERVAL = 30

# ========== PYDANTIC МОДЕЛИ ==========
class ServiceOut(BaseModel):
    id: int
    master_id: int
    name: str
    price: int
    duration_min: int

class ServiceIn(BaseModel):
    name: str
    price: int
    duration_min: int

class MasterOut(BaseModel):
    id: int
    name: str
    photo_url: Optional[str]
    description: Optional[str]
    address: str
    lat: float
    lon: float
    phone: Optional[str]
    instagram: Optional[str]
    services: List[ServiceOut] = []
    bot_token: Optional[str] = None
    telegram_id: Optional[str] = None
    photos: Optional[List[str]] = None
    registered_at: Optional[str] = None
    rating: Optional[float] = 0
    work_start: Optional[str] = "09:00"
    work_end: Optional[str] = "20:00"
    icon: Optional[str] = "💅"
    completed_bookings: Optional[int] = 0

class MasterIn(BaseModel):
    name: str
    address: str
    lat: Optional[float] = 47.222078
    lon: Optional[float] = 39.720358
    phone: Optional[str] = ""
    instagram: Optional[str] = ""
    description: Optional[str] = ""
    icon: Optional[str] = "💅"
    telegram_id: Optional[str] = None
    work_start: Optional[str] = "09:00"
    work_end: Optional[str] = "20:00"

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
    message: Optional[str] = None
    photo_url: Optional[str] = None

class ReviewIn(BaseModel):
    master_id: int
    booking_id: int
    client_name: str
    rating: int
    comment: Optional[str] = None

class ReviewReply(BaseModel):
    reply: str

class LocationUpdate(BaseModel):
    lat: float
    lon: float

class WorkHoursUpdate(BaseModel):
    work_start: str
    work_end: str

class BotTokenUpdate(BaseModel):
    bot_token: str

class IconUpdate(BaseModel):
    icon: str

class TelegramIdUpdate(BaseModel):
    telegram_id: str

class UserRegister(BaseModel):
    telegram_id: str

class DayOffRequest(BaseModel):
    date: str

# ========== МИГРАЦИЯ БД ==========
def migrate_db():
    """Автоматическое добавление недостающих колонок"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("PRAGMA table_info(bookings)")
    existing_columns = [col[1] for col in c.fetchall()]
    
    required_columns = {
        "deposit_amount": "REAL DEFAULT 0",
        "payment_id": "TEXT",
        "ykassa_payment_id": "TEXT",
        "confirmed_at": "TEXT",
        "cancelled_at": "TEXT"
    }
    
    for col_name, col_type in required_columns.items():
        if col_name not in existing_columns:
            try:
                c.execute(f"ALTER TABLE bookings ADD COLUMN {col_name} {col_type}")
                logger.info(f"✅ Добавлена колонка {col_name} в bookings")
            except Exception as e:
                logger.warning(f"Не удалось добавить {col_name}: {e}")
    
    c.execute("PRAGMA table_info(masters)")
    master_columns = [col[1] for col in c.fetchall()]
    
    master_required = {
        "rating": "REAL DEFAULT 0",
        "icon": "TEXT DEFAULT '💅'",
        "work_start": "TEXT DEFAULT '09:00'",
        "work_end": "TEXT DEFAULT '20:00'"
    }
    
    for col_name, col_type in master_required.items():
        if col_name not in master_columns:
            try:
                c.execute(f"ALTER TABLE masters ADD COLUMN {col_name} {col_type}")
                logger.info(f"✅ Добавлена колонка {col_name} в masters")
            except Exception as e:
                logger.warning(f"Не удалось добавить {col_name}: {e}")
    
    conn.commit()
    conn.close()
    logger.info("✅ Миграция БД завершена")

# ========== ИНИЦИАЛИЗАЦИЯ БД ==========
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
            work_end TEXT DEFAULT '20:00',
            registered_at TEXT DEFAULT CURRENT_TIMESTAMP,
            bot_token TEXT,
            photos TEXT,
            rating REAL DEFAULT 0,
            icon TEXT DEFAULT '💅'
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
            status TEXT DEFAULT 'pending_payment',
            payment_status TEXT DEFAULT 'pending',
            deposit_amount REAL DEFAULT 0,
            payment_id TEXT,
            ykassa_payment_id TEXT,
            reminder_sent INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            confirmed_at TEXT,
            cancelled_at TEXT,
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
        CREATE TABLE IF NOT EXISTS chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER UNIQUE,
            master_id INTEGER,
            client_telegram_id TEXT,
            master_telegram_id TEXT,
            token TEXT UNIQUE,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (booking_id) REFERENCES bookings(id),
            FOREIGN KEY (master_id) REFERENCES masters(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            master_id INTEGER NOT NULL,
            booking_id INTEGER UNIQUE,
            client_name TEXT NOT NULL,
            rating INTEGER NOT NULL,
            comment TEXT,
            master_reply TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (master_id) REFERENCES masters(id),
            FOREIGN KEY (booking_id) REFERENCES bookings(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id TEXT UNIQUE NOT NULL,
            registered_at TEXT DEFAULT CURRENT_TIMESTAMP,
            name TEXT,
            phone TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            payment_id TEXT UNIQUE,
            ykassa_payment_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT,
            FOREIGN KEY (booking_id) REFERENCES bookings(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER NOT NULL,
            from_id TEXT NOT NULL,
            to_id TEXT NOT NULL,
            message TEXT,
            photo_url TEXT,
            is_read INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (booking_id) REFERENCES bookings(id)
        )
    """)

    conn.commit()
    conn.close()
    logger.info("✅ Таблицы БД созданы")

    migrate_db()
    fill_test_data()

def fill_test_data():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM masters")
    if c.fetchone()[0] == 0:
        masters_data = [
            ("Алина Козлова", None, "Мастер маникюра с 5-летним опытом\n🏆 Топ-мастер 2024\n💅 Работаю с премиальными материалами", "ул. Ленина, 12", 47.222078, 39.720358, "+79001234567", "@alina_nails", "💅"),
            ("Мария Иванова", None, "Профессиональный визажист и мастер бровей\n👁️ 1000+ довольных клиентов\n✨ Дневной и вечерний макияж", "пр. Мира, 45", 47.223078, 39.721358, "+79009876543", "@maria_beauty", "👁️"),
            ("Екатерина Смирнова", None, "Специалист по уходу за ресницами\n👀 Ламинирование, ботокс, наращивание\n🌿 Только качественные материалы", "ул. Садовая, 8", 47.221078, 39.719358, "+79005551234", "@kate_lashes", "👀"),
        ]
        c.executemany("INSERT INTO masters (name, photo_url, description, address, lat, lon, phone, instagram, icon) VALUES (?,?,?,?,?,?,?,?,?)", masters_data)
        
        c.execute("SELECT id FROM masters")
        ids = [row[0] for row in c.fetchall()]
        services = [
            (ids[0], "Маникюр классический", 1200, 60),
            (ids[0], "Маникюр с покрытием гель-лак", 2000, 90),
            (ids[0], "Педикюр", 2500, 120),
            (ids[0], "Снятие гель-лака", 500, 30),
            (ids[0], "Дизайн ногтей (1 рука)", 800, 45),
            (ids[1], "Макияж дневной", 2500, 60),
            (ids[1], "Коррекция бровей", 800, 30),
            (ids[1], "Макияж вечерний", 4000, 90),
            (ids[1], "Окрашивание бровей", 1000, 45),
            (ids[2], "Наращивание ресниц 2D", 3000, 120),
            (ids[2], "Ламинирование ресниц", 2500, 90),
            (ids[2], "Ботокс для ресниц", 2000, 60),
            (ids[2], "Снятие нарощенных ресниц", 500, 30),
        ]
        c.executemany("INSERT INTO services (master_id, name, price, duration_min) VALUES (?,?,?,?)", services)
        conn.commit()
        logger.info("✅ Добавлены тестовые мастера и услуги")
    
    conn.close()

init_db()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def generate_slots(work_start: str, work_end: str, interval: int = 30) -> List[str]:
    slots = []
    start = datetime.strptime(work_start, "%H:%M")
    end = datetime.strptime(work_end, "%H:%M")
    current = start
    while current < end:
        slots.append(current.strftime("%H:%M"))
        current += timedelta(minutes=interval)
    return slots

async def notify_master(master_bot_token: str, master_telegram_id: str, message: str):
    if not master_bot_token or not master_telegram_id:
        return
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{master_bot_token}/sendMessage",
                json={"chat_id": master_telegram_id, "text": message, "parse_mode": "Markdown"}
            )
    except Exception as e:
        logger.error(f"Notify error: {e}")

async def notify_client(bot_token: str, client_telegram_id: str, message: str):
    if not bot_token or not client_telegram_id:
        return
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": client_telegram_id, "text": message, "parse_mode": "Markdown"}
            )
    except Exception as e:
        logger.error(f"Notify client error: {e}")

def confirm_booking(booking_id: int, conn: sqlite3.Connection):
    """Подтверждение записи для обоих после успешной оплаты"""
    conn.execute(
        "UPDATE bookings SET status = 'confirmed', payment_status = 'paid', confirmed_at = CURRENT_TIMESTAMP WHERE id = ?",
        (booking_id,)
    )
    
    token = secrets.token_urlsafe(16)
    booking = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    master = conn.execute("SELECT * FROM masters WHERE id = ?", (booking["master_id"],)).fetchone()
    service = conn.execute("SELECT * FROM services WHERE id = ?", (booking["service_id"],)).fetchone()
    
    conn.execute("""
        INSERT OR IGNORE INTO chats (booking_id, master_id, client_telegram_id, master_telegram_id, token)
        VALUES (?, ?, ?, ?, ?)
    """, (booking_id, booking["master_id"], booking["client_telegram_id"], master["telegram_id"], token))
    conn.commit()
    
    master_msg = f"✅ *Запись подтверждена!*\n👩 Клиент: {booking['client_name']}\n💅 Услуга: {service['name']}\n💰 Сумма: {service['price']} ₽\n📅 {booking['date']} в {booking['time']}"
    client_msg = f"✅ *Запись подтверждена!*\n💅 Мастер: {master['name']}\n📍 {master['address']}\n💰 {service['price']} ₽\n📅 {booking['date']} в {booking['time']}\n\n🌸 Ждём вас!"
    
    asyncio.create_task(notify_master(master["bot_token"], master["telegram_id"], master_msg))
    asyncio.create_task(notify_client(master["bot_token"], booking["client_telegram_id"], client_msg))
    
    logger.info(f"✅ Booking {booking_id} confirmed")

# ========== ГЛАВНАЯ ФУНКЦИЯ ПЛАТЕЖА С ТЕСТОВЫМ РЕЖИМОМ ==========
async def create_ykassa_payment(amount: float, description: str, return_url: str, booking_id: int) -> dict:
    """Создание платежа в ЮKassa"""
    
    # 🔥 ТЕСТОВЫЙ РЕЖИМ - ВРЕМЕННО 🔥
    TEST_MODE = True  # <--- ПОСТАВЬ False когда заработает
    
    if TEST_MODE:
        logger.info(f"🧪 ТЕСТОВЫЙ РЕЖИМ: платёж на {amount}₽, booking_id={booking_id}")
        # Открываем Яндекс для проверки
        return {
            "confirmation_url": "https://yandex.ru",
            "payment_id": f"test_{booking_id}"
        }
    
    if not YKASSA_SHOP_ID or not YKASSA_SECRET_KEY:
        logger.warning("ЮKassa не настроена, тестовый режим")
        return {
            "confirmation_url": f"https://t.me/pinkspotvelur_bot?booking_id={booking_id}",
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
            
            logger.info(f"ЮKassa status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                if "confirmation" in data and "confirmation_url" in data["confirmation"]:
                    payment_url = data["confirmation"]["confirmation_url"]
                elif "confirmation_url" in data:
                    payment_url = data["confirmation_url"]
                else:
                    payment_url = f"https://t.me/pinkspotvelur_bot?booking_id={booking_id}"
                
                return {
                    "confirmation_url": payment_url,
                    "payment_id": data.get("id", f"pay_{booking_id}")
                }
            else:
                logger.error(f"ЮKassa ошибка {response.status_code}: {response.text}")
                return {
                    "confirmation_url": f"https://t.me/pinkspotvelur_bot?booking_id={booking_id}",
                    "payment_id": f"error_{booking_id}"
                }
    except Exception as e:
        logger.error(f"Payment error: {e}")
        return {
            "confirmation_url": f"https://t.me/pinkspotvelur_bot?booking_id={booking_id}",
            "payment_id": f"fallback_{booking_id}"
        }

# ========== ЭНДПОИНТЫ ==========

@app.get("/masters")
def get_masters(conn: sqlite3.Connection = Depends(get_db)):
    masters = conn.execute("SELECT * FROM masters ORDER BY rating DESC").fetchall()
    result = []
    for m in masters:
        completed = conn.execute("SELECT COUNT(*) FROM bookings WHERE master_id = ? AND status = 'confirmed'", (m["id"],)).fetchone()[0]
        services = conn.execute("SELECT * FROM services WHERE master_id = ?", (m["id"],)).fetchall()
        master_dict = dict(m)
        master_dict["photos"] = json.loads(master_dict["photos"]) if master_dict.get("photos") else []
        master_dict["services"] = [dict(s) for s in services]
        master_dict["completed_bookings"] = completed
        result.append(master_dict)
    return result

@app.get("/masters/{master_id}")
def get_master(master_id: int, conn: sqlite3.Connection = Depends(get_db)):
    m = conn.execute("SELECT * FROM masters WHERE id = ?", (master_id,)).fetchone()
    if not m:
        raise HTTPException(404, "Master not found")
    completed = conn.execute("SELECT COUNT(*) FROM bookings WHERE master_id = ? AND status = 'confirmed'", (master_id,)).fetchone()[0]
    services = conn.execute("SELECT * FROM services WHERE master_id = ?", (master_id,)).fetchall()
    master_dict = dict(m)
    master_dict["photos"] = json.loads(master_dict["photos"]) if master_dict.get("photos") else []
    master_dict["services"] = [dict(s) for s in services]
    master_dict["completed_bookings"] = completed
    return master_dict

@app.get("/masters/by_telegram/{telegram_id}")
def get_master_by_telegram(telegram_id: str, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT * FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    return dict(master)

@app.post("/masters")
def add_master(master: MasterIn, conn: sqlite3.Connection = Depends(get_db)):
    cursor = conn.execute(
        """INSERT INTO masters (name, address, lat, lon, phone, instagram, description, icon, telegram_id, work_start, work_end, registered_at) 
           VALUES (?,?,?,?,?,?,?,?,?,?,?, CURRENT_TIMESTAMP)""",
        (master.name, master.address, master.lat, master.lon, master.phone, master.instagram, master.description, master.icon, master.telegram_id, master.work_start, master.work_end)
    )
    conn.commit()
    return {"status": "ok", "master_id": cursor.lastrowid}

@app.delete("/masters/{master_id}")
def delete_master(master_id: int, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("DELETE FROM services WHERE master_id = ?", (master_id,))
    conn.execute("DELETE FROM bookings WHERE master_id = ?", (master_id,))
    conn.execute("DELETE FROM days_off WHERE master_id = ?", (master_id,))
    conn.execute("DELETE FROM reviews WHERE master_id = ?", (master_id,))
    conn.execute("DELETE FROM masters WHERE id = ?", (master_id,))
    conn.commit()
    return {"status": "ok"}

@app.patch("/masters/{master_id}/telegram")
def set_master_telegram(master_id: int, data: TelegramIdUpdate, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("UPDATE masters SET telegram_id = ? WHERE id = ?", (data.telegram_id, master_id))
    conn.commit()
    return {"status": "ok"}

@app.patch("/masters/{master_id}/bot-token")
def set_master_bot_token(master_id: int, data: BotTokenUpdate, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("UPDATE masters SET bot_token = ? WHERE id = ?", (data.bot_token, master_id))
    conn.commit()
    return {"status": "ok"}

@app.patch("/masters/{master_id}/icon")
def set_master_icon(master_id: int, data: IconUpdate, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("UPDATE masters SET icon = ? WHERE id = ?", (data.icon, master_id))
    conn.commit()
    return {"status": "ok"}

@app.patch("/master/{telegram_id}/location")
def update_master_location(telegram_id: str, data: LocationUpdate, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("UPDATE masters SET lat = ?, lon = ? WHERE telegram_id = ?", (data.lat, data.lon, telegram_id))
    conn.commit()
    return {"status": "ok"}

@app.patch("/master/{telegram_id}/work-hours")
def update_work_hours(telegram_id: str, data: WorkHoursUpdate, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("UPDATE masters SET work_start = ?, work_end = ? WHERE telegram_id = ?", (data.work_start, data.work_end, telegram_id))
    conn.commit()
    return {"status": "ok"}

@app.get("/masters/{master_id}/slots")
def get_free_slots(master_id: int, date: str, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT * FROM masters WHERE id = ?", (master_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    
    day_off = conn.execute("SELECT id FROM days_off WHERE master_id=? AND date=?", (master_id, date)).fetchone()
    if day_off:
        return {"date": date, "slots": [], "day_off": True}
    
    work_start = master["work_start"] or DEFAULT_WORK_START
    work_end = master["work_end"] or DEFAULT_WORK_END
    all_slots = generate_slots(work_start, work_end)
    
    booked = conn.execute("SELECT time FROM bookings WHERE master_id=? AND date=? AND status IN ('pending_payment', 'confirmed')", (master_id, date)).fetchall()
    booked_times = {b["time"] for b in booked}
    
    today = datetime.now().strftime("%Y-%m-%d")
    now_time = datetime.now().strftime("%H:%M")
    
    free_slots = [s for s in all_slots if s not in booked_times and not (date == today and s <= now_time)]
    return {"date": date, "slots": free_slots, "day_off": False}

@app.post("/masters/{master_id}/days_off")
def add_day_off(master_id: int, data: DayOffRequest, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("INSERT OR IGNORE INTO days_off (master_id, date) VALUES (?,?)", (master_id, data.date))
    conn.commit()
    return {"status": "ok"}

@app.delete("/masters/{master_id}/days_off/{date}")
def remove_day_off(master_id: int, date: str, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("DELETE FROM days_off WHERE master_id=? AND date=?", (master_id, date))
    conn.commit()
    return {"status": "ok"}

@app.get("/master/{telegram_id}/services")
def get_master_services(telegram_id: str, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id = ?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    services = conn.execute("SELECT * FROM services WHERE master_id = ? ORDER BY price", (master["id"],)).fetchall()
    return [dict(s) for s in services]

@app.post("/master/{telegram_id}/services")
def add_master_service(telegram_id: str, data: ServiceIn, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id = ?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    cursor = conn.execute("INSERT INTO services (master_id, name, price, duration_min) VALUES (?, ?, ?, ?)", (master["id"], data.name, data.price, data.duration_min))
    conn.commit()
    return {"status": "ok", "service_id": cursor.lastrowid}

@app.delete("/master/{telegram_id}/services/{service_id}")
def delete_master_service(telegram_id: str, service_id: int, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id = ?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    conn.execute("DELETE FROM services WHERE id = ? AND master_id = ?", (service_id, master["id"]))
    conn.commit()
    return {"status": "ok"}

# ========== ОСНОВНОЙ ЭНДПОИНТ ЗАПИСИ ==========

@app.post("/bookings")
async def create_booking(data: BookingIn):
    conn = get_db()
    try:
        master = conn.execute("SELECT * FROM masters WHERE id = ?", (data.master_id,)).fetchone()
        if not master:
            raise HTTPException(404, "Master not found")
        
        service = conn.execute("SELECT * FROM services WHERE id=? AND master_id=?", (data.service_id, data.master_id)).fetchone()
        if not service:
            raise HTTPException(404, "Service not found")
        
        day_off = conn.execute("SELECT id FROM days_off WHERE master_id=? AND date=?", (data.master_id, data.date)).fetchone()
        if day_off:
            raise HTTPException(409, "Master is off this day")
        
        existing = conn.execute("SELECT id FROM bookings WHERE master_id=? AND date=? AND time=? AND status IN ('pending_payment', 'confirmed')", (data.master_id, data.date, data.time)).fetchone()
        if existing:
            raise HTTPException(409, "This time slot is already booked")
        
        deposit_amount = round(service["price"] * PAYMENT_COMMISSION, 2)
        
        cursor = conn.execute(
            "INSERT INTO bookings (master_id, service_id, client_name, client_telegram_id, client_phone, date, time, status, deposit_amount) VALUES (?,?,?,?,?,?,?, 'pending_payment', ?)",
            (data.master_id, data.service_id, data.client_name, data.client_telegram_id, data.client_phone, data.date, data.time, deposit_amount)
        )
        conn.commit()
        booking_id = cursor.lastrowid
        
        logger.info(f"Booking {booking_id} created for {data.client_name}")
        
        payment_result = await create_ykassa_payment(
            amount=deposit_amount,
            description=f"Бронь услуги {service['name']} ({deposit_amount}₽ из {service['price']}₽)",
            return_url=f"{YKASSA_RETURN_URL}?booking_id={booking_id}",
            booking_id=booking_id
        )
        
        conn.execute("UPDATE bookings SET payment_id = ?, ykassa_payment_id = ? WHERE id = ?", (payment_result["payment_id"], payment_result["payment_id"], booking_id))
        conn.execute("INSERT INTO payments (booking_id, amount, status, payment_id, ykassa_payment_id) VALUES (?, ?, 'pending', ?, ?)", (booking_id, deposit_amount, payment_result["payment_id"], payment_result["payment_id"]))
        conn.commit()
        
        master_msg = f"💳 *Новая заявка*\n👩 {data.client_name}\n💅 {service['name']}\n💰 {service['price']} ₽ (депозит {deposit_amount}₽)\n📅 {data.date} в {data.time}"
        await notify_master(master["bot_token"], master["telegram_id"], master_msg)
        
        return {
            "booking_id": booking_id,
            "payment_url": payment_result["confirmation_url"],
            "deposit_amount": deposit_amount,
            "total_price": service["price"],
            "status": "pending_payment"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Create booking error: {e}")
        raise HTTPException(500, detail=str(e))
    finally:
        conn.close()

# ========== ВЕБХУК ЮKASSA ==========

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
                booking = conn.execute("SELECT id FROM bookings WHERE ykassa_payment_id = ? OR payment_id = ?", (payment_id, payment_id)).fetchone()
                if booking:
                    conn.execute("UPDATE payments SET status = 'paid', completed_at = CURRENT_TIMESTAMP WHERE payment_id = ? OR ykassa_payment_id = ?", (payment_id, payment_id))
                    confirm_booking(booking["id"], conn)
                    logger.info(f"✅ Booking {booking['id']} confirmed")
            finally:
                conn.close()
    
    return {"status": "ok"}

# ========== ОСТАЛЬНЫЕ ЭНДПОИНТЫ ==========

@app.get("/bookings/client/{telegram_id}")
def get_client_bookings(telegram_id: str, conn: sqlite3.Connection = Depends(get_db)):
    bookings = conn.execute(
        """SELECT b.*, m.name as master_name, m.address, s.name as service_name, s.price
           FROM bookings b JOIN masters m ON b.master_id=m.id JOIN services s ON b.service_id=s.id
           WHERE b.client_telegram_id=? ORDER BY b.date DESC, b.time DESC""",
        (telegram_id,)
    ).fetchall()
    return [dict(b) for b in bookings]

@app.get("/master/{telegram_id}/bookings")
def get_master_bookings_web(telegram_id: str, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id = ?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    bookings = conn.execute(
        "SELECT b.*, s.name as service_name, s.price FROM bookings b JOIN services s ON b.service_id=s.id WHERE b.master_id = ? ORDER BY b.date DESC, b.time DESC",
        (master["id"],)
    ).fetchall()
    return [dict(b) for b in bookings]

@app.get("/master/{telegram_id}/stats")
def get_master_stats(telegram_id: str, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id = ?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    
    confirmed = conn.execute("SELECT COUNT(*) FROM bookings WHERE master_id = ? AND status = 'confirmed'", (master["id"],)).fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM bookings WHERE master_id = ? AND status = 'pending_payment'", (master["id"],)).fetchone()[0]
    revenue = conn.execute("SELECT SUM(s.price) FROM bookings b JOIN services s ON b.service_id=s.id WHERE b.master_id = ? AND b.status = 'confirmed'", (master["id"],)).fetchone()[0] or 0
    
    return {"completed_bookings": confirmed, "pending_payment": pending, "revenue": revenue, "total": confirmed + pending}

@app.post("/chat/send")
def send_message(data: MessageIn, conn: sqlite3.Connection = Depends(get_db)):
    booking = conn.execute("SELECT status FROM bookings WHERE id = ?", (data.booking_id,)).fetchone()
    if not booking or booking["status"] != "confirmed":
        raise HTTPException(403, "Chat available only after payment")
    conn.execute("INSERT INTO chat_messages (booking_id, from_id, to_id, message, photo_url) VALUES (?, ?, ?, ?, ?)", (data.booking_id, data.from_id, data.to_id, data.message, data.photo_url))
    conn.commit()
    return {"status": "ok"}

@app.get("/chat/messages/{booking_id}")
def get_chat_messages(booking_id: int, user_id: str, conn: sqlite3.Connection = Depends(get_db)):
    booking = conn.execute("SELECT b.client_telegram_id, m.telegram_id as master_telegram_id FROM bookings b LEFT JOIN masters m ON b.master_id = m.id WHERE b.id = ?", (booking_id,)).fetchone()
    if not booking or (user_id != booking["client_telegram_id"] and user_id != booking["master_telegram_id"]):
        return []
    messages = conn.execute("SELECT * FROM chat_messages WHERE booking_id = ? ORDER BY created_at ASC", (booking_id,)).fetchall()
    return [dict(m) for m in messages]

@app.post("/reviews")
def create_review(data: ReviewIn, conn: sqlite3.Connection = Depends(get_db)):
    existing = conn.execute("SELECT id FROM reviews WHERE booking_id = ?", (data.booking_id,)).fetchone()
    if existing:
        raise HTTPException(400, "Review already exists")
    conn.execute("INSERT INTO reviews (master_id, booking_id, client_name, rating, comment) VALUES (?, ?, ?, ?, ?)", (data.master_id, data.booking_id, data.client_name, data.rating, data.comment))
    conn.commit()
    conn.execute("UPDATE masters SET rating = (SELECT AVG(rating) FROM reviews WHERE master_id = ?) WHERE id = ?", (data.master_id, data.master_id))
    conn.commit()
    return {"status": "ok"}

@app.get("/reviews/master/{master_id}")
def get_master_reviews(master_id: int, conn: sqlite3.Connection = Depends(get_db)):
    reviews = conn.execute("SELECT * FROM reviews WHERE master_id = ? ORDER BY created_at DESC", (master_id,)).fetchall()
    return [dict(r) for r in reviews]

@app.post("/user/register")
def register_user(data: UserRegister, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("INSERT OR IGNORE INTO users (telegram_id) VALUES (?)", (data.telegram_id,))
    conn.commit()
    return {"status": "ok"}

@app.get("/payment-status/{booking_id}")
def get_payment_status(booking_id: int, conn: sqlite3.Connection = Depends(get_db)):
    booking = conn.execute("SELECT status, payment_status, deposit_amount FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    if not booking:
        raise HTTPException(404, "Booking not found")
    return dict(booking)

@app.get("/")
def root():
    return {"status": "Beauty Bot API running 🌸", "version": "3.0.0", "payment_commission": "7%"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
