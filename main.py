from fastapi import FastAPI, HTTPException, Depends, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
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

app = FastAPI(title="Beauty Bot API")

# ========== НАСТРОЙКИ ==========
YKASSA_SHOP_ID = os.getenv("YKASSA_SHOP_ID", "ТВОЙ_SHOP_ID")
YKASSA_SECRET_KEY = os.getenv("YKASSA_SECRET_KEY", "ТВОЙ_SECRET_KEY")
YKASSA_API_URL = "https://api.yookassa.ru/v3/payments"
COMMISSION_PERCENT = 7
DB_PATH = "beauty.db"
MASTER_BOT_TOKEN = os.getenv("MASTER_BOT_TOKEN", "8236516081:AAFjIjQBiAMs95XpURSCZZhuuYr5yDrcmlw")
DEFAULT_WORK_START = "09:00"
DEFAULT_WORK_END = "20:00"

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

# ========== МОДЕЛИ ==========
class ServiceOut(BaseModel):
    id: int
    master_id: int
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

class BookingIn(BaseModel):
    master_id: int
    service_id: int
    client_name: str
    client_telegram_id: str
    client_phone: Optional[str]
    date: str
    time: str

class PaymentRequest(BaseModel):
    booking_id: int
    return_url: Optional[str] = None

# ========== ИНИЦИАЛИЗАЦИЯ БД (С СОХРАНЕНИЕМ ДАННЫХ) ==========
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Таблица мастеров
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

    # Таблица услуг
    c.execute("""
        CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            master_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            duration_min INTEGER NOT NULL,
            FOREIGN KEY (master_id) REFERENCES masters(id) ON DELETE CASCADE
        )
    """)

    # Таблица записей
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
            payment_status TEXT DEFAULT 'pending',
            commission_amount REAL DEFAULT 0,
            commission_payment_id TEXT,
            reminder_sent INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (master_id) REFERENCES masters(id) ON DELETE CASCADE,
            FOREIGN KEY (service_id) REFERENCES services(id) ON DELETE CASCADE
        )
    """)

    # Таблица выходных дней
    c.execute("""
        CREATE TABLE IF NOT EXISTS days_off (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            master_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            UNIQUE(master_id, date),
            FOREIGN KEY (master_id) REFERENCES masters(id) ON DELETE CASCADE
        )
    """)

    # Таблица чатов
    c.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER UNIQUE,
            master_id INTEGER,
            client_telegram_id TEXT,
            master_telegram_id TEXT,
            token TEXT UNIQUE,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (booking_id) REFERENCES bookings(id) ON DELETE CASCADE,
            FOREIGN KEY (master_id) REFERENCES masters(id) ON DELETE CASCADE
        )
    """)

    # Таблица отзывов
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
            FOREIGN KEY (master_id) REFERENCES masters(id) ON DELETE CASCADE,
            FOREIGN KEY (booking_id) REFERENCES bookings(id) ON DELETE CASCADE
        )
    """)

    # Таблица пользователей
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id TEXT UNIQUE NOT NULL,
            registered_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Таблица платежей
    c.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            payment_id TEXT UNIQUE,
            payment_url TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (booking_id) REFERENCES bookings(id) ON DELETE CASCADE
        )
    """)

    # Таблица сообщений чата
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
            FOREIGN KEY (booking_id) REFERENCES bookings(id) ON DELETE CASCADE
        )
    """)

    # Добавляем недостающие колонки (если их нет)
    for col in ["rating REAL DEFAULT 0", "icon TEXT DEFAULT '💅'"]:
        try:
            c.execute(f"ALTER TABLE masters ADD COLUMN {col}")
        except:
            pass

    for col in ["work_start TEXT DEFAULT '09:00'", "work_end TEXT DEFAULT '20:00'"]:
        try:
            c.execute(f"ALTER TABLE masters ADD COLUMN {col}")
        except:
            pass

    # НЕ ДОБАВЛЯЕМ ТЕСТОВЫХ МАСТЕРОВ, ЧТОБЫ НЕ ЗАТИРАТЬ СУЩЕСТВУЮЩИХ
    conn.commit()
    conn.close()
    print("✅ База данных инициализирована (существующие мастера сохранены)")

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

# ========== ФУНКЦИИ ДЛЯ ЮKASSA ==========

def get_ykassa_auth():
    auth_string = f"{YKASSA_SHOP_ID}:{YKASSA_SECRET_KEY}"
    return base64.b64encode(auth_string.encode()).decode()

def get_ykassa_headers():
    return {
        "Authorization": f"Basic {get_ykassa_auth()}",
        "Content-Type": "application/json",
        "Idempotence-Key": str(uuid.uuid4())
    }

async def create_ykassa_payment(amount: float, description: str, return_url: str = None) -> dict:
    if not return_url:
        return_url = "https://t.me/pinkspotvelur_bot"
    
    payment_data = {
        "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
        "payment_method_data": {"type": "bank_card"},
        "confirmation": {"type": "redirect", "return_url": return_url},
        "description": description,
        "capture": True
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            YKASSA_API_URL,
            headers=get_ykassa_headers(),
            json=payment_data,
            timeout=30.0
        )
        
        if response.status_code != 200:
            raise HTTPException(500, f"ЮKassa error: {response.text}")
        
        return response.json()

async def send_telegram_message(chat_id: str, text: str):
    if not chat_id:
        return
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{MASTER_BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
            )
    except Exception as e:
        print(f"Send message error: {e}")

async def notify_master(master_bot_token: str, master_telegram_id: str, message: str, booking_id: int):
    if not master_bot_token or not master_telegram_id:
        return
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{master_bot_token}/sendMessage",
                json={
                    "chat_id": master_telegram_id,
                    "text": message,
                    "parse_mode": "Markdown",
                    "reply_markup": {
                        "inline_keyboard": [[
                            {"text": "✅ Подтвердить", "callback_data": f"confirm_{booking_id}"},
                            {"text": "❌ Отменить", "callback_data": f"cancel_{booking_id}"}
                        ]]
                    }
                }
            )
    except Exception as e:
        print(f"Notify error: {e}")

# ========== ЭНДПОИНТЫ ДЛЯ МАСТЕРОВ ==========

@app.get("/masters", response_model=List[MasterOut])
def get_masters(conn: sqlite3.Connection = Depends(get_db)):
    masters = conn.execute("SELECT * FROM masters").fetchall()
    result = []
    for m in masters:
        completed = conn.execute(
            "SELECT COUNT(*) FROM bookings WHERE master_id = ? AND status = 'confirmed'",
            (m["id"],)
        ).fetchone()[0]
        
        services = conn.execute("SELECT * FROM services WHERE master_id = ?", (m["id"],)).fetchall()
        master_dict = dict(m)
        if master_dict.get("photos"):
            try:
                master_dict["photos"] = json.loads(master_dict["photos"])
            except:
                master_dict["photos"] = []
        else:
            master_dict["photos"] = []
        master_dict["services"] = [dict(s) for s in services]
        master_dict["completed_bookings"] = completed
        result.append(master_dict)
    return result

@app.get("/masters/by_telegram/{telegram_id}")
def get_master_by_telegram(telegram_id: str, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT * FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(status_code=404, detail="Master not found")
    return dict(master)

@app.get("/masters/{master_id}")
def get_master(master_id: int, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT * FROM masters WHERE id = ?", (master_id,)).fetchone()
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

    free_slots = [s for s in all_slots if s not in booked_times and not (date == today and s <= now_time)]
    return {"slots": free_slots}

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

# ========== ЭНДПОИНТЫ ДЛЯ ЛОКАЦИИ ==========

@app.patch("/master/{telegram_id}/location")
def update_master_location(telegram_id: str, data: dict, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id = ?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    
    conn.execute("UPDATE masters SET lat = ?, lon = ? WHERE id = ?", (data["lat"], data["lon"], master["id"]))
    conn.commit()
    return {"status": "ok"}

@app.patch("/masters/{master_id}/telegram")
def set_master_telegram(master_id: int, data: dict, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("UPDATE masters SET telegram_id = ? WHERE id = ?", (data["telegram_id"], master_id))
    conn.commit()
    return {"status": "ok"}

@app.delete("/masters/{master_id}")
def delete_master(master_id: int, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("DELETE FROM masters WHERE id = ?", (master_id,))
    conn.commit()
    return {"status": "ok"}

@app.post("/masters")
def add_master(master: dict, conn: sqlite3.Connection = Depends(get_db)):
    if not master.get("name") or not master.get("address"):
        raise HTTPException(status_code=400, detail="Missing name or address")
    
    conn.execute(
        """INSERT INTO masters (name, address, lat, lon, phone, instagram, description, icon, registered_at) 
           VALUES (?,?,?,?,?,?,?,?, CURRENT_TIMESTAMP)""",
        (master["name"], master["address"], master.get("lat", 47.222078), master.get("lon", 39.720358),
         master.get("phone"), master.get("instagram"), master.get("description"), master.get("icon", "💅"))
    )
    conn.commit()
    return {"status": "ok"}

@app.patch("/masters/{master_id}/icon")
def set_master_icon(master_id: int, data: dict, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("UPDATE masters SET icon = ? WHERE id = ?", (data.get("icon", "💅"), master_id))
    conn.commit()
    return {"status": "ok"}

# ========== ЭНДПОИНТЫ ДЛЯ УСЛУГ ==========

@app.get("/master/{telegram_id}/services")
def get_master_services(telegram_id: str, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id = ?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    
    services = conn.execute("SELECT * FROM services WHERE master_id = ?", (master["id"],)).fetchall()
    return [dict(s) for s in services]

@app.post("/master/{telegram_id}/services")
def add_master_service(telegram_id: str, data: dict, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id = ?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    
    conn.execute(
        "INSERT INTO services (master_id, name, price, duration_min) VALUES (?, ?, ?, ?)",
        (master["id"], data["name"], data["price"], data["duration_min"])
    )
    conn.commit()
    return {"status": "ok"}

@app.delete("/master/{telegram_id}/services/{service_id}")
def delete_master_service(telegram_id: str, service_id: int, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id = ?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    
    conn.execute("DELETE FROM services WHERE id = ? AND master_id = ?", (service_id, master["id"]))
    conn.commit()
    return {"status": "ok"}

@app.patch("/master/{telegram_id}/work-hours")
def update_work_hours(telegram_id: str, data: dict, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id = ?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    
    conn.execute("UPDATE masters SET work_start = ?, work_end = ? WHERE id = ?", 
                (data["work_start"], data["work_end"], master["id"]))
    conn.commit()
    return {"status": "ok"}

# ========== ОСНОВНОЙ ЭНДПОИНТ ДЛЯ ЗАПИСИ ==========

@app.post("/bookings")
async def create_booking(data: BookingIn, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT * FROM masters WHERE id = ?", (data.master_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")

    service = conn.execute("SELECT * FROM services WHERE id=? AND master_id=?", (data.service_id, data.master_id)).fetchone()
    if not service:
        raise HTTPException(404, "Service not found")

    existing = conn.execute(
        "SELECT id FROM bookings WHERE master_id=? AND date=? AND time=? AND status!='cancelled'",
        (data.master_id, data.date, data.time)
    ).fetchone()
    if existing:
        raise HTTPException(409, "This time slot is already booked")

    commission_amount = round(service["price"] * COMMISSION_PERCENT / 100, 2)

    cursor = conn.execute(
        """INSERT INTO bookings (master_id, service_id, client_name, client_telegram_id, client_phone, date, time, commission_amount) 
           VALUES (?,?,?,?,?,?,?,?)""",
        (data.master_id, data.service_id, data.client_name, data.client_telegram_id, 
         data.client_phone, data.date, data.time, commission_amount)
    )
    conn.commit()
    booking_id = cursor.lastrowid

    # Уведомление мастеру
    message = (
        f"🌸 *Новая запись!*\n\n"
        f"👩 Клиент: {data.client_name}\n"
        f"💅 Услуга: {service['name']}\n"
        f"💰 Цена: {service['price']} ₽\n"
        f"💸 Комиссия: {commission_amount} ₽ ({COMMISSION_PERCENT}%)\n"
        f"📅 Дата: {data.date}\n"
        f"🕐 Время: {data.time}"
    )
    await notify_master(master["bot_token"], master["telegram_id"], message, booking_id)

    booking = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    return dict(booking)

# ========== ПЛАТЕЖИ ==========

@app.post("/create-payment")
async def create_payment(data: PaymentRequest, conn: sqlite3.Connection = Depends(get_db)):
    """Создание платежа в ЮKassa на сумму комиссии"""
    booking = conn.execute("SELECT * FROM bookings WHERE id = ?", (data.booking_id,)).fetchone()
    if not booking:
        raise HTTPException(404, "Booking not found")
    
    existing_payment = conn.execute("SELECT * FROM payments WHERE booking_id = ? AND status = 'pending'", (data.booking_id,)).fetchone()
    if existing_payment and existing_payment["payment_url"]:
        return {
            "payment_url": existing_payment["payment_url"],
            "amount": existing_payment["amount"],
            "payment_id": existing_payment["payment_id"],
            "booking_id": booking["id"]
        }
    
    service = conn.execute("SELECT name FROM services WHERE id = ?", (booking["service_id"],)).fetchone()
    amount = booking["commission_amount"]
    description = f"Комиссия Beauty Map ({COMMISSION_PERCENT}%) за запись: {service['name']}"
    
    try:
        ykassa_payment = await create_ykassa_payment(amount, description, data.return_url)
        payment_id = ykassa_payment["id"]
        payment_url = ykassa_payment["confirmation"]["confirmation_url"]
        
        conn.execute(
            """INSERT INTO payments (booking_id, amount, status, payment_id, payment_url) VALUES (?, ?, 'pending', ?, ?)""",
            (booking["id"], amount, payment_id, payment_url)
        )
        conn.execute("UPDATE bookings SET payment_status = 'pending', commission_payment_id = ? WHERE id = ?", (payment_id, booking["id"]))
        conn.commit()
        
        return {
            "payment_url": payment_url,
            "amount": amount,
            "payment_id": payment_id,
            "booking_id": booking["id"]
        }
    except Exception as e:
        raise HTTPException(500, f"Payment creation failed: {str(e)}")

@app.post("/payment-callback")
async def payment_callback(data: dict, conn: sqlite3.Connection = Depends(get_db)):
    """Callback для подтверждения оплаты (вызывается из бота после успешного платежа)"""
    booking_id = data.get("booking_id")
    payment_id = data.get("payment_id")
    
    if booking_id:
        conn.execute("UPDATE payments SET status = 'paid' WHERE payment_id = ?", (payment_id,))
        conn.execute("UPDATE bookings SET payment_status = 'paid', status = 'confirmed' WHERE id = ?", (booking_id,))
        
        # Создаём чат
        booking = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        token = secrets.token_urlsafe(16)
        conn.execute(
            """INSERT OR IGNORE INTO chats (booking_id, master_id, client_telegram_id, master_telegram_id, token)
               VALUES (?, ?, ?, ?, ?)""",
            (booking_id, booking["master_id"], booking["client_telegram_id"], None, token)
        )
        conn.commit()
        
        await send_telegram_message(
            booking["client_telegram_id"],
            f"✅ *Оплата прошла успешно!*\n\n"
            f"Ваша запись подтверждена. Чат с мастером открыт."
        )
    
    return {"status": "ok"}

@app.get("/payment-status/{booking_id}")
def get_payment_status(booking_id: int, conn: sqlite3.Connection = Depends(get_db)):
    payment = conn.execute("SELECT * FROM payments WHERE booking_id = ? ORDER BY id DESC LIMIT 1", (booking_id,)).fetchone()
    booking = conn.execute("SELECT payment_status, status FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    
    return {
        "booking_id": booking_id,
        "payment_status": booking["payment_status"] if booking else "unknown",
        "booking_status": booking["status"] if booking else "unknown",
        "commission_amount": payment["amount"] if payment else None
    }

# ========== ЗАПИСИ КЛИЕНТОВ И МАСТЕРОВ ==========

@app.get("/bookings/client/{telegram_id}")
def get_client_bookings(telegram_id: str, conn: sqlite3.Connection = Depends(get_db)):
    bookings = conn.execute(
        """SELECT b.*, m.name as master_name, m.telegram_id as master_telegram_id, s.name as service_name, s.price
           FROM bookings b 
           JOIN masters m ON b.master_id = m.id 
           JOIN services s ON b.service_id = s.id
           WHERE b.client_telegram_id = ? 
           ORDER BY b.date DESC, b.time DESC""",
        (telegram_id,)
    ).fetchall()
    return [dict(b) for b in bookings]

@app.get("/bookings/master/{master_id}")
def get_master_bookings(master_id: int, conn: sqlite3.Connection = Depends(get_db)):
    bookings = conn.execute(
        """SELECT b.*, s.name as service_name, s.price 
           FROM bookings b 
           JOIN services s ON b.service_id = s.id
           WHERE b.master_id = ? 
           ORDER BY b.date DESC, b.time DESC""",
        (master_id,)
    ).fetchall()
    return [dict(b) for b in bookings]

@app.patch("/bookings/{booking_id}/status")
def update_booking_status(booking_id: int, status: str, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("UPDATE bookings SET status = ? WHERE id = ?", (status, booking_id))
    conn.commit()
    return {"status": "ok"}

# ========== СТАТИСТИКА ==========

@app.get("/master/{telegram_id}/stats")
def get_master_stats(telegram_id: str, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id = ?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    
    confirmed = conn.execute("SELECT COUNT(*) FROM bookings WHERE master_id = ? AND status = 'confirmed'", (master["id"],)).fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM bookings WHERE master_id = ? AND status = 'pending'", (master["id"],)).fetchone()[0]
    revenue = conn.execute("SELECT SUM(s.price) FROM bookings b JOIN services s ON b.service_id = s.id WHERE b.master_id = ? AND b.status = 'confirmed'", (master["id"],)).fetchone()[0] or 0
    
    return {
        "completed_bookings": confirmed,
        "pending_bookings": pending,
        "revenue": revenue,
        "commission_percent": COMMISSION_PERCENT
    }

# ========== ПОЛЬЗОВАТЕЛИ ==========

@app.post("/user/register")
def register_user(data: dict, conn: sqlite3.Connection = Depends(get_db)):
    try:
        conn.execute("INSERT OR IGNORE INTO users (telegram_id) VALUES (?)", (data["telegram_id"],))
        conn.commit()
    except:
        pass
    return {"status": "ok"}

@app.get("/user/trial/{telegram_id}")
def check_trial(telegram_id: str):
    return {"has_trial": False, "days_left": 0, "message": "Платная услуга. Комиссия 7% оплачивается отдельно."}

# ========== ЧАТ ==========

@app.post("/chat/send")
def send_message(data: dict, conn: sqlite3.Connection = Depends(get_db)):
    booking = conn.execute("SELECT id, status FROM bookings WHERE id = ?", (data["booking_id"],)).fetchone()
    if not booking:
        raise HTTPException(404, "Booking not found")
    if booking["status"] != "confirmed":
        raise HTTPException(403, "Chat available only after payment confirmation")
    
    conn.execute(
        "INSERT INTO chat_messages (booking_id, from_id, to_id, message) VALUES (?, ?, ?, ?)",
        (data["booking_id"], data["from_id"], data["to_id"], data.get("message"))
    )
    conn.commit()
    return {"status": "ok"}

@app.get("/chat/messages/{booking_id}")
def get_messages(booking_id: int, user_id: str, conn: sqlite3.Connection = Depends(get_db)):
    booking = conn.execute("SELECT client_telegram_id, master_id FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    if not booking:
        return []
    
    master = conn.execute("SELECT telegram_id FROM masters WHERE id = ?", (booking["master_id"],)).fetchone()
    master_telegram_id = master["telegram_id"] if master else None
    
    if user_id != booking["client_telegram_id"] and user_id != master_telegram_id:
        return []
    
    messages = conn.execute("SELECT * FROM chat_messages WHERE booking_id = ? ORDER BY created_at ASC", (booking_id,)).fetchall()
    return [dict(m) for m in messages]

@app.get("/chat/booking/{booking_id}/access")
def check_chat_access(booking_id: int, user_id: str, conn: sqlite3.Connection = Depends(get_db)):
    booking = conn.execute("SELECT status FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    if not booking:
        return {"access": False}
    return {"access": booking["status"] == "confirmed", "status": booking["status"]}

@app.get("/chat/{token}")
def get_chat_by_token(token: str, conn: sqlite3.Connection = Depends(get_db)):
    chat = conn.execute("SELECT * FROM chats WHERE token = ?", (token,)).fetchone()
    if not chat:
        raise HTTPException(404, "Chat not found")
    return dict(chat)

# ========== АДМИН-ПАНЕЛЬ ==========

@app.post("/admin/add-master")
def admin_add_master(data: dict, conn: sqlite3.Connection = Depends(get_db)):
    cursor = conn.execute(
        """INSERT INTO masters (name, address, lat, lon, phone, instagram, description, icon) 
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (data["name"], data["address"], data.get("lat", 47.222078), data.get("lon", 39.720358),
         data.get("phone", ""), data.get("instagram", ""), data.get("description", ""), data.get("icon", "💅"))
    )
    conn.commit()
    return {"id": cursor.lastrowid, "status": "ok"}

