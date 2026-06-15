from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import asyncpg
import os
from datetime import datetime, timedelta

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost/beauty")
db = None

# ========== МОДЕЛИ ==========
class BookingCreate(BaseModel):
    master_id: int
    service_id: int
    client_name: str
    client_telegram_id: str
    client_phone: Optional[str] = None
    date: str
    time: str

class ServiceCreate(BaseModel):
    name: str
    price: int
    duration_min: int

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

class BeforeAfterCreate(BaseModel):
    before_photo: str
    after_photo: str
    description: Optional[str] = None

class QuickReplyCreate(BaseModel):
    title: str
    message: str

class ChatMessageSend(BaseModel):
    booking_id: int
    from_id: str
    to_id: str
    message: str

class ClientSettingsUpdate(BaseModel):
    push_enabled: Optional[bool] = None
    tg_notify_enabled: Optional[bool] = None
    quiet_hour_start: Optional[str] = None
    quiet_hour_end: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None

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
    # Таблица мастеров
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
    
    # Таблица услуг
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
    
    # Таблица записей
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
            deposit_amount INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    
    # Таблица отзывов
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
    
    # Таблица листа ожидания
    await db.execute("""
        CREATE TABLE IF NOT EXISTS waitlist (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            service VARCHAR(100),
            created_at TIMESTAMP DEFAULT NOW(),
            notified BOOLEAN DEFAULT FALSE
        )
    """)
    
    # Таблица портфолио "до/после"
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
    
    # Таблица избранного
    await db.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            id SERIAL PRIMARY KEY,
            client_telegram_id VARCHAR(50) NOT NULL,
            master_id INTEGER REFERENCES masters(id),
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(client_telegram_id, master_id)
        )
    """)
    
    # Таблица быстрых ответов
    await db.execute("""
        CREATE TABLE IF NOT EXISTS quick_replies (
            id SERIAL PRIMARY KEY,
            master_id INTEGER REFERENCES masters(id) ON DELETE CASCADE,
            title VARCHAR(100) NOT NULL,
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    
    # Таблица выходных дней
    await db.execute("""
        CREATE TABLE IF NOT EXISTS master_days_off (
            id SERIAL PRIMARY KEY,
            master_id INTEGER REFERENCES masters(id) ON DELETE CASCADE,
            date DATE NOT NULL,
            UNIQUE(master_id, date)
        )
    """)
    
    # Таблица чата
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
    
    # Таблица настроек клиента
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
    
    # Таблица промокодов
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
    
    # Таблица уведомлений
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
    
    # Восстанавливаем мастеров
    await restore_masters()

async def restore_masters():
    """Восстанавливает мастеров, если таблица пустая"""
    try:
        count = await db.fetchval("SELECT COUNT(*) FROM masters")
        if count > 0:
            print(f"✅ Мастера уже есть в БД: {count} шт.")
            return
    except Exception as e:
        print(f"⚠️ Ошибка проверки мастеров: {e}")
        return
    
    print("🔄 Восстанавливаем мастеров...")
    
    try:
        # Мастер 1: Алина
        await db.execute("""
            INSERT INTO masters (telegram_id, name, lat, lon, description, work_start, work_end, icon, rating, reviews_count)
            VALUES (777000, 'Алина Козлова', 47.222078, 39.720358, 
                   '🌸 Мастер маникюра с 5-летним опытом. Делаю классику, гель-лак, дизайн.',
                   '09:00', '21:00', '💅', 4.9, 128)
        """)
        
        # Мастер 2: Елена
        await db.execute("""
            INSERT INTO masters (telegram_id, name, lat, lon, description, work_start, work_end, icon, rating, reviews_count)
            VALUES (777001, 'Елена Соколова', 47.225000, 39.725000,
                   '👑 Топ-мастер по бровам и ресницам. Стаж 7 лет.',
                   '10:00', '20:00', '✏️', 4.95, 256)
        """)
        
        # Мастер 3: Дмитрий
        await db.execute("""
            INSERT INTO masters (telegram_id, name, lat, lon, description, work_start, work_end, icon, rating, reviews_count)
            VALUES (777002, 'Дмитрий Волков', 47.218000, 39.718000,
                   '💈 Мужской мастер. Стрижки, бороды, укладки.',
                   '11:00', '22:00', '✂️', 4.85, 89)
        """)
        
        # Мастер 4: Анна
        await db.execute("""
            INSERT INTO masters (telegram_id, name, lat, lon, description, work_start, work_end, icon, rating, reviews_count)
            VALUES (777003, 'Анна Морозова', 47.230000, 39.730000,
                   '💆‍♀️ Косметолог. Чистки лица, пилинги, массажи.',
                   '09:30', '19:30', '🧴', 4.92, 312)
        """)
        
        # Услуги Алины (master_id=1)
        await db.execute("""
            INSERT INTO services (master_id, name, price, duration_min) VALUES
            (1, 'Маникюр классический', 1200, 60),
            (1, 'Маникюр с покрытием гель-лак', 2000, 90),
            (1, 'Педикюр', 2500, 90),
            (1, 'SPA-уход за руками', 1500, 60)
        """)
        
        # Услуги Елены (master_id=2)
        await db.execute("""
            INSERT INTO services (master_id, name, price, duration_min) VALUES
            (2, 'Коррекция бровей', 800, 40),
            (2, 'Окрашивание бровей', 1000, 50),
            (2, 'Ламинирование бровей', 2000, 70),
            (2, 'Ламинирование ресниц', 2500, 90),
            (2, 'Наращивание ресниц 2D', 3000, 120)
        """)
        
        # Услуги Дмитрия (master_id=3)
        await db.execute("""
            INSERT INTO services (master_id, name, price, duration_min) VALUES
            (3, 'Мужская стрижка', 1200, 45),
            (3, 'Стрижка + борода', 1800, 60),
            (3, 'Моделирование бороды', 800, 30),
            (3, 'Укладка', 600, 25)
        """)
        
        # Услуги Анны (master_id=4)
        await db.execute("""
            INSERT INTO services (master_id, name, price, duration_min) VALUES
            (4, 'Чистка лица ультразвуковая', 2500, 60),
            (4, 'Чистка лица комбинированная', 3500, 90),
            (4, 'Пилинг лица', 2000, 45),
            (4, 'Массаж лица', 1800, 50)
        """)
        
        # Добавляем портфолио "до/после"
        await db.execute("""
            INSERT INTO master_before_after (master_id, before_photo, after_photo, description) VALUES
            (1, 'https://images.unsplash.com/photo-1604654894610-df63bc536371?w=400', 'https://images.unsplash.com/photo-1604654894610-df63bc536371?w=400', 'Классический маникюр'),
            (2, 'https://images.unsplash.com/photo-1512290923902-8a9f81dc236c?w=400', 'https://images.unsplash.com/photo-1512290923902-8a9f81dc236c?w=400', 'Коррекция бровей')
        """)
        
        # Добавляем промокоды
        await db.execute("""
            INSERT INTO promocodes (code, discount_percent, expires_at, max_uses) VALUES
            ('WELCOME10', 10, NOW() + INTERVAL '30 days', 100),
            ('BEAUTY20', 20, NOW() + INTERVAL '15 days', 50)
        """)
        
        print(f"✅ Восстановлено мастеров: {await db.fetchval('SELECT COUNT(*) FROM masters')}")
        print(f"✅ Восстановлено услуг: {await db.fetchval('SELECT COUNT(*) FROM services')}")
    except Exception as e:
        print(f"❌ Ошибка восстановления мастеров: {e}")

# ========== МАСТЕРА ==========
@app.get("/masters")
async def get_masters():
    rows = await db.fetch("SELECT id, name, lat, lon, rating, description, icon, reviews_count FROM masters")
    result = []
    for r in rows:
        services = await db.fetch("SELECT id, name, price, duration_min FROM services WHERE master_id = $1", r["id"])
        result.append({
            "id": r["id"],
            "name": r["name"],
            "lat": r["lat"],
            "lon": r["lon"],
            "rating": r["rating"],
            "description": r["description"],
            "icon": r["icon"],
            "reviews_count": r["reviews_count"],
            "services": [dict(s) for s in services]
        })
    return result

@app.get("/masters/{master_id}")
async def get_master(master_id: int):
    row = await db.fetchrow("SELECT * FROM masters WHERE id = $1", master_id)
    if not row:
        raise HTTPException(404, "Master not found")
    services = await db.fetch("SELECT id, name, price, duration_min FROM services WHERE master_id = $1", master_id)
    return dict(row, services=[dict(s) for s in services])

@app.get("/masters/by_telegram/{telegram_id}")
async def get_master_by_telegram(telegram_id: int):
    row = await db.fetchrow("SELECT id FROM masters WHERE telegram_id = $1", telegram_id)
    if not row:
        raise HTTPException(404, "Master not found")
    return {"id": row["id"]}

@app.get("/masters/{master_id}/slots")
async def get_slots(master_id: int, date: str, service_id: int):
    service = await db.fetchrow("SELECT duration_min FROM services WHERE id = $1", service_id)
    if not service:
        raise HTTPException(404, "Service not found")
    duration = service["duration_min"]
    
    booked = await db.fetch("""
        SELECT b.time, s.duration_min 
        FROM bookings b
        JOIN services s ON b.service_id = s.id
        WHERE b.master_id = $1 AND b.date = $2 AND b.status NOT IN ('cancelled')
    """, master_id, date)
    
    booked_slots = [b["time"] for b in booked]
    booked_durations = {b["time"]: b["duration_min"] for b in booked}
    
    return {
        "booked_slots": booked_slots,
        "booked_durations": booked_durations,
        "service_duration": duration
    }

# ========== ЗАПИСИ ==========
@app.post("/bookings")
async def create_booking(booking: BookingCreate):
    service = await db.fetchrow("SELECT duration_min, price FROM services WHERE id = $1", booking.service_id)
    if not service:
        raise HTTPException(400, "Service not found")
    
    sh, sm = map(int, booking.time.split(':'))
    new_start = sh * 60 + sm
    new_end = new_start + service["duration_min"]
    
    existing = await db.fetch("""
        SELECT b.time, s.duration_min
        FROM bookings b
        JOIN services s ON b.service_id = s.id
        WHERE b.master_id = $1 AND b.date = $2 AND b.status NOT IN ('cancelled')
    """, booking.master_id, booking.date)
    
    for ex in existing:
        eh, em = map(int, ex["time"].split(':'))
        ex_start = eh * 60 + em
        ex_end = ex_start + ex["duration_min"]
        if not (new_end <= ex_start or new_start >= ex_end):
            raise HTTPException(400, "Time slot overlaps with existing booking")
    
    booking_id = await db.execute("""
        INSERT INTO bookings (master_id, service_id, client_name, client_telegram_id, client_phone, date, time, price, status, created_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'pending', NOW())
        RETURNING id
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
        ORDER BY b.date ASC, b.time ASC
        LIMIT 1
    """, telegram_id)
    
    recent = await db.fetch("""
        SELECT b.id, b.date, b.time, b.price, m.name as master_name, s.name as service_name
        FROM bookings b
        JOIN masters m ON b.master_id = m.id
        JOIN services s ON b.service_id = s.id
        WHERE b.client_telegram_id = $1 AND b.status = 'confirmed'
        ORDER BY b.date DESC, b.time DESC
        LIMIT 5
    """, telegram_id)
    
    total_visits = stats["total_visits"] if stats else 0
    if total_visits >= 50:
        level, discount, badge = "Платина", 20, "💎"
    elif total_visits >= 20:
        level, discount, badge = "Золото", 15, "🥇"
    elif total_visits >= 10:
        level, discount, badge = "Серебро", 10, "🥈"
    elif total_visits >= 5:
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
        "visits_to_next_level": max(0, (5 if total_visits < 5 else 10 if total_visits < 10 else 20 if total_visits < 20 else 50 if total_visits < 50 else 0) - total_visits)
    }

