from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import sqlite3
import os
import httpx
import json
import secrets
from datetime import datetime, timedelta
from fastapi.responses import JSONResponse
from fastapi import Request

app = FastAPI(title="Beauty Bot API")

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
MASTER_BOT_TOKEN = os.getenv("MASTER_BOT_TOKEN", "8236516081:AAFjIjQBiAMs95XpURSCZZhuuYr5yDrcmlw")
DEFAULT_WORK_START = "09:00"
DEFAULT_WORK_END = "20:00"
SLOT_INTERVAL = 30


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
            photos TEXT
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
            status TEXT DEFAULT 'pending',
            payment_status TEXT DEFAULT 'pending',
            deposit_amount REAL DEFAULT 0,
            reminder_sent INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
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

    # Добавляем колонки для существующих БД
    for col in ["telegram_id TEXT", "work_start TEXT DEFAULT '09:00'", "work_end TEXT DEFAULT '20:00'", "registered_at TEXT DEFAULT CURRENT_TIMESTAMP"]:
        try:
            c.execute(f"ALTER TABLE masters ADD COLUMN {col}")
        except:
            pass

    try:
        c.execute("ALTER TABLE masters ADD COLUMN bot_token TEXT")
        print("✅ Колонка bot_token добавлена")
    except:
        print("⚠️ Колонка bot_token уже есть")

    try:
        c.execute("ALTER TABLE masters ADD COLUMN photos TEXT")
        print("✅ Колонка photos добавлена")
    except:
        print("⚠️ Колонка photos уже есть")

    try:
        c.execute("ALTER TABLE bookings ADD COLUMN payment_status TEXT DEFAULT 'pending'")
        c.execute("ALTER TABLE bookings ADD COLUMN deposit_amount REAL DEFAULT 0")
        c.execute("ALTER TABLE bookings ADD COLUMN reminder_sent INTEGER DEFAULT 0")
        print("✅ Колонки bookings обновлены")
    except:
        print("⚠️ Колонки bookings уже есть")

    c.execute("SELECT COUNT(*) FROM masters")
    if c.fetchone()[0] == 0:
        masters_data = [
            ("Алина Козлова", None, "Мастер маникюра с 5-летним опытом", "ул. Ленина, 12", 55.751244, 37.618423, "+79001234567", "@alina_nails"),
            ("Мария Иванова", None, "Профессиональный визажист и мастер бровей", "пр. Мира, 45", 55.763244, 37.628423, "+79009876543", "@maria_beauty"),
            ("Екатерина Смирнова", None, "Специалист по уходу за ресницами", "ул. Садовая, 8", 55.745244, 37.608423, "+79005551234", "@kate_lashes"),
        ]
        c.executemany("INSERT INTO masters (name, photo_url, description, address, lat, lon, phone, instagram) VALUES (?,?,?,?,?,?,?,?)", masters_data)
        conn.commit()

        c.execute("SELECT id FROM masters")
        ids = [row[0] for row in c.fetchall()]
        services = [
            (ids[0], "Маникюр классический", 1200, 60),
            (ids[0], "Маникюр с покрытием гель-лак", 2000, 90),
            (ids[0], "Педикюр", 2500, 120),
            (ids[1], "Макияж дневной", 2500, 60),
            (ids[1], "Коррекция бровей", 800, 30),
            (ids[1], "Макияж вечерний", 4000, 90),
            (ids[2], "Наращивание ресниц", 3000, 120),
            (ids[2], "Ламинирование ресниц", 2500, 90),
        ]
        c.executemany("INSERT INTO services (master_id, name, price, duration_min) VALUES (?,?,?,?)", services)
        conn.commit()

    conn.close()

init_db()


# ВАЖНО: Функция get_db теперь НЕ асинхронная и создаёт новое соединение
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


async def send_message_to_client(telegram_id: str, message: str):
    if not telegram_id or MASTER_BOT_TOKEN == "YOUR_MASTER_BOT_TOKEN":
        return
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{MASTER_BOT_TOKEN}/sendMessage",
                json={"chat_id": telegram_id, "text": message, "parse_mode": "Markdown"}
            )
    except Exception as e:
        print(f"Send message error: {e}")


