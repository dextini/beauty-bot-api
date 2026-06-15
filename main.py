from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import asyncpg
import os
import json
import hashlib
import hmac
from datetime import datetime, timedelta
from decimal import Decimal
import random
import string

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost/beauty")
db = None

# ========== МОДЕЛИ ==========
class MasterCreate(BaseModel):
    telegram_id: int
    name: str
    lat: float
    lon: float
    description: Optional[str] = None
    work_start: Optional[str] = "09:00"
    work_end: Optional[str] = "21:00"

class MasterUpdate(BaseModel):
    name: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    description: Optional[str] = None
    work_start: Optional[str] = None
    work_end: Optional[str] = None

class ServiceCreate(BaseModel):
    name: str
    price: int
    duration_min: int

class ServiceUpdate(BaseModel):
    name: Optional[str] = None
    price: Optional[int] = None
    duration_min: Optional[int] = None

class BookingCreate(BaseModel):
    master_id: int
    service_id: int
    client_name: str
    client_telegram_id: str
    client_phone: Optional[str] = None
    date: str
    time: str

class BookingUpdate(BaseModel):
    status: Optional[str] = None
    date: Optional[str] = None
    time: Optional[str] = None

class ReviewCreate(BaseModel):
    booking_id: int
    rating: int
    comment: Optional[str] = None

class ReviewDirectCreate(BaseModel):
    user_id: int
    master_id: int
    rating: int
    comment: Optional[str] = None

class ReminderRequest(BaseModel):
    user_id: int
    hours_before: int
    message: str

class WaitlistRequest(BaseModel):
    user_id: int
    service: str
    master_id: Optional[int] = None

class BeforeAfterCreate(BaseModel):
    before_photo: str
    after_photo: str
    description: Optional[str] = None

class PortfolioCreate(BaseModel):
    photo_url: str
    description: Optional[str] = None

class QuickReplyCreate(BaseModel):
    title: str
    message: str

class ChatMessageSend(BaseModel):
    booking_id: int
    from_id: str
    to_id: str
    message: str

class PromoCodeCreate(BaseModel):
    code: str
    discount_percent: int
    expires_at: str
    max_uses: Optional[int] = None

class PromoCodeApply(BaseModel):
    user_id: int
    promo_code: str
    booking_id: Optional[int] = None

class ClientSettingsUpdate(BaseModel):
    push_enabled: Optional[bool] = None
    tg_notify_enabled: Optional[bool] = None
    quiet_hour_start: Optional[str] = None
    quiet_hour_end: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None

class SupportRequest(BaseModel):
    user_id: int
    message: str
    subject: Optional[str] = None

class PaymentCreate(BaseModel):
    booking_id: int
    amount: int
    payment_method: str = "card"

# ========== ЗАПУСК ==========
@app.on_event("startup")
async def startup():
    global db
    try:
        db = await asyncpg.connect(DATABASE_URL)
        await init_db()
    except Exception as e:
        print(f"Database connection error: {e}")