# ========== УМНЫЕ ФУНКЦИИ ==========
@app.post("/api/reminder")
async def send_reminder(data: ReminderRequest):
    print(f"[REMINDER] To {data.user_id} (за {data.hours_before}ч): {data.message}")
    return {"status": "ok"}

@app.post("/api/waitlist/add")
async def add_to_waitlist(data: WaitlistRequest):
    await db.execute("""
        INSERT INTO waitlist (user_id, service, created_at)
        VALUES ($1, $2, NOW())
        ON CONFLICT (user_id, service) DO NOTHING
    """, data.user_id, data.service)
    return {"status": "ok"}

@app.post("/api/review")
async def add_review(data: ReviewDirectCreate):
    await db.execute("""
        INSERT INTO reviews (user_id, master_id, rating, comment, created_at)
        VALUES ($1, $2, $3, $4, NOW())
    """, data.user_id, data.master_id, data.rating, data.comment)
    
    avg = await db.fetchval("SELECT AVG(rating) FROM reviews WHERE master_id = $1", data.master_id)
    if avg:
        await db.execute("UPDATE masters SET rating = $1 WHERE id = $2", round(avg, 1), data.master_id)
    
    return {"status": "ok"}

@app.post("/api/repeat/trigger")
async def trigger_repeat(data: dict):
    user_id = data.get("user_id")
    print(f"[REPEAT] To {user_id}: Пора повторить процедуру! 💅")
    return {"status": "ok"}

