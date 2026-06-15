from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional
import asyncpg
import os
from datetime import datetime, timedelta
import uvicorn

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost/beauty")
db = None

# ========== МОДЕЛИ ==========
class MasterCreate(BaseModel):
    telegram_id: Optional[int] = None
    name: str
    lat: float
    lon: float
    description: Optional[str] = None

class ServiceCreate(BaseModel):
    name: str
    price: int
    duration_min: int

class BookingCreate(BaseModel):
    master_id: int
    service_id: int
    client_name: str
    client_telegram_id: str
    client_phone: Optional[str] = None
    date: str
    time: str

class PromoCreate(BaseModel):
    code: str
    discount_percent: int
    expires_at: str
    max_uses: Optional[int] = 100

# ========== ЗАПУСК ==========
@app.on_event("startup")
async def startup():
    global db
    try:
        db = await asyncpg.connect(DATABASE_URL)
        await init_db()
        print("✅ Database connected")
    except Exception as e:
        print(f"❌ Database error: {e}")

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
            master_id INTEGER,
            created_at TIMESTAMP DEFAULT NOW(),
            notified BOOLEAN DEFAULT FALSE
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
        CREATE TABLE IF NOT EXISTS promocodes (
            id SERIAL PRIMARY KEY,
            code VARCHAR(50) UNIQUE NOT NULL,
            discount_percent INTEGER NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            max_uses INTEGER DEFAULT 100,
            used_count INTEGER DEFAULT 0,
            active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS client_settings (
            telegram_id VARCHAR(50) PRIMARY KEY,
            push_enabled BOOLEAN DEFAULT TRUE,
            tg_notify_enabled BOOLEAN DEFAULT TRUE,
            email VARCHAR(100),
            phone VARCHAR(20)
        )
    """)
    
    # Восстановление мастеров при пустой БД
    count = await db.fetchval("SELECT COUNT(*) FROM masters")
    if count == 0:
        await db.execute("""
            INSERT INTO masters (telegram_id, name, lat, lon, description, rating, reviews_count) VALUES
            (777000, 'Алина Козлова', 47.222078, 39.720358, '🌸 Мастер маникюра с 5-летним опытом', 4.9, 128),
            (777001, 'Елена Соколова', 47.225000, 39.725000, '👑 Топ-мастер по бровам и ресницам', 4.95, 256),
            (777002, 'Дмитрий Волков', 47.218000, 39.718000, '💈 Мужской мастер. Стрижки, бороды', 4.85, 89)
        """)
        await db.execute("""
            INSERT INTO services (master_id, name, price, duration_min) VALUES
            (1, 'Маникюр классический', 1200, 60),
            (1, 'Маникюр с покрытием гель-лак', 2000, 90),
            (2, 'Коррекция бровей', 800, 40),
            (2, 'Ламинирование ресниц', 2500, 90),
            (3, 'Мужская стрижка', 1200, 45),
            (3, 'Стрижка + борода', 1800, 60)
        """)
        print("✅ Восстановлены тестовые мастера")

# ========== МАСТЕРА ==========
@app.get("/masters")
async def get_masters():
    rows = await db.fetch("SELECT id, name, lat, lon, rating, reviews_count, description, icon FROM masters")
    result = []
    for r in rows:
        services = await db.fetch("SELECT id, name, price, duration_min FROM services WHERE master_id = $1", r["id"])
        result.append({**dict(r), "services": [dict(s) for s in services]})
    return result

@app.get("/masters/{master_id}")
async def get_master(master_id: int):
    row = await db.fetchrow("SELECT * FROM masters WHERE id = $1", master_id)
    if not row:
        raise HTTPException(404, "Master not found")
    services = await db.fetch("SELECT id, name, price, duration_min FROM services WHERE master_id = $1", master_id)
    return {**dict(row), "services": [dict(s) for s in services]}

@app.get("/masters/by_telegram/{telegram_id}")
async def get_master_by_telegram(telegram_id: int):
    row = await db.fetchrow("SELECT id, name FROM masters WHERE telegram_id = $1", telegram_id)
    return dict(row) if row else None

@app.post("/masters")
async def create_master(master: MasterCreate):
    master_id = await db.execute("""
        INSERT INTO masters (telegram_id, name, lat, lon, description)
        VALUES ($1, $2, $3, $4, $5) RETURNING id
    """, master.telegram_id, master.name, master.lat, master.lon, master.description)
    return {"id": master_id, "status": "created"}

@app.patch("/masters/{master_id}")
async def update_master(master_id: int, data: dict):
    if "telegram_id" in data:
        await db.execute("UPDATE masters SET telegram_id = $1 WHERE id = $2", data["telegram_id"], master_id)
    if "name" in data:
        await db.execute("UPDATE masters SET name = $1 WHERE id = $2", data["name"], master_id)
    if "description" in data:
        await db.execute("UPDATE masters SET description = $1 WHERE id = $2", data["description"], master_id)
    return {"status": "updated"}

@app.delete("/masters/{master_id}")
async def delete_master(master_id: int):
    await db.execute("DELETE FROM masters WHERE id = $1", master_id)
    return {"status": "deleted"}

# ========== УСЛУГИ ==========
@app.get("/master/{telegram_id}/services")
async def get_master_services(telegram_id: int):
    master = await db.fetchrow("SELECT id FROM masters WHERE telegram_id = $1", telegram_id)
    if not master:
        return []
    rows = await db.fetch("SELECT id, name, price, duration_min FROM services WHERE master_id = $1", master["id"])
    return [dict(r) for r in rows]

@app.post("/master/{telegram_id}/services")
async def add_service(telegram_id: int, service: ServiceCreate):
    master = await db.fetchrow("SELECT id FROM masters WHERE telegram_id = $1", telegram_id)
    if not master:
        raise HTTPException(404, "Master not found")
    service_id = await db.execute("""
        INSERT INTO services (master_id, name, price, duration_min)
        VALUES ($1, $2, $3, $4) RETURNING id
    """, master["id"], service.name, service.price, service.duration_min)
    return {"id": service_id, "status": "created"}

@app.delete("/services/{service_id}")
async def delete_service(service_id: int):
    await db.execute("DELETE FROM services WHERE id = $1", service_id)
    return {"status": "deleted"}

# ========== СЛОТЫ ==========
@app.get("/masters/{master_id}/slots")
async def get_slots(master_id: int, date: str, service_id: int):
    service = await db.fetchrow("SELECT duration_min FROM services WHERE id = $1", service_id)
    if not service:
        raise HTTPException(404, "Service not found")
    
    booked = await db.fetch("""
        SELECT b.time, s.duration_min 
        FROM bookings b JOIN services s ON b.service_id = s.id
        WHERE b.master_id = $1 AND b.date = $2 AND b.status NOT IN ('cancelled')
    """, master_id, date)
    
    return {
        "booked_slots": [b["time"] for b in booked],
        "booked_durations": {b["time"]: b["duration_min"] for b in booked},
        "service_duration": service["duration_min"]
    }

# ========== ЗАПИСИ ==========
@app.post("/bookings")
async def create_booking(booking: BookingCreate):
    service = await db.fetchrow("SELECT duration_min, price FROM services WHERE id = $1", booking.service_id)
    if not service:
        raise HTTPException(400, "Service not found")
    
    # Проверка пересечения слотов
    [sh, sm] = map(int, booking.time.split(':'))
    new_start = sh * 60 + sm
    new_end = new_start + service["duration_min"]
    
    existing = await db.fetch("""
        SELECT b.time, s.duration_min
        FROM bookings b JOIN services s ON b.service_id = s.id
        WHERE b.master_id = $1 AND b.date = $2 AND b.status NOT IN ('cancelled')
    """, booking.master_id, booking.date)
    
    for ex in existing:
        [eh, em] = map(int, ex["time"].split(':'))
        ex_start = eh * 60 + em
        ex_end = ex_start + ex["duration_min"]
        if not (new_end <= ex_start or new_start >= ex_end):
            raise HTTPException(400, "Time slot overlaps with existing booking")
    
    booking_id = await db.execute("""
        INSERT INTO bookings (master_id, service_id, client_name, client_telegram_id, client_phone, date, time, price, status)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'pending') RETURNING id
    """, booking.master_id, booking.service_id, booking.client_name, booking.client_telegram_id,
        booking.client_phone, booking.date, booking.time, service["price"])
    
    return {"booking_id": booking_id, "status": "created"}

@app.get("/bookings/client/{telegram_id}")
async def get_client_bookings(telegram_id: str):
    rows = await db.fetch("""
        SELECT b.id, b.date, b.time, b.price, b.status, b.review_given,
               m.name as master_name, s.name as service_name
        FROM bookings b
        JOIN masters m ON b.master_id = m.id
        JOIN services s ON b.service_id = s.id
        WHERE b.client_telegram_id = $1
        ORDER BY b.date DESC, b.time DESC
    """, telegram_id)
    return [dict(r) for r in rows]

@app.get("/bookings/master/{master_id}")
async def get_master_bookings(master_id: int):
    rows = await db.fetch("""
        SELECT b.id, b.date, b.time, b.price, b.status, b.client_name, b.client_telegram_id,
               s.name as service_name
        FROM bookings b
        JOIN services s ON b.service_id = s.id
        WHERE b.master_id = $1
        ORDER BY b.date DESC, b.time DESC
    """, master_id)
    return [dict(r) for r in rows]

@app.patch("/bookings/{booking_id}/status")
async def update_booking_status(booking_id: int, status: str):
    await db.execute("UPDATE bookings SET status = $1 WHERE id = $2", status, booking_id)
    return {"status": "ok"}

# ========== ОТЗЫВЫ ==========
@app.post("/reviews")
async def create_review(data: dict):
    booking_id = data.get("booking_id")
    rating = data.get("rating")
    comment = data.get("comment")
    
    booking = await db.fetchrow("SELECT master_id, client_telegram_id FROM bookings WHERE id = $1", booking_id)
    if not booking:
        raise HTTPException(404, "Booking not found")
    
    await db.execute("""
        INSERT INTO reviews (booking_id, user_id, master_id, rating, comment)
        VALUES ($1, $2, $3, $4, $5)
    """, booking_id, int(booking["client_telegram_id"]), booking["master_id"], rating, comment)
    
    await db.execute("UPDATE bookings SET review_given = TRUE WHERE id = $1", booking_id)
    
    avg = await db.fetchval("SELECT AVG(rating) FROM reviews WHERE master_id = $1", booking["master_id"])
    cnt = await db.fetchval("SELECT COUNT(*) FROM reviews WHERE master_id = $1", booking["master_id"])
    await db.execute("UPDATE masters SET rating = $1, reviews_count = $2 WHERE id = $3", round(avg, 1), cnt, booking["master_id"])
    
    return {"status": "created"}

@app.post("/api/review")
async def create_review_direct(data: dict):
    await db.execute("""
        INSERT INTO reviews (user_id, master_id, rating, comment)
        VALUES ($1, $2, $3, $4)
    """, data["user_id"], data["master_id"], data["rating"], data.get("comment", ""))
    
    avg = await db.fetchval("SELECT AVG(rating) FROM reviews WHERE master_id = $1", data["master_id"])
    await db.execute("UPDATE masters SET rating = $1 WHERE id = $2", round(avg, 1), data["master_id"])
    return {"status": "created"}

# ========== УМНЫЕ ФУНКЦИИ ==========
@app.post("/api/reminder")
async def send_reminder(data: dict):
    print(f"[REMINDER] To {data['user_id']}: {data['message']}")
    return {"status": "sent"}

@app.post("/api/waitlist/add")
async def add_to_waitlist(data: dict):
    await db.execute("""
        INSERT INTO waitlist (user_id, service, master_id)
        VALUES ($1, $2, $3)
        ON CONFLICT DO NOTHING
    """, data["user_id"], data.get("service", ""), data.get("master_id"))
    return {"status": "added"}

@app.post("/api/repeat/trigger")
async def trigger_repeat(data: dict):
    print(f"[REPEAT] To {data.get('user_id')}: Пора повторить!")
    return {"status": "triggered"}

# ========== ПРОМОКОДЫ ==========
@app.get("/promocodes/active")
async def get_active_promocodes():
    rows = await db.fetch("""
        SELECT code, discount_percent, expires_at
        FROM promocodes
        WHERE active = TRUE AND expires_at > NOW()
        LIMIT 10
    """)
    return [dict(r) for r in rows]

@app.post("/promocodes")
async def create_promo(promo: PromoCreate):
    await db.execute("""
        INSERT INTO promocodes (code, discount_percent, expires_at, max_uses)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (code) DO UPDATE SET
            discount_percent = EXCLUDED.discount_percent,
            expires_at = EXCLUDED.expires_at,
            active = TRUE
    """, promo.code.upper(), promo.discount_percent, promo.expires_at, promo.max_uses)
    return {"status": "created"}

@app.post("/apply-promo")
async def apply_promo(data: dict):
    promo = await db.fetchrow("""
        SELECT discount_percent FROM promocodes
        WHERE code = $1 AND active = TRUE AND expires_at > NOW()
    """, data.get("promo_code", "").upper())
    if not promo:
        raise HTTPException(400, "Invalid promo code")
    return {"discount_percent": promo["discount_percent"]}

# ========== ИЗБРАННОЕ ==========
@app.get("/favorites/{client_telegram_id}")
async def get_favorites(client_telegram_id: str):
    rows = await db.fetch("""
        SELECT f.master_id, m.name as master_name, m.rating
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
    await db.execute("""
        DELETE FROM favorites
        WHERE client_telegram_id = $1 AND master_id = $2
    """, client_telegram_id, master_id)
    return {"status": "removed"}

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
        SELECT b.id, b.date, b.time, b.price, m.name as master_name, s.name as service_name
        FROM bookings b
        JOIN masters m ON b.master_id = m.id
        JOIN services s ON b.service_id = s.id
        WHERE b.client_telegram_id = $1 AND b.status = 'confirmed' AND b.date >= CURRENT_DATE
        ORDER BY b.date ASC, b.time ASC LIMIT 1
    """, telegram_id)
    
    recent = await db.fetch("""
        SELECT b.id, b.date, b.time, b.price, m.name as master_name, s.name as service_name
        FROM bookings b
        JOIN masters m ON b.master_id = m.id
        JOIN services s ON b.service_id = s.id
        WHERE b.client_telegram_id = $1 AND b.status = 'confirmed'
        ORDER BY b.date DESC, b.time DESC LIMIT 5
    """, telegram_id)
    
    total = stats["total_visits"] if stats else 0
    if total >= 50:
        level, discount, badge = "Платина", 20, "💎"
    elif total >= 20:
        level, discount, badge = "Золото", 15, "🥇"
    elif total >= 10:
        level, discount, badge = "Серебро", 10, "🥈"
    elif total >= 5:
        level, discount, badge = "Бронза", 5, "🥉"
    else:
        level, discount, badge = "Новичок", 0, "🌱"
    
    return {
        "stats": dict(stats) if stats else {"total_visits": 0, "reviews_count": 0, "total_spent": 0, "cashback_balance": 0},
        "next_booking": dict(next_booking) if next_booking else None,
        "recent_bookings": [dict(r) for r in recent],
        "level": level,
        "level_discount": discount,
        "level_badge": badge,
        "visits_to_next_level": max(0, (5 if total < 5 else 10 if total < 10 else 20 if total < 20 else 50 if total < 50 else 0) - total)
    }

@app.patch("/client/settings/{telegram_id}")
async def update_client_settings(telegram_id: str, data: dict):
    await db.execute("""
        INSERT INTO client_settings (telegram_id, push_enabled, tg_notify_enabled, email, phone)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (telegram_id) DO UPDATE SET
            push_enabled = EXCLUDED.push_enabled,
            tg_notify_enabled = EXCLUDED.tg_notify_enabled,
            email = EXCLUDED.email,
            phone = EXCLUDED.phone
    """, telegram_id, data.get("push_enabled", True), data.get("tg_notify_enabled", True),
        data.get("email"), data.get("phone"))
    return {"status": "updated"}

# ========== СТАТИСТИКА ДЛЯ АДМИНА ==========
@app.get("/admin/stats")
async def admin_stats():
    masters = await db.fetchval("SELECT COUNT(*) FROM masters")
    bookings = await db.fetchval("SELECT COUNT(*) FROM bookings")
    revenue = await db.fetchval("SELECT COALESCE(SUM(price), 0) FROM bookings WHERE status = 'confirmed'")
    clients = await db.fetchval("SELECT COUNT(DISTINCT client_telegram_id) FROM bookings")
    promos = await db.fetchval("SELECT COUNT(*) FROM promocodes")
    return {
        "masters_count": masters or 0,
        "bookings_count": bookings or 0,
        "revenue": revenue or 0,
        "clients_count": clients or 0,
        "promocodes_count": promos or 0
    }

@app.post("/user/register")
async def register_user(data: dict):
    await db.execute("""
        INSERT INTO client_settings (telegram_id, email, phone)
        VALUES ($1, $2, $3)
        ON CONFLICT (telegram_id) DO NOTHING
    """, data.get("telegram_id"), data.get("username"), data.get("name"))
    return {"status": "ok"}

# ========== ЗДОРОВЬЕ ==========
@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