async def notify_master_with_buttons_v2(master_bot_token: str, master_telegram_id: str, message: str, booking_id: int):
    if not master_bot_token or not master_telegram_id:
        print(f"❌ У мастера нет bot_token или telegram_id, уведомление не отправлено")
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


# --- Schemas ---
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

class BookingIn(BaseModel):
    master_id: int
    service_id: int
    client_name: str
    client_telegram_id: str
    client_phone: Optional[str]
    date: str
    time: str

class BookingOut(BaseModel):
    id: int
    master_id: int
    service_id: int
    client_name: str
    date: str
    time: str
    status: str


# ========== ОСНОВНЫЕ ЭНДПОИНТЫ ==========

@app.get("/masters", response_model=List[MasterOut])
def get_masters():
    conn = get_db()
    try:
        masters = conn.execute("SELECT * FROM masters").fetchall()
        result = []
        for m in masters:
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
            result.append(master_dict)
        return result
    finally:
        conn.close()


@app.get("/masters/{master_id}", response_model=MasterOut)
def get_master(master_id: int):
    conn = get_db()
    try:
        m = conn.execute("SELECT * FROM masters WHERE id = ?", (master_id,)).fetchone()
        if not m:
            raise HTTPException(status_code=404, detail="Master not found")
        services = conn.execute("SELECT * FROM services WHERE master_id = ?", (master_id,)).fetchall()
        master_dict = dict(m)
        if master_dict.get("photos"):
            try:
                master_dict["photos"] = json.loads(master_dict["photos"])
            except:
                master_dict["photos"] = []
        else:
            master_dict["photos"] = []
        master_dict["services"] = [dict(s) for s in services]
        return master_dict
    finally:
        conn.close()


@app.get("/masters/{master_id}/slots")
def get_free_slots(master_id: int, date: str):
    conn = get_db()
    try:
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

        free_slots = [
            s for s in all_slots
            if s not in booked_times and not (date == today and s <= now_time)
        ]

        return {"date": date, "slots": free_slots, "day_off": False}
    finally:
        conn.close()


# ========== ЭНДПОИНТЫ ДЛЯ БРОНИРОВАНИЙ ==========

@app.post("/bookings", response_model=BookingOut)
async def create_booking(data: BookingIn):
    conn = get_db()
    try:
        master = conn.execute("SELECT * FROM masters WHERE id = ?", (data.master_id,)).fetchone()
        if not master:
            raise HTTPException(status_code=404, detail="Master not found")

        service = conn.execute("SELECT * FROM services WHERE id=? AND master_id=?", (data.service_id, data.master_id)).fetchone()
        if not service:
            raise HTTPException(status_code=404, detail="Service not found")

        day_off = conn.execute("SELECT id FROM days_off WHERE master_id=? AND date=?", (data.master_id, data.date)).fetchone()
        if day_off:
            raise HTTPException(status_code=409, detail="Master is off this day")

        existing = conn.execute(
            "SELECT id FROM bookings WHERE master_id=? AND date=? AND time=? AND status!='cancelled'",
            (data.master_id, data.date, data.time)
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="This time slot is already booked")

        cursor = conn.execute(
            "INSERT INTO bookings (master_id, service_id, client_name, client_telegram_id, client_phone, date, time) VALUES (?,?,?,?,?,?,?)",
            (data.master_id, data.service_id, data.client_name, data.client_telegram_id, data.client_phone, data.date, data.time)
        )
        conn.commit()
        booking_id = cursor.lastrowid

        master_tg = master["telegram_id"]
        master_bot_token = master["bot_token"]
        
        phone_line = f"\n📞 Телефон: {data.client_phone}" if data.client_phone else ""
        message = (
            f"🌸 *Новая запись!*\n\n"
            f"👩 Клиент: {data.client_name}{phone_line}\n"
            f"💅 Услуга: {service['name']}\n"
            f"💰 Цена: {service['price']} ₽\n"
            f"📅 Дата: {data.date}\n"
            f"🕐 Время: {data.time}"
        )
        
        await notify_master_with_buttons_v2(master_bot_token, master_tg, message, booking_id)

        booking = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        return dict(booking)
    finally:
        conn.close()