# ========== ПОРТФОЛИО ДО/ПОСЛЕ ==========
@app.get("/masters/{master_id}/before-after")
async def get_before_after(master_id: int):
    rows = await db.fetch("SELECT id, before_photo, after_photo, description FROM master_before_after WHERE master_id = $1 ORDER BY created_at DESC", master_id)
    return [dict(r) for r in rows]

@app.post("/master/{telegram_id}/before-after")
async def add_before_after(telegram_id: int, data: BeforeAfterCreate):
    master = await db.fetchrow("SELECT id FROM masters WHERE telegram_id = $1", telegram_id)
    if not master:
        raise HTTPException(404, "Master not found")
    await db.execute("""
        INSERT INTO master_before_after (master_id, before_photo, after_photo, description, created_at)
        VALUES ($1, $2, $3, $4, NOW())
    """, master["id"], data.before_photo, data.after_photo, data.description)
    return {"status": "ok"}

@app.delete("/master/{telegram_id}/before-after/{item_id}")
async def delete_before_after(telegram_id: int, item_id: int):
    await db.execute("""
        DELETE FROM master_before_after
        WHERE id = $1 AND master_id IN (SELECT id FROM masters WHERE telegram_id = $2)
    """, item_id, telegram_id)
    return {"status": "ok"}

