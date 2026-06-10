from fastapi import FastAPI, HTTPException, Depends, Request
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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Beauty Bot API")

# === КОНФИГУРАЦИЯ ЮKASSA ===
YKASSA_SHOP_ID = os.getenv("YKASSA_SHOP_ID", "1368786")
YKASSA_SECRET_KEY = "live_aRHBYSr1irUAO8_dvzZCmQCih-vTF0q0NFfSvW5OOcs
"
YKASSA_RETURN_URL = os.getenv("YKASSA_RETURN_URL", "https://t.me/pinkspotvelur_bot")
PAYMENT_COMMISSION = 0.07
CLEANING_TIME = 15  # 15 минут на уборку между записями

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

# ========== БД ==========
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS masters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, address TEXT, lat REAL, lon REAL,
        phone TEXT, instagram TEXT, telegram_id TEXT,
        work_start TEXT DEFAULT '09:00', work_end TEXT DEFAULT '20:00',
        bot_token TEXT, description TEXT, icon TEXT DEFAULT '💅', rating REAL DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS services (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        master_id INTEGER, name TEXT, price INTEGER, duration_min INTEGER
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        master_id INTEGER, service_id INTEGER,
        client_name TEXT, client_telegram_id TEXT, client_phone TEXT,
        date TEXT, time TEXT,
        status TEXT DEFAULT 'pending_payment',
        deposit_amount REAL DEFAULT 0,
        payment_id TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        confirmed_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS days_off (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        master_id INTEGER, date TEXT, UNIQUE(master_id, date)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS chats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        booking_id INTEGER UNIQUE, master_id INTEGER,
        client_telegram_id TEXT, master_telegram_id TEXT, token TEXT UNIQUE
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS chat_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        booking_id INTEGER, from_id TEXT, to_id TEXT,
        message TEXT, is_read INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id TEXT UNIQUE, registered_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    
    try:
        c.execute("ALTER TABLE bookings ADD COLUMN deposit_amount REAL DEFAULT 0")
    except: pass
    try:
        c.execute("ALTER TABLE bookings ADD COLUMN payment_id TEXT")
    except: pass
    
    c.execute("SELECT COUNT(*) FROM masters")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO masters (name, address, lat, lon, phone, instagram, icon, work_start, work_end) VALUES (?,?,?,?,?,?,?,?,?)",
                  ("Алина Козлова", "ул. Ленина, 12", 47.222078, 39.720358, "+79001234567", "@alina_nails", "💅", "09:00", "20:00"))
        c.execute("SELECT id FROM masters")
        master_id = c.fetchone()[0]
        c.execute("INSERT INTO services (master_id, name, price, duration_min) VALUES (?,?,?,?)", (master_id, "Маникюр классический", 1200, 60))
        c.execute("INSERT INTO services (master_id, name, price, duration_min) VALUES (?,?,?,?)", (master_id, "Маникюр с покрытием гель-лак", 2000, 90))
        c.execute("INSERT INTO services (master_id, name, price, duration_min) VALUES (?,?,?,?)", (master_id, "Педикюр", 2500, 120))
    
    conn.commit()
    conn.close()
    logger.info("✅ БД готова")

init_db()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def time_to_minutes(time_str: str) -> int:
    """Преобразует время в минуты с начала дня"""
    h, m = map(int, time_str.split(':'))
    return h * 60 + m

def minutes_to_time(minutes: int) -> str:
    """Преобразует минуты в строку времени HH:MM"""
    h = minutes // 60
    m = minutes % 60
    return f"{h:02d}:{m:02d}"

def generate_slots_with_duration(work_start: str, work_end: str, booked_slots: List[dict], service_duration: int, cleaning_time: int = 15) -> List[str]:
    """
    Генерирует свободные слоты с учётом длительности услуги и времени на уборку.
    booked_slots: список словарей с временем начала и длительностью услуги
    """
    start_min = time_to_minutes(work_start)
    end_min = time_to_minutes(work_end)
    interval = 30  # шаг 30 минут
    
    # Преобразуем занятые слоты в занятые интервалы
    occupied_intervals = []
    for slot in booked_slots:
        slot_start = time_to_minutes(slot['time'])
        slot_duration = slot.get('duration_min', 60)
        slot_end = slot_start + slot_duration + cleaning_time  # добавляем время на уборку
        occupied_intervals.append((slot_start, slot_end))
    
    # Сортируем по времени начала
    occupied_intervals.sort()
    
    # Объединяем пересекающиеся интервалы
    merged = []
    for interval in occupied_intervals:
        if not merged or merged[-1][1] < interval[0]:
            merged.append(list(interval))
        else:
            merged[-1][1] = max(merged[-1][1], interval[1])
    
    # Генерируем свободные слоты
    free_slots = []
    current_time = start_min
    
    for occ_start, occ_end in merged:
        # Добавляем слоты от текущего времени до начала занятого интервала
        while current_time + service_duration <= occ_start:
            free_slots.append(minutes_to_time(current_time))
            current_time += interval
        
        # Перемещаем текущее время на конец занятого интервала
        current_time = max(current_time, occ_end)
    
    # Добавляем слоты после последнего занятого интервала до конца рабочего дня
    while current_time + service_duration <= end_min:
        free_slots.append(minutes_to_time(current_time))
        current_time += interval
    
    return free_slots

def generate_slots_simple(work_start: str, work_end: str) -> List[str]:
    """Простая генерация слотов без учёта длительности (для совместимости)"""
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
        async with httpx.AsyncClient() as client:
            await client.post(f"https://api.telegram.org/bot{token}/sendMessage",
                            json={"chat_id": tg_id, "text": msg, "parse_mode": "Markdown"})
    except: pass

def confirm_booking(booking_id, conn):
    conn.execute("UPDATE bookings SET status='confirmed', confirmed_at=CURRENT_TIMESTAMP WHERE id=?", (booking_id,))
    conn.commit()
    logger.info(f"✅ Бронирование {booking_id} подтверждено")

# ========== ГЛАВНАЯ ФУНКЦИЯ ПЛАТЕЖА ==========
async def create_ykassa_payment(amount: float, description: str, return_url: str, booking_id: int) -> dict:
    """Создание реального платежа в ЮKassa"""
    
    if not YKASSA_SHOP_ID or not YKASSA_SECRET_KEY:
        logger.error("ЮKassa не настроена!")
        raise HTTPException(500, "ЮKassa не настроена")
    
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
                raise HTTPException(500, f"Ошибка платежа: {response.text}")
    except Exception as e:
        logger.error(f"Payment error: {e}")
        raise HTTPException(500, str(e))

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

@app.get("/masters/{master_id}/slots")
def get_slots(master_id: int, date: str, service_id: int, conn=Depends(get_db)):
    """Возвращает свободные слоты с учётом длительности выбранной услуги"""
    master = conn.execute("SELECT * FROM masters WHERE id=?", (master_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    
    # Получаем длительность услуги
    service = conn.execute("SELECT duration_min FROM services WHERE id=? AND master_id=?", (service_id, master_id)).fetchone()
    if not service:
        raise HTTPException(404, "Service not found")
    
    service_duration = service["duration_min"]
    
    # Проверка на выходной
    day_off = conn.execute("SELECT id FROM days_off WHERE master_id=? AND date=?", (master_id, date)).fetchone()
    if day_off:
        return {"date": date, "slots": [], "day_off": True}
    
    work_start = master["work_start"] or DEFAULT_WORK_START
    work_end = master["work_end"] or DEFAULT_WORK_END
    
    # Получаем все подтверждённые записи на эту дату с их длительностью
    booked = conn.execute("""
        SELECT b.time, s.duration_min 
        FROM bookings b 
        JOIN services s ON b.service_id = s.id 
        WHERE b.master_id=? AND b.date=? AND b.status IN ('pending_payment', 'confirmed')
    """, (master_id, date)).fetchall()
    
    booked_slots = [{"time": b["time"], "duration_min": b["duration_min"]} for b in booked]
    
    # Генерируем свободные слоты с учётом длительности услуги
    free_slots = generate_slots_with_duration(work_start, work_end, booked_slots, service_duration, CLEANING_TIME)
    
    today = datetime.now().strftime("%Y-%m-%d")
    now_time = datetime.now().strftime("%H:%M")
    now_minutes = time_to_minutes(now_time)
    
    # Фильтруем прошедшие слоты для сегодняшнего дня
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
        
        deposit_amount = round(service["price"] * PAYMENT_COMMISSION, 2)
        
        cur = conn.execute("""
            INSERT INTO bookings (master_id, service_id, client_name, client_telegram_id, client_phone, date, time, deposit_amount)
            VALUES (?,?,?,?,?,?,?,?)
        """, (data.master_id, data.service_id, data.client_name, data.client_telegram_id, data.client_phone, data.date, data.time, deposit_amount))
        conn.commit()
        booking_id = cur.lastrowid
        
        logger.info(f"📝 Бронь {booking_id}: {data.client_name} -> {service['name']} на {data.date} {data.time}")
        
        # СОЗДАЁМ РЕАЛЬНЫЙ ПЛАТЁЖ В ЮKASSA
        payment = await create_ykassa_payment(
            amount=deposit_amount,
            description=f"Бронь услуги {service['name']} ({deposit_amount}₽ из {service['price']}₽)",
            return_url=f"{YKASSA_RETURN_URL}?booking_id={booking_id}",
            booking_id=booking_id
        )
        
        conn.execute("UPDATE bookings SET payment_id=? WHERE id=?", (payment["payment_id"], booking_id))
        conn.commit()
        
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
                    logger.info(f"✅ Booking {booking['id']} confirmed")
            finally:
                conn.close()
    return {"status": "ok"}

@app.get("/bookings/client/{telegram_id}")
def get_client_bookings(telegram_id: str, conn=Depends(get_db)):
    bookings = conn.execute("""
        SELECT b.*, m.name as master_name, s.name as service_name, s.price
        FROM bookings b JOIN masters m ON b.master_id=m.id JOIN services s ON b.service_id=s.id
        WHERE b.client_telegram_id=? ORDER BY b.date DESC, b.time DESC
    """, (telegram_id,)).fetchall()
    return [dict(b) for b in bookings]

@app.get("/master/{telegram_id}/stats")
def get_stats(telegram_id: str, conn=Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    confirmed = conn.execute("SELECT COUNT(*) FROM bookings WHERE master_id=? AND status='confirmed'", (master["id"],)).fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM bookings WHERE master_id=? AND status='pending_payment'", (master["id"],)).fetchone()[0]
    revenue = conn.execute("SELECT SUM(s.price) FROM bookings b JOIN services s ON b.service_id=s.id WHERE b.master_id=? AND b.status='confirmed'", (master["id"],)).fetchone()[0] or 0
    return {"completed_bookings": confirmed, "pending_payment": pending, "revenue": revenue}

@app.post("/chat/send")
def send_message(data: MessageIn, conn=Depends(get_db)):
    conn.execute("INSERT INTO chat_messages (booking_id, from_id, to_id, message) VALUES (?,?,?,?)",
                (data.booking_id, data.from_id, data.to_id, data.message))
    conn.commit()
    return {"status": "ok"}

@app.get("/chat/messages/{booking_id}")
def get_messages(booking_id: int, user_id: str, conn=Depends(get_db)):
    messages = conn.execute("SELECT * FROM chat_messages WHERE booking_id=? ORDER BY created_at ASC", (booking_id,)).fetchall()
    return [dict(m) for m in messages]

@app.patch("/master/{telegram_id}/work-hours")
def update_work_hours(telegram_id: str, data: WorkHoursUpdate, conn=Depends(get_db)):
    conn.execute("UPDATE masters SET work_start=?, work_end=? WHERE telegram_id=?", (data.work_start, data.work_end, telegram_id))
    conn.commit()
    return {"status": "ok"}

@app.patch("/master/{telegram_id}/location")
def update_location(telegram_id: str, data: LocationUpdate, conn=Depends(get_db)):
    conn.execute("UPDATE masters SET lat=?, lon=? WHERE telegram_id=?", (data.lat, data.lon, telegram_id))
    conn.commit()
    return {"status": "ok"}

@app.post("/user/register")
def register_user(data: UserRegister, conn=Depends(get_db)):
    conn.execute("INSERT OR IGNORE INTO users (telegram_id) VALUES (?)", (data.telegram_id,))
    conn.commit()
    return {"status": "ok"}

@app.post("/master/{telegram_id}/services")
def add_service(telegram_id: str, data: ServiceIn, conn=Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    conn.execute("INSERT INTO services (master_id, name, price, duration_min) VALUES (?,?,?,?)",
                (master["id"], data.name, data.price, data.duration_min))
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
def get_master_services(telegram_id: str, conn=Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(404, "Master not found")
    services = conn.execute("SELECT * FROM services WHERE master_id=?", (master["id"],)).fetchall()
    return [dict(s) for s in services]

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

@app.get("/")
def root():
    return {"status": "Beauty Bot API running 🌸", "version": "3.0.0"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