@app.get("/admin/masters")
def admin_get_masters(conn: sqlite3.Connection = Depends(get_db)):
    masters = conn.execute("SELECT id, name, telegram_id, phone, instagram, icon FROM masters").fetchall()
    return [dict(m) for m in masters]

@app.delete("/admin/delete-master/{master_id}")
def admin_delete_master(master_id: int, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("DELETE FROM masters WHERE id = ?", (master_id,))
    conn.commit()
    return {"status": "ok"}

@app.patch("/admin/set-telegram/{master_id}")
def admin_set_telegram(master_id: int, data: dict, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("UPDATE masters SET telegram_id = ? WHERE id = ?", (data["telegram_id"], master_id))
    conn.commit()
    return {"status": "ok"}

@app.post("/admin/add-promo")
def admin_add_promo(data: dict, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute(
        "INSERT INTO promo_codes (code, discount_percent, valid_until, max_uses) VALUES (?, ?, ?, ?)",
        (data["code"], data["discount_percent"], data["valid_until"], data.get("max_uses", 100))
    )
    conn.commit()
    return {"status": "ok"}

@app.post("/apply-promo")
def apply_promo(data: dict, conn: sqlite3.Connection = Depends(get_db)):
    promo = conn.execute(
        "SELECT * FROM promo_codes WHERE code = ? AND valid_until >= date('now') AND used_count < max_uses",
        (data["promo_code"],)
    ).fetchone()
    if not promo:
        raise HTTPException(404, "Promo not found")
    
    conn.execute("UPDATE promo_codes SET used_count = used_count + 1 WHERE id = ?", (promo["id"],))
    conn.commit()
    return {"discount_percent": promo["discount_percent"], "valid_until": promo["valid_until"]}

# ========== ОТЗЫВЫ ==========

@app.post("/reviews")
def create_review(data: dict, conn: sqlite3.Connection = Depends(get_db)):
    booking = conn.execute(
        "SELECT id FROM bookings WHERE id = ? AND master_id = ? AND client_telegram_id = ? AND status = 'confirmed'",
        (data.get("booking_id"), data.get("master_id"), data.get("client_telegram_id"))
    ).fetchone()
    if not booking:
        raise HTTPException(400, "Вы можете оставить отзыв только после подтверждённой записи")
    
    conn.execute(
        "INSERT INTO reviews (master_id, booking_id, client_name, rating, comment) VALUES (?, ?, ?, ?, ?)",
        (data.get("master_id"), data.get("booking_id"), data.get("client_name"), data.get("rating"), data.get("comment"))
    )
    conn.commit()
    
    conn.execute(
        "UPDATE masters SET rating = (SELECT AVG(rating) FROM reviews WHERE master_id = ?) WHERE id = ?",
        (data.get("master_id"), data.get("master_id"))
    )
    conn.commit()
    return {"status": "ok"}

@app.get("/reviews/master/{master_id}")
def get_master_reviews(master_id: int, conn: sqlite3.Connection = Depends(get_db)):
    reviews = conn.execute("SELECT * FROM reviews WHERE master_id = ? ORDER BY created_at DESC", (master_id,)).fetchall()
    return [dict(r) for r in reviews]

# ========== БЭКАП ==========

@app.get("/backup-db")
def backup_db():
    if os.path.exists(DB_PATH):
        return FileResponse(DB_PATH, filename="beauty.db")
    return {"error": "Database not found"}

@app.post("/restore-db")
async def restore_db(file: UploadFile = File(...)):
    contents = await file.read()
    with open(DB_PATH, "wb") as f:
        f.write(contents)
    return {"status": "ok"}

# ========== ГЛАВНАЯ ==========

@app.get("/")
def root():
    return {
        "status": "Beauty Bot API running 🌸",
        "commission_percent": COMMISSION_PERCENT,
        "version": "2.0"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