# ========== УСЛУГИ МАСТЕРА ==========
@app.get("/master/{telegram_id}/services")
async def get_master_services(telegram_id: int):
    master = await db.fetchrow("SELECT id FROM masters WHERE telegram_id = $1", telegram_id)
    if not master:
        return []
    rows = await db.fetch("SELECT id, name, price, duration_min FROM services WHERE master_id = $1 ORDER BY id", master["id"])
    return [dict(r) for r in rows]

@app.post("/master/{telegram_id}/services")
async def add_master_service(telegram_id: int, service: ServiceCreate):
    master = await db.fetchrow("SELECT id FROM masters WHERE telegram_id = $1", telegram_id)
    if not master:
        raise HTTPException(404, "Master not found")
    await db.execute("""
        INSERT INTO services (master_id, name, price, duration_min)
        VALUES ($1, $2, $3, $4)
    """, master["id"], service.name, service.price, service.duration_min)
    return {"status": "ok"}

@app.delete("/master/{telegram_id}/services/{service_id}")
async def delete_master_service(telegram_id: int, service_id: int):
    await db.execute("""
        DELETE FROM services
        WHERE id = $1 AND master_id IN (SELECT id FROM masters WHERE telegram_id = $2)
    """, service_id, telegram_id)
    return {"status": "ok"}

# ========== СТАТИСТИКА МАСТЕРА ==========
@app.get("/master/{telegram_id}/stats")
async def get_master_stats(telegram_id: int):
    master = await db.fetchrow("SELECT id FROM masters WHERE telegram_id = $1", telegram_id)
    if not master:
        return {"completed": 0, "pending": 0, "revenue": 0}
    
    completed = await db.fetchval("SELECT COUNT(*) FROM bookings WHERE master_id = $1 AND status = 'confirmed'", master["id"])
    pending = await db.fetchval("SELECT COUNT(*) FROM bookings WHERE master_id = $1 AND status = 'pending'", master["id"])
    revenue = await db.fetchval("SELECT COALESCE(SUM(price), 0) FROM bookings WHERE master_id = $1 AND status = 'confirmed'", master["id"])
    
    return {"completed": completed or 0, "pending": pending or 0, "revenue": revenue or 0}

@app.patch("/master/{telegram_id}/work-hours")
async def update_work_hours(telegram_id: int, data: dict):
    work_start = data.get("work_start", "09:00")
    work_end = data.get("work_end", "21:00")
    await db.execute("""
        UPDATE masters SET work_start = $1, work_end = $2
        WHERE telegram_id = $3
    """, work_start, work_end, telegram_id)
    return {"status": "ok"}