@app.patch("/bookings/{booking_id}/status")
def update_booking_status(booking_id: int, status: str):
    conn = get_db()
    try:
        booking = conn.execute(
            """SELECT b.*, m.telegram_id, s.name as service_name
               FROM bookings b JOIN masters m ON b.master_id=m.id JOIN services s ON b.service_id=s.id
               WHERE b.id=?""", (booking_id,)
        ).fetchone()
        if not booking:
            raise HTTPException(status_code=404, detail="Booking not found")
        
        conn.execute("UPDATE bookings SET status=? WHERE id=?", (status, booking_id))
        conn.commit()
        
        return {"status": "ok", "booking_id": booking_id, "new_status": status}
    except Exception as e:
        print(f"Error in update_booking_status: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.get("/bookings/client/{telegram_id}")
def get_client_bookings(telegram_id: str):
    conn = get_db()
    try:
        bookings = conn.execute(
            """SELECT b.*, m.name as master_name, s.name as service_name, s.price
               FROM bookings b JOIN masters m ON b.master_id=m.id JOIN services s ON b.service_id=s.id
               WHERE b.client_telegram_id=? ORDER BY b.date DESC, b.time DESC""",
            (telegram_id,)
        ).fetchall()
        return [dict(b) for b in bookings]
    finally:
        conn.close()


@app.get("/bookings/master/{master_id}")
def get_master_bookings(master_id: int):
    conn = get_db()
    try:
        bookings = conn.execute(
            """SELECT b.*, s.name as service_name, s.price FROM bookings b
               JOIN services s ON b.service_id=s.id
               WHERE b.master_id=? AND b.status!='cancelled' ORDER BY b.date, b.time""",
            (master_id,)
        ).fetchall()
        return [dict(b) for b in bookings]
    finally:
        conn.close()


@app.delete("/bookings/{booking_id}")
def delete_booking(booking_id: int):
    """Альтернативный эндпоинт для отмены записи через DELETE"""
    conn = get_db()
    try:
        booking = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        if not booking:
            raise HTTPException(status_code=404, detail="Booking not found")
        
        conn.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (booking_id,))
        conn.commit()
        
        return {"status": "ok", "booking_id": booking_id, "message": "Booking cancelled"}
    except Exception as e:
        print(f"Error in delete_booking: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.post("/bookings/{booking_id}/cancel")
def cancel_booking_post(booking_id: int):
    """Альтернативный эндпоинт для отмены записи через POST"""
    conn = get_db()
    try:
        booking = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        if not booking:
            raise HTTPException(status_code=404, detail="Booking not found")
        
        conn.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (booking_id,))
        conn.commit()
        
        return {"status": "ok", "booking_id": booking_id, "message": "Booking cancelled"}
    except Exception as e:
        print(f"Error in cancel_booking_post: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ========== ОСТАЛЬНЫЕ ЭНДПОИНТЫ ==========

@app.get("/masters/{master_id}/schedule")
def get_schedule(master_id: int):
    conn = get_db()
    try:
        master = conn.execute("SELECT * FROM masters WHERE id = ?", (master_id,)).fetchone()
        if not master:
            raise HTTPException(status_code=404, detail="Master not found")

        result = []
        today = datetime.now()
        for i in range(7):
            day = (today + timedelta(days=i)).strftime("%Y-%m-%d")
            day_off = conn.execute("SELECT id FROM days_off WHERE master_id=? AND date=?", (master_id, day)).fetchone()
            bookings = conn.execute(
                """SELECT b.time, b.status, b.client_name, b.client_phone, s.name as service_name
                   FROM bookings b JOIN services s ON b.service_id=s.id
                   WHERE b.master_id=? AND b.date=? AND b.status!='cancelled' ORDER BY b.time""",
                (master_id, day)
            ).fetchall()
            result.append({"date": day, "day_off": bool(day_off), "bookings": [dict(b) for b in bookings]})
        return result
    finally:
        conn.close()


@app.post("/masters/{master_id}/days_off")
def add_day_off(master_id: int, date: str):
    conn = get_db()
    try:
        conn.execute("INSERT OR IGNORE INTO days_off (master_id, date) VALUES (?,?)", (master_id, date))
        conn.commit()
        return {"status": "ok", "date": date}
    finally:
        conn.close()


@app.delete("/masters/{master_id}/days_off/{date}")
def remove_day_off(master_id: int, date: str):
    conn = get_db()
    try:
        conn.execute("DELETE FROM days_off WHERE master_id=? AND date=?", (master_id, date))
        conn.commit()
        return {"status": "ok", "date": date}
    finally:
        conn.close()


# ========== ЭНДПОИНТЫ ДЛЯ ФОТОГРАФИЙ ==========

@app.post("/masters/{master_id}/photos")
def add_master_photo(master_id: int, data: dict):
    conn = get_db()
    try:
        master = conn.execute("SELECT id FROM masters WHERE id = ?", (master_id,)).fetchone()
        if not master:
            raise HTTPException(status_code=404, detail="Master not found")
        
        current = conn.execute("SELECT photos FROM masters WHERE id = ?", (master_id,)).fetchone()
        photos = json.loads(current["photos"]) if current["photos"] else []
        photos.append(data["photo"])
        
        conn.execute("UPDATE masters SET photos = ? WHERE id = ?", (json.dumps(photos), master_id))
        conn.commit()
        return {"status": "ok", "photos": photos}
    finally:
        conn.close()


@app.delete("/masters/{master_id}/photos")
def delete_master_photo(master_id: int, index: int):
    conn = get_db()
    try:
        master = conn.execute("SELECT id FROM masters WHERE id = ?", (master_id,)).fetchone()
        if not master:
            raise HTTPException(status_code=404, detail="Master not found")
        
        current = conn.execute("SELECT photos FROM masters WHERE id = ?", (master_id,)).fetchone()
        photos = json.loads(current["photos"]) if current["photos"] else []
        
        if index < 0 or index >= len(photos):
            raise HTTPException(status_code=400, detail="Invalid photo index")
        
        photos.pop(index)
        conn.execute("UPDATE masters SET photos = ? WHERE id = ?", (json.dumps(photos), master_id))
        conn.commit()
        return {"status": "ok", "photos": photos}
    finally:
        conn.close()


@app.get("/masters/{master_id}/photos")
def get_master_photos(master_id: int):
    conn = get_db()
    try:
        master = conn.execute("SELECT id FROM masters WHERE id = ?", (master_id,)).fetchone()
        if not master:
            raise HTTPException(status_code=404, detail="Master not found")
        
        current = conn.execute("SELECT photos FROM masters WHERE id = ?", (master_id,)).fetchone()
        photos = json.loads(current["photos"]) if current["photos"] else []
        return {"photos": photos}
    finally:
        conn.close()


@app.patch("/masters/{master_id}/avatar")
def set_master_avatar(master_id: int, photo_url: str):
    conn = get_db()
    try:
        master = conn.execute("SELECT id FROM masters WHERE id = ?", (master_id,)).fetchone()
        if not master:
            raise HTTPException(status_code=404, detail="Master not found")
        
        conn.execute("UPDATE masters SET photo_url = ? WHERE id = ?", (photo_url, master_id))
        conn.commit()
        return {"status": "ok", "message": "Avatar saved"}
    finally:
        conn.close()


# ========== ЭНДПОИНТЫ ДЛЯ МАСТЕРОВ И ТЕЛЕГРАМ ==========

@app.get("/masters/by_telegram/{telegram_id}")
def get_master_by_telegram(telegram_id: str):
    conn = get_db()
    try:
        master = conn.execute("SELECT * FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
        if not master:
            raise HTTPException(status_code=404, detail="Master not found")
        return dict(master)
    finally:
        conn.close()


@app.patch("/masters/{master_id}/telegram")
def set_master_telegram(master_id: int, telegram_id: str):
    conn = get_db()
    try:
        master = conn.execute("SELECT id FROM masters WHERE id = ?", (master_id,)).fetchone()
        if not master:
            raise HTTPException(status_code=404, detail="Master not found")
        
        conn.execute("UPDATE masters SET telegram_id = ? WHERE id = ?", (telegram_id, master_id))
        conn.commit()
        return {"status": "ok"}
    finally:
        conn.close()


@app.patch("/masters/{master_id}/bot-token")
def set_master_bot_token(master_id: int, bot_token: str):
    conn = get_db()
    try:
        master = conn.execute("SELECT id FROM masters WHERE id = ?", (master_id,)).fetchone()
        if not master:
            raise HTTPException(status_code=404, detail="Master not found")
        
        conn.execute("UPDATE masters SET bot_token = ? WHERE id = ?", (bot_token, master_id))
        conn.commit()
        return {"status": "ok", "message": "Bot token saved"}
    finally:
        conn.close()


@app.post("/masters")
def add_master(master: dict):
    conn = get_db()
    try:
        if not master.get("name") or not master.get("address"):
            raise HTTPException(status_code=400, detail="Missing name or address")
        
        conn.execute(
            """INSERT INTO masters (name, address, lat, lon, phone, instagram, description, registered_at) 
               VALUES (?,?,?,?,?,?,?, CURRENT_TIMESTAMP)""",
            (master["name"], master["address"], 
             master.get("lat", 55.751244), master.get("lon", 37.618423),
             master.get("phone"), master.get("instagram"), master.get("description"))
        )
        conn.commit()
        return {"status": "ok", "message": "Master added"}
    finally:
        conn.close()


@app.delete("/masters/{master_id}")
def delete_master(master_id: int):
    conn = get_db()
    try:
        master = conn.execute("SELECT id FROM masters WHERE id = ?", (master_id,)).fetchone()
        if not master:
            raise HTTPException(status_code=404, detail="Master not found")
        
        conn.execute("DELETE FROM masters WHERE id = ?", (master_id,))
        conn.commit()
        return {"status": "ok", "message": f"Master {master_id} deleted"}
    finally:
        conn.close()


# ========== ЭНДПОИНТЫ ДЛЯ ЧАТА ==========

@app.get("/chat/{token}")
def get_chat_by_token(token: str):
    conn = get_db()
    try:
        chat = conn.execute("SELECT * FROM chats WHERE token = ?", (token,)).fetchone()
        if not chat:
            raise HTTPException(404, "Chat not found")
        
        booking = conn.execute("SELECT * FROM bookings WHERE id = ?", (chat["booking_id"],)).fetchone()
        
        return {
            "booking_id": chat["booking_id"],
            "master_id": chat["master_id"],
            "client_telegram_id": chat["client_telegram_id"],
            "master_telegram_id": chat["master_telegram_id"],
            "client_name": booking["client_name"]
        }
    finally:
        conn.close()


# ========== ЭНДПОИНТЫ ПЛАТЕЖЕЙ ==========

@app.post("/create-commission-payment")
async def create_commission_payment(data: dict):
    conn = get_db()
    try:
        booking_id = data["booking_id"]
        
        booking = conn.execute("""
            SELECT b.*, s.price, m.registered_at, m.name as master_name, m.bot_token, m.telegram_id as master_telegram_id
            FROM bookings b 
            JOIN services s ON b.service_id = s.id
            JOIN masters m ON b.master_id = m.id
            WHERE b.id = ?
        """, (booking_id,)).fetchone()
        
        if not booking:
            raise HTTPException(404, "Booking not found")
        
        registered_at = datetime.strptime(booking["registered_at"], "%Y-%m-%d %H:%M:%S")
        days_since = (datetime.now() - registered_at).days
        
        if days_since < 21:
            conn.execute("UPDATE bookings SET status = 'confirmed' WHERE id = ?", (booking_id,))
            conn.commit()
            
            token = secrets.token_urlsafe(16)
            conn.execute("""
                INSERT INTO chats (booking_id, master_id, client_telegram_id, master_telegram_id, token)
                VALUES (?, ?, ?, ?, ?)
            """, (booking_id, booking["master_id"], booking["client_telegram_id"], booking["master_telegram_id"], token))
            conn.commit()
            
            chat_link = f"https://t.me/pinkspotvelur_bot?start=chat_{token}"
            
            await send_message_to_client(
                booking["client_telegram_id"],
                f"✅ *Запись подтверждена! (бесплатный период)*\n\n"
                f"💅 {booking['service_name']}\n👩 {booking['master_name']}\n📅 {booking['date']} в {booking['time']}\n\n"
                f"💬 [Чат с мастером]({chat_link})"
            )
            
            await notify_master_with_buttons_v2(
                booking["bot_token"],
                booking["master_telegram_id"],
                f"✅ Запись подтверждена (бесплатно)\nКлиент: {booking['client_name']}\n{booking['date']} в {booking['time']}\n\n💬 [Чат с клиентом]({chat_link})",
                booking_id
            )
            
            return {"free": True, "chat_link": chat_link}
        
        amount = booking["price"]
        commission = round(amount * 0.10, 2)
        
        conn.execute("UPDATE bookings SET status = 'awaiting_payment', deposit_amount = ? WHERE id = ?", (commission, booking_id))
        conn.commit()
        
        payment_url = f"https://t.me/pinkspotvelur_bot?start=pay_{booking_id}_{commission}"
        
        return {
            "free": False,
            "payment_url": payment_url,
            "commission": commission,
            "booking_id": booking_id
        }
    finally:
        conn.close()


@app.post("/confirm-commission-payment/{booking_id}")
async def confirm_commission_payment(booking_id: int):
    conn = get_db()
    try:
        booking = conn.execute("""
            SELECT b.*, m.name as master_name, m.bot_token, m.telegram_id as master_telegram_id
            FROM bookings b
            JOIN masters m ON b.master_id = m.id
            WHERE b.id = ?
        """, (booking_id,)).fetchone()
        
        if not booking:
            raise HTTPException(404, "Booking not found")
        
        if booking["status"] != "awaiting_payment":
            raise HTTPException(400, "Booking not awaiting payment")
        
        conn.execute("UPDATE bookings SET status = 'confirmed', payment_status = 'paid' WHERE id = ?", (booking_id,))
        conn.commit()
        
        token = secrets.token_urlsafe(16)
        conn.execute("""
            INSERT INTO chats (booking_id, master_id, client_telegram_id, master_telegram_id, token)
            VALUES (?, ?, ?, ?, ?)
        """, (booking_id, booking["master_id"], booking["client_telegram_id"], booking["master_telegram_id"], token))
        conn.commit()
        
        chat_link = f"https://t.me/pinkspotvelur_bot?start=chat_{token}"
        
        await send_message_to_client(
            booking["client_telegram_id"],
            f"✅ *Запись подтверждена!*\n\n"
            f"💅 {booking['service_name']}\n👩 {booking['master_name']}\n📅 {booking['date']} в {booking['time']}\n"
            f"💰 Оплачено: {booking['deposit_amount']} ₽ (комиссия 10%)\n\n"
            f"💬 [Чат с мастером]({chat_link})"
        )
        
        await notify_master_with_buttons_v2(
            booking["bot_token"],
            booking["master_telegram_id"],
            f"✅ *Клиент оплатил комиссию 10%!*\n\n"
            f"Клиент: {booking['client_name']}\n"
            f"Запись: {booking['date']} в {booking['time']}\n"
            f"💰 Комиссия: {booking['deposit_amount']} ₽\n\n"
            f"💬 [Чат с клиентом]({chat_link})",
            booking_id
        )
        
        return {"status": "ok", "chat_link": chat_link}
    finally:
        conn.close()


# ========== НАПОМИНАНИЯ ==========

@app.get("/send-reminders")
async def send_reminders():
    conn = get_db()
    try:
        now = datetime.now()
        two_hours_later = now + timedelta(hours=2)
        
        bookings = conn.execute("""
            SELECT b.*, m.name as master_name, m.bot_token, m.telegram_id as master_telegram_id, s.name as service_name
            FROM bookings b
            JOIN masters m ON b.master_id = m.id
            JOIN services s ON b.service_id = s.id
            WHERE b.date = ? AND b.time = ? AND b.status = 'confirmed' AND b.reminder_sent = 0
        """, (two_hours_later.strftime("%Y-%m-%d"), two_hours_later.strftime("%H:%M"))).fetchall()
        
        sent = 0
        for booking in bookings:
            await send_message_to_client(
                booking["client_telegram_id"],
                f"⏰ *Напоминание!*\n\nЧерез 2 часа у вас запись к {booking['master_name']}\n"
                f"💅 {booking['service_name']}\n"
                f"📅 {booking['date']} в {booking['time']}\n\n"
                f"Пожалуйста, не опаздывайте! ✨"
            )
            
            conn.execute("UPDATE bookings SET reminder_sent = 1 WHERE id = ?", (booking["id"],))
            sent += 1
        
        conn.commit()
        return {"sent": sent}
    finally:
        conn.close()


@app.get("/")
def root():
    return {"status": "Beauty Bot API running 🌸"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