async def init_db():
    await db.execute("""
        CREATE TABLE IF NOT EXISTS masters (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT UNIQUE,
            name VARCHAR(100) NOT NULL,
            lat FLOAT NOT NULL,
            lon FLOAT NOT NULL,
            rating FLOAT DEFAULT 0,
            reviews_count INTEGER DEFAULT 0,
            description TEXT,
            work_start TIME DEFAULT '09:00',
            work_end TIME DEFAULT '21:00',
            icon VARCHAR(10) DEFAULT '💅',
            completed_bookings INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS services (
            id SERIAL PRIMARY KEY,
            master_id INTEGER REFERENCES masters(id) ON DELETE CASCADE,
            name VARCHAR(100) NOT NULL,
            price INTEGER NOT NULL,
            duration_min INTEGER DEFAULT 60,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id SERIAL PRIMARY KEY,
            master_id INTEGER REFERENCES masters(id),
            service_id INTEGER REFERENCES services(id),
            client_name VARCHAR(100) NOT NULL,
            client_telegram_id VARCHAR(50) NOT NULL,
            client_phone VARCHAR(20),
            date DATE NOT NULL,
            time TIME NOT NULL,
            price INTEGER NOT NULL,
            status VARCHAR(20) DEFAULT 'pending',
            review_given BOOLEAN DEFAULT FALSE,
            payment_id VARCHAR(100),
            deposit_paid BOOLEAN DEFAULT FALSE,
            deposit_amount INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id SERIAL PRIMARY KEY,
            booking_id INTEGER REFERENCES bookings(id) ON DELETE CASCADE,
            user_id BIGINT NOT NULL,
            master_id INTEGER REFERENCES masters(id),
            rating INTEGER CHECK (rating >= 1 AND rating <= 5),
            comment TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS waitlist (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            service VARCHAR(100),
            master_id INTEGER REFERENCES masters(id),
            created_at TIMESTAMP DEFAULT NOW(),
            notified BOOLEAN DEFAULT FALSE,
            UNIQUE(user_id, service, master_id)
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS master_before_after (
            id SERIAL PRIMARY KEY,
            master_id INTEGER REFERENCES masters(id) ON DELETE CASCADE,
            before_photo TEXT NOT NULL,
            after_photo TEXT NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS master_portfolio (
            id SERIAL PRIMARY KEY,
            master_id INTEGER REFERENCES masters(id) ON DELETE CASCADE,
            photo_url TEXT NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            id SERIAL PRIMARY KEY,
            client_telegram_id VARCHAR(50) NOT NULL,
            master_id INTEGER REFERENCES masters(id),
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(client_telegram_id, master_id)
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS quick_replies (
            id SERIAL PRIMARY KEY,
            master_id INTEGER REFERENCES masters(id) ON DELETE CASCADE,
            title VARCHAR(100) NOT NULL,
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS master_days_off (
            id SERIAL PRIMARY KEY,
            master_id INTEGER REFERENCES masters(id) ON DELETE CASCADE,
            date DATE NOT NULL,
            UNIQUE(master_id, date)
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id SERIAL PRIMARY KEY,
            booking_id INTEGER REFERENCES bookings(id) ON DELETE CASCADE,
            from_id VARCHAR(50) NOT NULL,
            to_id VARCHAR(50) NOT NULL,
            message TEXT NOT NULL,
            is_read BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS client_settings (
            telegram_id VARCHAR(50) PRIMARY KEY,
            push_enabled BOOLEAN DEFAULT TRUE,
            tg_notify_enabled BOOLEAN DEFAULT TRUE,
            quiet_hour_start TIME DEFAULT '22:00',
            quiet_hour_end TIME DEFAULT '09:00',
            email VARCHAR(100),
            phone VARCHAR(20)
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS promocodes (
            id SERIAL PRIMARY KEY,
            code VARCHAR(50) UNIQUE NOT NULL,
            discount_percent INTEGER NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            max_uses INTEGER,
            used_count INTEGER DEFAULT 0,
            active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS user_promocodes (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            promo_code_id INTEGER REFERENCES promocodes(id),
            used_at TIMESTAMP DEFAULT NOW(),
            booking_id INTEGER REFERENCES bookings(id),
            UNIQUE(user_id, promo_code_id)
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS support_requests (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            subject VARCHAR(200),
            message TEXT NOT NULL,
            status VARCHAR(20) DEFAULT 'open',
            admin_response TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            resolved_at TIMESTAMP
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id SERIAL PRIMARY KEY,
            booking_id INTEGER REFERENCES bookings(id),
            user_id BIGINT NOT NULL,
            amount INTEGER NOT NULL,
            payment_method VARCHAR(50),
            payment_status VARCHAR(20) DEFAULT 'pending',
            transaction_id VARCHAR(100),
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            type VARCHAR(50),
            title VARCHAR(200),
            message TEXT,
            is_read BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

# ========== МАСТЕРА ==========
@app.get("/masters")
async def get_masters(
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    radius: Optional[float] = None,
    service: Optional[str] = None,
    min_rating: Optional[float] = None
):
    query = """
        SELECT m.id, m.name, m.lat, m.lon, m.rating, m.reviews_count, 
               m.description, m.work_start, m.work_end, m.icon, m.completed_bookings
        FROM masters m
        WHERE 1=1
    """
    params = []
    if min_rating:
        query += " AND m.rating >= $" + str(len(params) + 1)
        params.append(min_rating)
    
    rows = await db.fetch(query, *params)
    result = []
    for r in rows:
        services = await db.fetch("SELECT id, name, price, duration_min FROM services WHERE master_id = $1", r["id"])
        result.append(dict(r, services=[dict(s) for s in services]))
    
    if service:
        result = [m for m in result if any(s["name"] == service for s in m["services"])]
    
    if lat and lon and radius:
        result = [m for m in result if ((m["lat"] - lat) ** 2 + (m["lon"] - lon) ** 2) ** 0.5 * 111 <= radius]
    
    return result

@app.get("/masters/{master_id}")
async def get_master(master_id: int):
    row = await db.fetchrow("""
        SELECT id, name, lat, lon, rating, reviews_count, description, work_start, work_end, icon, completed_bookings
        FROM masters WHERE id = $1
    """, master_id)
    if not row:
        raise HTTPException(404, "Master not found")
    services = await db.fetch("SELECT id, name, price, duration_min FROM services WHERE master_id = $1", master_id)
    reviews = await db.fetch("SELECT rating, comment, created_at FROM reviews WHERE master_id = $1 ORDER BY created_at DESC LIMIT 10", master_id)
    return dict(row, services=[dict(s) for s in services], reviews=[dict(r) for r in reviews])

@app.get("/masters/by_telegram/{telegram_id}")
async def get_master_by_telegram(telegram_id: int):
    row = await db.fetchrow("SELECT id FROM masters WHERE telegram_id = $1", telegram_id)
    if not row:
        raise HTTPException(404, "Master not found")
    return {"id": row["id"]}

@app.post("/masters")
async def create_master(master: MasterCreate):
    existing = await db.fetchrow("SELECT id FROM masters WHERE telegram_id = $1", master.telegram_id)
    if existing:
        raise HTTPException(400, "Master already exists")
    master_id = await db.execute("""
        INSERT INTO masters (telegram_id, name, lat, lon, description, work_start, work_end)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING id
    """, master.telegram_id, master.name, master.lat, master.lon, 
        master.description, master.work_start, master.work_end)
    return {"id": master_id, "status": "created"}

@app.patch("/masters/{master_id}")
async def update_master(master_id: int, update: MasterUpdate):
    updates = []
    params = []
    if update.name is not None:
        updates.append(f"name = ${len(params) + 1}")
        params.append(update.name)
    if update.lat is not None:
        updates.append(f"lat = ${len(params) + 1}")
        params.append(update.lat)
    if update.lon is not None:
        updates.append(f"lon = ${len(params) + 1}")
        params.append(update.lon)
    if update.description is not None:
        updates.append(f"description = ${len(params) + 1}")
        params.append(update.description)
    if update.work_start is not None:
        updates.append(f"work_start = ${len(params) + 1}")
        params.append(update.work_start)
    if update.work_end is not None:
        updates.append(f"work_end = ${len(params) + 1}")
        params.append(update.work_end)
    
    if updates:
        params.append(master_id)
        await db.execute(f"UPDATE masters SET {', '.join(updates)} WHERE id = ${len(params)}", *params)
    return {"status": "updated"}

@app.delete("/masters/{master_id}")
async def delete_master(master_id: int):
    await db.execute("DELETE FROM masters WHERE id = $1", master_id)
    return {"status": "deleted"}

# ========== СЛОТЫ С УЧЁТОМ ДЛИТЕЛЬНОСТИ ==========
@app.get("/masters/{master_id}/slots")
async def get_slots(master_id: int, date: str, service_id: int):
    service = await db.fetchrow("SELECT duration_min, name FROM services WHERE id = $1", service_id)
    if not service:
        raise HTTPException(404, "Service not found")
    duration = service["duration_min"]
    
    master = await db.fetchrow("SELECT work_start, work_end FROM masters WHERE id = $1", master_id)
    if not master:
        raise HTTPException(404, "Master not found")
    
    days_off = await db.fetch("SELECT date FROM master_days_off WHERE master_id = $1 AND date = $2", master_id, date)
    if days_off:
        return {"booked_slots": [], "booked_durations": {}, "service_duration": duration, "is_day_off": True}
    
    work_start_hour = int(master["work_start"].split(":")[0])
    work_start_min = int(master["work_start"].split(":")[1])
    work_end_hour = int(master["work_end"].split(":")[0])
    work_end_min = int(master["work_end"].split(":")[1])
    work_start = work_start_hour * 60 + work_start_min
    work_end = work_end_hour * 60 + work_end_min
    
    booked = await db.fetch("""
        SELECT b.time, s.duration_min, b.id
        FROM bookings b
        JOIN services s ON b.service_id = s.id
        WHERE b.master_id = $1 AND b.date = $2 AND b.status NOT IN ('cancelled', 'rejected')
    """, master_id, date)
    
    booked_slots = [b["time"] for b in booked]
    booked_durations = {b["time"]: b["duration_min"] for b in booked}
    
    all_slots = []
    for minute in range(work_start, work_end - duration + 1, 30):
        hour = minute // 60
        min_val = minute % 60
        slot_time = f"{hour:02d}:{min_val:02d}"
        all_slots.append(slot_time)
    
    def is_overlapping(time, dur):
        sh, sm = map(int, time.split(':'))
        start = sh * 60 + sm
        end = start + dur
        for bs in booked_slots:
            bh, bm = map(int, bs.split(':'))
            b_start = bh * 60 + bm
            b_dur = booked_durations.get(bs, 60)
            b_end = b_start + b_dur
            if not (end <= b_start or start >= b_end):
                return True
        return False
    
    available_slots = [slot for slot in all_slots if not is_overlapping(slot, duration)]
    
    return {
        "booked_slots": booked_slots,
        "booked_durations": booked_durations,
        "service_duration": duration,
        "available_slots": available_slots,
        "work_start": master["work_start"],
        "work_end": master["work_end"]
    }

# ========== УСЛУГИ ==========
@app.get("/masters/{master_id}/services")
async def get_master_services(master_id: int):
    rows = await db.fetch("SELECT id, name, price, duration_min FROM services WHERE master_id = $1 ORDER BY id", master_id)
    return [dict(r) for r in rows]

@app.post("/masters/{master_id}/services")
async def add_service(master_id: int, service: ServiceCreate):
    service_id = await db.execute("""
        INSERT INTO services (master_id, name, price, duration_min)
        VALUES ($1, $2, $3, $4)
        RETURNING id
    """, master_id, service.name, service.price, service.duration_min)
    return {"id": service_id, "status": "created"}

@app.put("/services/{service_id}")
async def update_service(service_id: int, update: ServiceUpdate):
    updates = []
    params = []
    if update.name is not None:
        updates.append(f"name = ${len(params) + 1}")
        params.append(update.name)
    if update.price is not None:
        updates.append(f"price = ${len(params) + 1}")
        params.append(update.price)
    if update.duration_min is not None:
        updates.append(f"duration_min = ${len(params) + 1}")
        params.append(update.duration_min)
    
    if updates:
        params.append(service_id)
        await db.execute(f"UPDATE services SET {', '.join(updates)} WHERE id = ${len(params)}", *params)
    return {"status": "updated"}

@app.delete("/services/{service_id}")
async def delete_service(service_id: int):
    await db.execute("DELETE FROM services WHERE id = $1", service_id)
    return {"status": "deleted"}

# ========== ЗАПИСИ ==========
@app.post("/bookings")
async def create_booking(booking: BookingCreate):
    service = await db.fetchrow("SELECT duration_min, price FROM services WHERE id = $1", booking.service_id)
    if not service:
        raise HTTPException(400, "Service not found")
    
    [sh, sm] = map(int, booking.time.split(':'))
    new_start = sh * 60 + sm
    new_end = new_start + service["duration_min"]
    
    existing = await db.fetch("""
        SELECT b.time, s.duration_min
        FROM bookings b
        JOIN services s ON b.service_id = s.id
        WHERE b.master_id = $1 AND b.date = $2 AND b.status NOT IN ('cancelled', 'rejected')
    """, booking.master_id, booking.date)
    
    for ex in existing:
        [eh, em] = map(int, ex["time"].split(':'))
        ex_start = eh * 60 + em
        ex_end = ex_start + ex["duration_min"]
        if not (new_end <= ex_start or new_start >= ex_end):
            raise HTTPException(400, "Time slot overlaps with existing booking")
    
    deposit_amount = int(service["price"] * 0.07)
    
    booking_id = await db.execute("""
        INSERT INTO bookings (master_id, service_id, client_name, client_telegram_id, client_phone, date, time, price, deposit_amount, status, created_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'pending', NOW())
        RETURNING id
    """, booking.master_id, booking.service_id, booking.client_name, booking.client_telegram_id,
        booking.client_phone, booking.date, booking.time, service["price"], deposit_amount)
    
    # Создаём уведомление
    await db.execute("""
        INSERT INTO notifications (user_id, type, title, message)
        VALUES ($1, 'booking_created', '✅ Новая запись', 'Вы записаны на $2 $3 в $4')
    """, int(booking.client_telegram_id), service["name"], booking.date, booking.time)
    
    # Отправляем напоминание мастеру
    master = await db.fetchrow("SELECT telegram_id FROM masters WHERE id = $1", booking.master_id)
    if master and master["telegram_id"]:
        await db.execute("""
            INSERT INTO notifications (user_id, type, title, message)
            VALUES ($1, 'new_booking', '📅 Новая запись!', 'Клиент $2 записался на $3 $4 в $5')
        """, master["telegram_id"], booking.client_name, service["name"], booking.date, booking.time)
    
    return {"booking_id": booking_id, "status": "created", "deposit_amount": deposit_amount}

@app.get("/bookings/client/{telegram_id}")
async def get_client_bookings(telegram_id: str):
    rows = await db.fetch("""
        SELECT b.id, b.date, b.time, b.price, b.status, b.review_given, b.deposit_paid,
               m.id as master_id, m.name as master_name, s.id as service_id, s.name as service_name, s.duration_min
        FROM bookings b
        JOIN masters m ON b.master_id = m.id
        JOIN services s ON b.service_id = s.id
        WHERE b.client_telegram_id = $1
        ORDER BY b.date DESC, b.time DESC
    """, telegram_id)
    return [dict(r) for r in rows]

@app.get("/bookings/master/{master_id}")
async def get_master_bookings(master_id: int, date: Optional[str] = None, status: Optional[str] = None):
    query = """
        SELECT b.id, b.date, b.time, b.price, b.status, b.client_name, b.client_telegram_id, b.review_given,
               s.id as service_id, s.name as service_name, s.duration_min
        FROM bookings b
        JOIN services s ON b.service_id = s.id
        WHERE b.master_id = $1
    """
    params = [master_id]
    if date:
        query += " AND b.date = $" + str(len(params) + 1)
        params.append(date)
    if status:
        query += " AND b.status = $" + str(len(params) + 1)
        params.append(status)
    query += " ORDER BY b.date DESC, b.time DESC"
    
    rows = await db.fetch(query, *params)
    return [dict(r) for r in rows]

@app.get("/bookings/{booking_id}")
async def get_booking(booking_id: int):
    row = await db.fetchrow("""
        SELECT b.*, m.name as master_name, s.name as service_name, s.duration_min
        FROM bookings b
        JOIN masters m ON b.master_id = m.id
        JOIN services s ON b.service_id = s.id
        WHERE b.id = $1
    """, booking_id)
    if not row:
        raise HTTPException(404, "Booking not found")
    return dict(row)

@app.patch("/bookings/{booking_id}")
async def update_booking(booking_id: int, update: BookingUpdate):
    updates = []
    params = []
    if update.status is not None:
        updates.append(f"status = ${len(params) + 1}")
        params.append(update.status)
    if update.date is not None:
        updates.append(f"date = ${len(params) + 1}")
        params.append(update.date)
    if update.time is not None:
        updates.append(f"time = ${len(params) + 1}")
        params.append(update.time)
    
    if updates:
        params.append(booking_id)
        await db.execute(f"UPDATE bookings SET {', '.join(updates)} WHERE id = ${len(params)}", *params)
        
        if update.status == "confirmed":
            booking = await db.fetchrow("SELECT client_telegram_id, date, time FROM bookings WHERE id = $1", booking_id)
            if booking:
                await db.execute("""
                    INSERT INTO notifications (user_id, type, title, message)
                    VALUES ($1, 'booking_confirmed', '✅ Запись подтверждена!', 'Ваша запись на $2 в $3 подтверждена')
                """, int(booking["client_telegram_id"]), booking["date"], booking["time"])
        
        if update.status == "cancelled":
            booking = await db.fetchrow("SELECT client_telegram_id, date, time FROM bookings WHERE id = $1", booking_id)
            if booking:
                await db.execute("""
                    INSERT INTO notifications (user_id, type, title, message)
                    VALUES ($1, 'booking_cancelled', '❌ Запись отменена', 'Ваша запись на $2 в $3 отменена')
                """, int(booking["client_telegram_id"]), booking["date"], booking["time"])
            
            await db.execute("""
                UPDATE waitlist SET notified = FALSE
                WHERE master_id = (SELECT master_id FROM bookings WHERE id = $1) AND notified = TRUE
            """, booking_id)
    
    return {"status": "updated"}

@app.delete("/bookings/{booking_id}")
async def delete_booking(booking_id: int):
    await db.execute("DELETE FROM bookings WHERE id = $1", booking_id)
    return {"status": "deleted"}

# ========== ПРОФИЛЬ КЛИЕНТА ==========
@app.get("/client/profile/{telegram_id}")
async def get_client_profile(telegram_id: str):
    stats = await db.fetchrow("""
        SELECT 
            COUNT(*) as total_visits,
            COUNT(CASE WHEN review_given THEN 1 END) as reviews_count,
            COALESCE(SUM(price), 0) as total_spent,
            COALESCE(SUM(price) * 0.05, 0) as cashback_balance
        FROM bookings
        WHERE client_telegram_id = $1 AND status = 'confirmed'
    """, telegram_id)
    
    next_booking = await db.fetchrow("""
        SELECT b.id, b.date, b.time, b.price, b.status, m.name as master_name, s.name as service_name
        FROM bookings b
        JOIN masters m ON b.master_id = m.id
        JOIN services s ON b.service_id = s.id
        WHERE b.client_telegram_id = $1 AND b.status = 'confirmed' AND b.date >= CURRENT_DATE
        ORDER BY b.date ASC, b.time ASC
        LIMIT 1
    """, telegram_id)
    
    recent = await db.fetch("""
        SELECT b.id, b.date, b.time, b.price, b.review_given, m.name as master_name, s.name as service_name
        FROM bookings b
        JOIN masters m ON b.master_id = m.id
        JOIN services s ON b.service_id = s.id
        WHERE b.client_telegram_id = $1 AND b.status = 'confirmed'
        ORDER BY b.date DESC, b.time DESC
        LIMIT 10
    """, telegram_id)
    
    settings = await db.fetchrow("SELECT * FROM client_settings WHERE telegram_id = $1", telegram_id)
    
    total_visits = stats["total_visits"] if stats else 0
    if total_visits >= 50:
        level, discount, badge, next_level = "Платина", 20, "💎", 0
    elif total_visits >= 20:
        level, discount, badge, next_level = "Золото", 15, "🥇", 50
    elif total_visits >= 10:
        level, discount, badge, next_level = "Серебро", 10, "🥈", 20
    elif total_visits >= 5:
        level, discount, badge, next_level = "Бронза", 5, "🥉", 10
    else:
        level, discount, badge, next_level = "Новичок", 0, "🌱", 5
    
    return {
        "stats": dict(stats) if stats else {"total_visits": 0, "reviews_count": 0, "total_spent": 0, "cashback_balance": 0},
        "next_booking": dict(next_booking) if next_booking else None,
        "recent_bookings": [dict(r) for r in recent],
        "settings": dict(settings) if settings else None,
        "level": level,
        "level_discount": discount,
        "level_badge": badge,
        "visits_to_next_level": max(0, next_level - total_visits),
        "next_level_name": "Платина" if next_level == 50 else "Золото" if next_level == 20 else "Серебро" if next_level == 10 else "Бронза" if next_level == 5 else None
    }

@app.get("/client/stats/{telegram_id}")
async def get_client_stats(telegram_id: str):
    stats = await db.fetchrow("""
        SELECT 
            COUNT(*) as total_bookings,
            COUNT(CASE WHEN status = 'confirmed' THEN 1 END) as completed_bookings,
            COUNT(CASE WHEN status = 'cancelled' THEN 1 END) as cancelled_bookings,
            COALESCE(SUM(price), 0) as total_spent
        FROM bookings
        WHERE client_telegram_id = $1
    """, telegram_id)
    return dict(stats) if stats else {"total_bookings": 0, "completed_bookings": 0, "cancelled_bookings": 0, "total_spent": 0}

@app.patch("/client/settings/{telegram_id}")
async def update_client_settings(telegram_id: str, settings: ClientSettingsUpdate):
    await db.execute("""
        INSERT INTO client_settings (telegram_id, push_enabled, tg_notify_enabled, quiet_hour_start, quiet_hour_end, email, phone)
        VALUES ($1, COALESCE($2, TRUE), COALESCE($3, TRUE), COALESCE($4, '22:00'), COALESCE($5, '09:00'), $6, $7)
        ON CONFLICT (telegram_id) DO UPDATE SET
            push_enabled = COALESCE(EXCLUDED.push_enabled, client_settings.push_enabled),
            tg_notify_enabled = COALESCE(EXCLUDED.tg_notify_enabled, client_settings.tg_notify_enabled),
            quiet_hour_start = COALESCE(EXCLUDED.quiet_hour_start, client_settings.quiet_hour_start),
            quiet_hour_end = COALESCE(EXCLUDED.quiet_hour_end, client_settings.quiet_hour_end),
            email = COALESCE(EXCLUDED.email, client_settings.email),
            phone = COALESCE(EXCLUDED.phone, client_settings.phone)
    """, telegram_id, settings.push_enabled, settings.tg_notify_enabled, 
        settings.quiet_hour_start, settings.quiet_hour_end, settings.email, settings.phone)
    return {"status": "updated"}

# ========== ОТЗЫВЫ ==========
@app.post("/reviews")
async def create_review(review: ReviewCreate):
    booking = await db.fetchrow("SELECT master_id, client_telegram_id FROM bookings WHERE id = $1", review.booking_id)
    if not booking:
        raise HTTPException(404, "Booking not found")
    
    await db.execute("""
        INSERT INTO reviews (booking_id, user_id, master_id, rating, comment)
        VALUES ($1, $2, $3, $4, $5)
    """, review.booking_id, int(booking["client_telegram_id"]), booking["master_id"], review.rating, review.comment)
    
    await db.execute("UPDATE bookings SET review_given = TRUE WHERE id = $1", review.booking_id)
    
    avg_rating = await db.fetchval("SELECT AVG(rating) FROM reviews WHERE master_id = $1", booking["master_id"])
    reviews_count = await db.fetchval("SELECT COUNT(*) FROM reviews WHERE master_id = $1", booking["master_id"])
    await db.execute("UPDATE masters SET rating = $1, reviews_count = $2 WHERE id = $3", 
                     round(avg_rating, 1) if avg_rating else 0, reviews_count, booking["master_id"])
    
    return {"status": "created"}

@app.post("/api/review")
async def create_review_direct(review: ReviewDirectCreate):
    await db.execute("""
        INSERT INTO reviews (user_id, master_id, rating, comment)
        VALUES ($1, $2, $3, $4)
    """, review.user_id, review.master_id, review.rating, review.comment)
    
    avg_rating = await db.fetchval("SELECT AVG(rating) FROM reviews WHERE master_id = $1", review.master_id)
    reviews_count = await db.fetchval("SELECT COUNT(*) FROM reviews WHERE master_id = $1", review.master_id)
    await db.execute("UPDATE masters SET rating = $1, reviews_count = $2 WHERE id = $3", 
                     round(avg_rating, 1) if avg_rating else 0, reviews_count, review.master_id)
    
    return {"status": "created"}

@app.get("/reviews/master/{master_id}")
async def get_master_reviews(master_id: int, limit: int = 20):
    rows = await db.fetch("""
        SELECT r.rating, r.comment, r.created_at, b.client_name
        FROM reviews r
        LEFT JOIN bookings b ON r.booking_id = b.id
        WHERE r.master_id = $1
        ORDER BY r.created_at DESC
        LIMIT $2
    """, master_id, limit)
    return [dict(r) for r in rows]

# ========== УМНЫЕ ФУНКЦИИ ==========
@app.post("/api/reminder")
async def send_reminder(data: ReminderRequest):
    await db.execute("""
        INSERT INTO notifications (user_id, type, title, message)
        VALUES ($1, 'reminder', $2, $3)
    """, data.user_id, f"Напоминание за {data.hours_before}ч", data.message)
    
    # Здесь будет вызов Telegram бота
    print(f"[REMINDER] To {data.user_id} ({data.hours_before}h): {data.message}")
    return {"status": "sent"}

@app.post("/api/waitlist/add")
async def add_to_waitlist(data: WaitlistRequest):
    await db.execute("""
        INSERT INTO waitlist (user_id, service, master_id, created_at)
        VALUES ($1, $2, $3, NOW())
        ON CONFLICT (user_id, service, master_id) DO NOTHING
    """, data.user_id, data.service, data.master_id)
    
    await db.execute("""
        INSERT INTO notifications (user_id, type, title, message)
        VALUES ($1, 'waitlist', '📋 Вы в листе ожидания', 'Мы уведомим вас, когда появится свободное место на $2')
    """, data.user_id, data.service)
    
    return {"status": "added"}

@app.get("/api/waitlist/check/{master_id}")
async def check_waitlist(master_id: int):
    cancelled_bookings = await db.fetch("""
        SELECT b.date, b.time FROM bookings 
        WHERE master_id = $1 AND status = 'cancelled' AND date >= CURRENT_DATE
    """, master_id)
    
    if cancelled_bookings:
        waitlist_users = await db.fetch("SELECT user_id, service FROM waitlist WHERE master_id = $1 AND notified = FALSE", master_id)
        for user in waitlist_users:
            await db.execute("""
                INSERT INTO notifications (user_id, type, title, message)
                VALUES ($1, 'waitlist_free', '🎉 Место освободилось!', 'Скорее запишитесь на $2')
            """, user["user_id"], user["service"])
            await db.execute("UPDATE waitlist SET notified = TRUE WHERE user_id = $1 AND master_id = $2", user["user_id"], master_id)
    
    return {"checked": True}

@app.post("/api/repeat/trigger")
async def trigger_repeat(data: dict):
    user_id = data.get("user_id")
    last_booking = await db.fetchrow("""
        SELECT b.date, s.name as service_name
        FROM bookings b
        JOIN services s ON b.service_id = s.id
        WHERE b.client_telegram_id = $1 AND b.status = 'confirmed'
        ORDER BY b.date DESC
        LIMIT 1
    """, str(user_id) if user_id else None)
    
    if last_booking:
        await db.execute("""
            INSERT INTO notifications (user_id, type, title, message)
            VALUES ($1, 'repeat', '🔄 Пора повторить!', 'Прошло 3 недели с вашего последнего визита на $2. Время записаться снова! 💅')
        """, user_id, last_booking["service_name"])
    
    return {"status": "triggered"}

# ========== ПОРТФОЛИО ДО/ПОСЛЕ ==========
@app.get("/masters/{master_id}/before-after")
async def get_before_after(master_id: int):
    rows = await db.fetch("""
        SELECT id, before_photo, after_photo, description
        FROM master_before_after
        WHERE master_id = $1
        ORDER BY created_at DESC
    """, master_id)
    return [dict(r) for r in rows]

@app.post("/master/{telegram_id}/before-after")
async def add_before_after(telegram_id: int, data: BeforeAfterCreate):
    master = await db.fetchrow("SELECT id FROM masters WHERE telegram_id = $1", telegram_id)
    if not master:
        raise HTTPException(404, "Master not found")
    await db.execute("""
        INSERT INTO master_before_after (master_id, before_photo, after_photo, description)
        VALUES ($1, $2, $3, $4)
    """, master["id"], data.before_photo, data.after_photo, data.description)
    return {"status": "created"}

@app.delete("/master/{telegram_id}/before-after/{item_id}")
async def delete_before_after(telegram_id: int, item_id: int):
    await db.execute("""
        DELETE FROM master_before_after
        WHERE id = $1 AND master_id IN (SELECT id FROM masters WHERE telegram_id = $2)
    """, item_id, telegram_id)
    return {"status": "deleted"}

# ========== ПОРТФОЛИО ==========
@app.get("/masters/{master_id}/portfolio")
async def get_portfolio(master_id: int):
    rows = await db.fetch("SELECT id, photo_url, description FROM master_portfolio WHERE master_id = $1 ORDER BY created_at DESC", master_id)
    return [dict(r) for r in rows]

@app.post("/master/{telegram_id}/portfolio")
async def add_portfolio(telegram_id: int, data: PortfolioCreate):
    master = await db.fetchrow("SELECT id FROM masters WHERE telegram_id = $1", telegram_id)
    if not master:
        raise HTTPException(404, "Master not found")
    await db.execute("""
        INSERT INTO master_portfolio (master_id, photo_url, description)
        VALUES ($1, $2, $3)
    """, master["id"], data.photo_url, data.description)
    return {"status": "created"}

@app.delete("/master/{telegram_id}/portfolio/{photo_id}")
async def delete_portfolio(telegram_id: int, photo_id: int):
    await db.execute("""
        DELETE FROM master_portfolio
        WHERE id = $1 AND master_id IN (SELECT id FROM masters WHERE telegram_id = $2)
    """, photo_id, telegram_id)
    return {"status": "deleted"}

# ========== БЫСТРЫЕ ОТВЕТЫ ==========
@app.get("/master/{telegram_id}/quick-replies")
async def get_quick_replies(telegram_id: int):
    master = await db.fetchrow("SELECT id FROM masters WHERE telegram_id = $1", telegram_id)
    if not master:
        return []
    rows = await db.fetch("SELECT id, title, message FROM quick_replies WHERE master_id = $1", master["id"])
    return [dict(r) for r in rows]

@app.post("/master/{telegram_id}/quick-replies")
async def add_quick_reply(telegram_id: int, data: QuickReplyCreate):
    master = await db.fetchrow("SELECT id FROM masters WHERE telegram_id = $1", telegram_id)
    if not master:
        raise HTTPException(404, "Master not found")
    await db.execute("""
        INSERT INTO quick_replies (master_id, title, message)
        VALUES ($1, $2, $3)
    """, master["id"], data.title, data.message)
    return {"status": "created"}

@app.delete("/master/{telegram_id}/quick-replies/{reply_id}")
async def delete_quick_reply(telegram_id: int, reply_id: int):
    await db.execute("""
        DELETE FROM quick_replies
        WHERE id = $1 AND master_id IN (SELECT id FROM masters WHERE telegram_id = $2)
    """, reply_id, telegram_id)
    return {"status": "deleted"}

# ========== РАСПИСАНИЕ И ВЫХОДНЫЕ ==========
@app.get("/masters/{master_id}/schedule")
async def get_master_schedule(master_id: int, week_start: Optional[str] = None):
    if not week_start:
        week_start = datetime.now().strftime("%Y-%m-%d")
    
    master = await db.fetchrow("SELECT work_start, work_end FROM masters WHERE id = $1", master_id)
    if not master:
        raise HTTPException(404, "Master not found")
    
    days_off = await db.fetch("SELECT date FROM master_days_off WHERE master_id = $1 AND date >= $2", master_id, week_start)
    
    return {
        "work_start": master["work_start"],
        "work_end": master["work_end"],
        "days_off": [d["date"] for d in days_off]
    }

@app.post("/masters/{master_id}/days-off")
async def add_day_off(master_id: int, date: str):
    await db.execute("""
        INSERT INTO master_days_off (master_id, date)
        VALUES ($1, $2)
        ON CONFLICT DO NOTHING
    """, master_id, date)
    return {"status": "added"}

@app.delete("/masters/{master_id}/days-off/{date}")
async def remove_day_off(master_id: int, date: str):
    await db.execute("DELETE FROM master_days_off WHERE master_id = $1 AND date = $2", master_id, date)
    return {"status": "removed"}

# ========== ИЗБРАННОЕ ==========
@app.get("/favorites/{client_telegram_id}")
async def get_favorites(client_telegram_id: str):
    rows = await db.fetch("""
        SELECT f.master_id, m.name as master_name, m.rating, m.icon
        FROM favorites f
        JOIN masters m ON f.master_id = m.id
        WHERE f.client_telegram_id = $1
    """, client_telegram_id)
    return [dict(r) for r in rows]

@app.post("/favorites/{master_id}")
async def add_favorite(master_id: int, client_telegram_id: str):
    await db.execute("""
        INSERT INTO favorites (client_telegram_id, master_id)
        VALUES ($1, $2)
        ON CONFLICT DO NOTHING
    """, client_telegram_id, master_id)
    return {"status": "added"}

@app.delete("/favorites/{master_id}")
async def remove_favorite(master_id: int, client_telegram_id: str):
    await db.execute("DELETE FROM favorites WHERE client_telegram_id = $1 AND master_id = $2", client_telegram_id, master_id)
    return {"status": "removed"}

# ========== ЧАТ ==========
@app.get("/chat/messages/{booking_id}")
async def get_chat_messages(booking_id: int, user_id: str):
    await db.execute("""
        UPDATE chat_messages SET is_read = TRUE
        WHERE booking_id = $1 AND to_id = $2 AND is_read = FALSE
    """, booking_id, user_id)
    
    rows = await db.fetch("""
        SELECT id, from_id, to_id, message, is_read, created_at
        FROM chat_messages
        WHERE booking_id = $1
        ORDER BY created_at ASC
    """, booking_id)
    return [dict(r) for r in rows]

@app.post("/chat/send")
async def send_chat_message(data: ChatMessageSend):
    booking = await db.fetchrow("SELECT id FROM bookings WHERE id = $1", data.booking_id)
    if not booking:
        raise HTTPException(404, "Booking not found")
    
    await db.execute("""
        INSERT INTO chat_messages (booking_id, from_id, to_id, message, created_at)
        VALUES ($1, $2, $3, $4, NOW())
    """, data.booking_id, data.from_id, data.to_id, data.message)
    
    await db.execute("""
        INSERT INTO notifications (user_id, type, title, message)
        VALUES ($1, 'chat', '💬 Новое сообщение', 'Вам пришло новое сообщение в чате')
    """, int(data.to_id))
    
    return {"status": "sent"}

@app.get("/chat/unread/{user_id}")
async def get_unread_count(user_id: str):
    count = await db.fetchval("""
        SELECT COUNT(*) FROM chat_messages
        WHERE to_id = $1 AND is_read = FALSE
    """, user_id)
    return {"unread_count": count}

# ========== ПРОМОКОДЫ ==========
@app.get("/promocodes")
async def get_promocodes(active_only: bool = True):
    query = "SELECT id, code, discount_percent, expires_at, max_uses, used_count FROM promocodes"
    if active_only:
        query += " WHERE active = TRUE AND expires_at > NOW()"
    query += " ORDER BY created_at DESC"
    rows = await db.fetch(query)
    return [dict(r) for r in rows]

@app.get("/promocodes/active")
async def get_active_promocodes():
    rows = await db.fetch("""
        SELECT code, discount_percent, expires_at
        FROM promocodes
        WHERE active = TRUE AND expires_at > NOW() AND (max_uses IS NULL OR used_count < max_uses)
        LIMIT 10
    """)
    return [dict(r) for r in rows]

@app.post("/promocodes")
async def create_promocode(data: PromoCodeCreate):
    await db.execute("""
        INSERT INTO promocodes (code, discount_percent, expires_at, max_uses)
        VALUES ($1, $2, $3, $4)
    """, data.code.upper(), data.discount_percent, data.expires_at, data.max_uses)
    return {"status": "created"}

@app.post("/apply-promo")
async def apply_promo_code(data: PromoCodeApply):
    promo = await db.fetchrow("""
        SELECT id, discount_percent, max_uses, used_count
        FROM promocodes
        WHERE code = $1 AND active = TRUE AND expires_at > NOW()
    """, data.promo_code.upper())
    
    if not promo:
        raise HTTPException(400, "Invalid or expired promo code")
    
    if promo["max_uses"] and promo["used_count"] >= promo["max_uses"]:
        raise HTTPException(400, "Promo code has reached maximum uses")
    
    used_before = await db.fetchval("SELECT id FROM user_promocodes WHERE user_id = $1 AND promo_code_id = $2", data.user_id, promo["id"])
    if used_before:
        raise HTTPException(400, "You have already used this promo code")
    
    await db.execute("""
        INSERT INTO user_promocodes (user_id, promo_code_id, booking_id)
        VALUES ($1, $2, $3)
    """, data.user_id, promo["id"], data.booking_id)
    
    await db.execute("UPDATE promocodes SET used_count = used_count + 1 WHERE id = $1", promo["id"])
    
    return {"discount_percent": promo["discount_percent"], "status": "applied"}

# ========== ПОДДЕРЖКА ==========
@app.post("/support")
async def create_support_request(data: SupportRequest):
    request_id = await db.execute("""
        INSERT INTO support_requests (user_id, subject, message, created_at)
        VALUES ($1, $2, $3, NOW())
        RETURNING id
    """, data.user_id, data.subject, data.message)
    
    await db.execute("""
        INSERT INTO notifications (user_id, type, title, message)
        VALUES ($1, 'support', '🆘 Запрос в поддержку', 'Ваш запрос #$2 получен. Мы ответим в ближайшее время')
    """, data.user_id, request_id)
    
    return {"request_id": request_id, "status": "created"}

@app.get("/support/{user_id}")
async def get_user_support_requests(user_id: int):
    rows = await db.fetch("""
        SELECT id, subject, message, status, admin_response, created_at, resolved_at
        FROM support_requests
        WHERE user_id = $1
        ORDER BY created_at DESC
    """, user_id)
    return [dict(r) for r in rows]

# ========== НАПОМИНАНИЯ (СИСТЕМНЫЕ) ==========
@app.get("/notifications/{user_id}")
async def get_notifications(user_id: int, unread_only: bool = False):
    query = "SELECT id, type, title, message, is_read, created_at FROM notifications WHERE user_id = $1"
    params = [user_id]
    if unread_only:
        query += " AND is_read = FALSE"
    query += " ORDER BY created_at DESC LIMIT 50"
    
    rows = await db.fetch(query, *params)
    return [dict(r) for r in rows]

@app.patch("/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: int):
    await db.execute("UPDATE notifications SET is_read = TRUE WHERE id = $1", notification_id)
    return {"status": "updated"}

@app.post("/notifications/mark-all-read/{user_id}")
async def mark_all_notifications_read(user_id: int):
    await db.execute("UPDATE notifications SET is_read = TRUE WHERE user_id = $1", user_id)
    return {"status": "updated"}

# ========== СТАТИСТИКА МАСТЕРА ==========
@app.get("/master/{telegram_id}/stats")
async def get_master_stats(telegram_id: int):
    master = await db.fetchrow("SELECT id, completed_bookings FROM masters WHERE telegram_id = $1", telegram_id)
    if not master:
        return {"completed": 0, "pending": 0, "revenue": 0, "this_week": 0, "last_week": 0}
    
    completed = await db.fetchval("SELECT COUNT(*) FROM bookings WHERE master_id = $1 AND status = 'confirmed'", master["id"])
    pending = await db.fetchval("SELECT COUNT(*) FROM bookings WHERE master_id = $1 AND status = 'pending'", master["id"])
    revenue = await db.fetchval("SELECT COALESCE(SUM(price), 0) FROM bookings WHERE master_id = $1 AND status = 'confirmed'", master["id"])
    
    this_week = await db.fetchval("""
        SELECT COALESCE(SUM(price), 0) FROM bookings 
        WHERE master_id = $1 AND status = 'confirmed' 
        AND date >= date_trunc('week', CURRENT_DATE)
    """, master["id"])
    
    last_week = await db.fetchval("""
        SELECT COALESCE(SUM(price), 0) FROM bookings 
        WHERE master_id = $1 AND status = 'confirmed' 
        AND date >= date_trunc('week', CURRENT_DATE - INTERVAL '7 days')
        AND date < date_trunc('week', CURRENT_DATE)
    """, master["id"])
    
    avg_rating = await db.fetchval("SELECT AVG(rating) FROM reviews WHERE master_id = $1", master["id"])
    
    return {
        "completed": completed,
        "pending": pending,
        "revenue": revenue,
        "this_week": this_week,
        "last_week": last_week,
        "avg_rating": round(avg_rating, 1) if avg_rating else 0,
        "reviews_count": await db.fetchval("SELECT COUNT(*) FROM reviews WHERE master_id = $1", master["id"])
    }

@app.patch("/master/{telegram_id}/work-hours")
async def update_work_hours(telegram_id: int, work_start: str, work_end: str):
    await db.execute("""
        UPDATE masters SET work_start = $1, work_end = $2
        WHERE telegram_id = $3
    """, work_start, work_end, telegram_id)
    return {"status": "updated"}

@app.patch("/master/{telegram_id}/profile")
async def update_master_profile(telegram_id: int, description: Optional[str] = None, icon: Optional[str] = None):
    updates = []
    params = []
    if description is not None:
        updates.append(f"description = ${len(params) + 1}")
        params.append(description)
    if icon is not None:
        updates.append(f"icon = ${len(params) + 1}")
        params.append(icon)
    
    if updates:
        params.append(telegram_id)
        await db.execute(f"UPDATE masters SET {', '.join(updates)} WHERE telegram_id = ${len(params)}", *params)
    return {"status": "updated"}

@app.patch("/master/{telegram_id}/location")
async def update_master_location(telegram_id: int, lat: float, lon: float):
    await db.execute("UPDATE masters SET lat = $1, lon = $2 WHERE telegram_id = $3", lat, lon, telegram_id)
    return {"status": "updated"}

# ========== ПЛАТЕЖИ ==========
@app.post("/payments/create")
async def create_payment(data: PaymentCreate):
    payment_id = await db.execute("""
        INSERT INTO payments (booking_id, user_id, amount, payment_method, payment_status, created_at)
        VALUES ($1, $2, $3, $4, 'pending', NOW())
        RETURNING id
    """, data.booking_id, data.user_id, data.amount, data.payment_method)
    
    # Здесь будет интеграция с платёжной системой (Stripe, YooKassa, Telegram Stars)
    return {"payment_id": payment_id, "payment_url": f"https://t.me/beauty_bot/pay_{payment_id}"}

@app.get("/payments/{payment_id}/status")
async def get_payment_status(payment_id: int):
    payment = await db.fetchrow("SELECT payment_status, amount FROM payments WHERE id = $1", payment_id)
    if not payment:
        raise HTTPException(404, "Payment not found")
    return {"status": payment["payment_status"], "amount": payment["amount"]}

@app.post("/payments/webhook")
async def payment_webhook(data: dict):
    payment_id = data.get("payment_id")
    status = data.get("status")
    if payment_id and status == "succeeded":
        await db.execute("UPDATE payments SET payment_status = 'completed' WHERE id = $1", payment_id)
        payment = await db.fetchrow("SELECT booking_id FROM payments WHERE id = $1", payment_id)
        if payment:
            await db.execute("UPDATE bookings SET deposit_paid = TRUE, status = 'confirmed' WHERE id = $1", payment["booking_id"])
    return {"status": "ok"}

# ========== УТИЛИТЫ ==========
@app.get("/health")
async def health_check():
    if db:
        await db.execute("SELECT 1")
    return {"status": "ok", "timestamp": datetime.now().isoformat()}

@app.get("/search")
async def search_masters(q: str, limit: int = 20):
    rows = await db.fetch("""
        SELECT id, name, lat, lon, rating, description, icon
        FROM masters
        WHERE name ILIKE $1 OR description ILIKE $1
        LIMIT $2
    """, f"%{q}%", limit)
    return [dict(r) for r in rows]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