@app.patch("/master/{telegram_id}/profile")
async def update_master_profile(telegram_id: int, data: dict):
    description = data.get("description", "")
    await db.execute("""
        UPDATE masters SET description = $1
        WHERE telegram_id = $2
    """, description, telegram_id)
    return {"status": "ok"}

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
        ON CONFLICT (client_telegram_id, master_id) DO NOTHING
    """, client_telegram_id, master_id)
    return {"status": "ok"}

@app.delete("/favorites/{master_id}")
async def remove_favorite(master_id: int, client_telegram_id: str):
    await db.execute("""
        DELETE FROM favorites
        WHERE client_telegram_id = $1 AND master_id = $2
    """, client_telegram_id, master_id)
    return {"status": "ok"}

# ========== БЫСТРЫЕ ОТВЕТЫ ==========
@app.get("/master/{telegram_id}/quick-replies")
async def get_quick_replies(telegram_id: int):
    master = await db.fetchrow("SELECT id FROM masters WHERE telegram_id = $1", telegram_id)
    if not master:
        return []
    rows = await db.fetch("SELECT id, title, message FROM quick_replies WHERE master_id = $1 ORDER BY id", master["id"])
    return [dict(r) for r in rows]

@app.post("/master/{telegram_id}/quick-replies")
async def add_quick_reply(telegram_id: int, reply: QuickReplyCreate):
    master = await db.fetchrow("SELECT id FROM masters WHERE telegram_id = $1", telegram_id)
    if not master:
        raise HTTPException(404, "Master not found")
    await db.execute("""
        INSERT INTO quick_replies (master_id, title, message)
        VALUES ($1, $2, $3)
    """, master["id"], reply.title, reply.message)
    return {"status": "ok"}

@app.delete("/master/{telegram_id}/quick-replies/{reply_id}")
async def delete_quick_reply(telegram_id: int, reply_id: int):
    await db.execute("""
        DELETE FROM quick_replies
        WHERE id = $1 AND master_id IN (SELECT id FROM masters WHERE telegram_id = $2)
    """, reply_id, telegram_id)
    return {"status": "ok"}

# ========== ЧАТ ==========
@app.get("/chat/messages/{booking_id}")
async def get_chat_messages(booking_id: int, user_id: str):
    rows = await db.fetch("""
        SELECT id, from_id, to_id, message, created_at
        FROM chat_messages
        WHERE booking_id = $1
        ORDER BY created_at ASC
    """, booking_id)
    return [dict(r) for r in rows]

@app.post("/chat/send")
async def send_chat_message(msg: ChatMessageSend):
    await db.execute("""
        INSERT INTO chat_messages (booking_id, from_id, to_id, message, created_at)
        VALUES ($1, $2, $3, $4, NOW())
    """, msg.booking_id, msg.from_id, msg.to_id, msg.message)
    return {"status": "ok"}

# ========== ПРОМОКОДЫ ==========
@app.get("/promocodes/active")
async def get_active_promocodes():
    rows = await db.fetch("""
        SELECT code, discount_percent, expires_at
        FROM promocodes
        WHERE expires_at > NOW() AND active = true
        LIMIT 10
    """)
    return [dict(r) for r in rows]

@app.post("/apply-promo")
async def apply_promo(data: dict):
    promo_code = data.get("promo_code", "").upper()
    user_id = data.get("user_id")
    
    promo = await db.fetchrow("""
        SELECT discount_percent FROM promocodes
        WHERE code = $1 AND expires_at > NOW() AND active = true
    """, promo_code)
    
    if not promo:
        raise HTTPException(400, "Invalid or expired promo code")
    
    return {"status": "ok", "discount_percent": promo["discount_percent"]}

# ========== НАСТРОЙКИ КЛИЕНТА ==========
@app.patch("/client/settings/{telegram_id}")
async def update_client_settings(telegram_id: str, settings: ClientSettingsUpdate):
    await db.execute("""
        INSERT INTO client_settings (telegram_id, push_enabled, tg_notify_enabled, quiet_hour_start, quiet_hour_end, email, phone)
        VALUES ($1, COALESCE($2, TRUE), COALESCE($3, TRUE), COALESCE($4, '22:00'), COALESCE($5, '09:00'), $6, $7)
        ON CONFLICT (telegram_id) DO UPDATE SET
            push_enabled = EXCLUDED.push_enabled,
            tg_notify_enabled = EXCLUDED.tg_notify_enabled,
            quiet_hour_start = EXCLUDED.quiet_hour_start,
            quiet_hour_end = EXCLUDED.quiet_hour_end,
            email = EXCLUDED.email,
            phone = EXCLUDED.phone
    """, telegram_id, settings.push_enabled, settings.tg_notify_enabled, 
        settings.quiet_hour_start, settings.quiet_hour_end, settings.email, settings.phone)
    return {"status": "ok"}

# ========== ЗДОРОВЬЕ ==========
@app.get("/health")
async def health_check():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
