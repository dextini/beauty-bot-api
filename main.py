from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import sqlite3
import os
import httpx
import json
from datetime import datetime, timedelta
from fastapi.responses import JSONResponse
from fastapi import Request

app = FastAPI(title="Beauty Bot API")

# === CORS НАСТРОЕН ПРАВИЛЬНО ===
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
            work_end TEXT DEFAULT '20:00'
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

    # Добавляем колонки для существующих БД
    for col in ["telegram_id TEXT", "work_start TEXT DEFAULT '09:00'", "work_end TEXT DEFAULT '20:00'"]:
        try:
            c.execute(f"ALTER TABLE masters ADD COLUMN {col}")
        except:
            pass

    # Добавляем колонку bot_token
    try:
        c.execute("ALTER TABLE masters ADD COLUMN bot_token TEXT")
        print("✅ Колонка bot_token добавлена")
    except:
        print("⚠️ Колонка bot_token уже есть")

    # Добавляем колонку photos (JSON массив)
    try:
        c.execute("ALTER TABLE masters ADD COLUMN photos TEXT")
        print("✅ Колонка photos добавлена")
    except:
        print("⚠️ Колонка photos уже есть")

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


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def generate_slots(work_start: str, work_end: str, interval: int = 30) -> List[str]:
    slots = []
    start = datetime.strptime(work_start, "%H:%M")
    end = datetime.strptime(work_end, "%H:%M")
    current = start
    while current < end:
        slots.append(current.strftime("%H:%M"))
        current += timedelta(minutes=interval)
    return slots


# === ФУНКЦИЯ ОТПРАВКИ УВЕДОМЛЕНИЙ В БОТА МАСТЕРА ===
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


# --- Routes ---
@app.get("/masters", response_model=List[MasterOut])
def get_masters(conn: sqlite3.Connection = Depends(get_db)):
    masters = conn.execute("SELECT * FROM masters").fetchall()
    result = []
    for m in masters:
        services = conn.execute("SELECT * FROM services WHERE master_id = ?", (m["id"],)).fetchall()
        master_dict = dict(m)
        # Преобразуем JSON строку photos в список
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


# === ЭНДПОИНТЫ ДЛЯ УПРАВЛЕНИЯ ФОТО ===
@app.post("/masters/{master_id}/photos")
def add_master_photo(master_id: int, data: dict, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE id = ?", (master_id,)).fetchone()
    if not master:
        raise HTTPException(status_code=404, detail="Master not found")
    
    current = conn.execute("SELECT photos FROM masters WHERE id = ?", (master_id,)).fetchone()
    photos = json.loads(current["photos"]) if current["photos"] else []
    photos.append(data["photo"])
    
    conn.execute("UPDATE masters SET photos = ? WHERE id = ?", (json.dumps(photos), master_id))
    conn.commit()
    return {"status": "ok", "photos": photos}


@app.delete("/masters/{master_id}/photos")
def delete_master_photo(master_id: int, index: int, conn: sqlite3.Connection = Depends(get_db)):
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


@app.get("/masters/{master_id}/photos")
def get_master_photos(master_id: int, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE id = ?", (master_id,)).fetchone()
    if not master:
        raise HTTPException(status_code=404, detail="Master not found")
    
    current = conn.execute("SELECT photos FROM masters WHERE id = ?", (master_id,)).fetchone()
    photos = json.loads(current["photos"]) if current["photos"] else []
    return {"photos": photos}


# === ЭНДПОИНТ ДЛЯ ДОБАВЛЕНИЯ МАСТЕРА ===
@app.post("/masters")
def add_master(master: dict, conn: sqlite3.Connection = Depends(get_db)):
    if not master.get("name") or not master.get("address"):
        raise HTTPException(status_code=400, detail="Missing name or address")
    
    conn.execute(
        """INSERT INTO masters (name, address, lat, lon, phone, instagram, description) 
           VALUES (?,?,?,?,?,?,?)""",
        (master["name"], master["address"], 
         master.get("lat", 55.751244), master.get("lon", 37.618423),
         master.get("phone"), master.get("instagram"), master.get("description"))
    )
    conn.commit()
    return {"status": "ok", "message": "Master added"}


# === ЭНДПОИНТ ДЛЯ УДАЛЕНИЯ МАСТЕРА ===
@app.delete("/masters/{master_id}")
def delete_master(master_id: int, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE id = ?", (master_id,)).fetchone()
    if not master:
        raise HTTPException(status_code=404, detail="Master not found")
    
    conn.execute("DELETE FROM masters WHERE id = ?", (master_id,))
    conn.commit()
    return {"status": "ok", "message": f"Master {master_id} deleted"}


@app.get("/masters/by_telegram/{telegram_id}")
def get_master_by_telegram(telegram_id: str, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT * FROM masters WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not master:
        raise HTTPException(status_code=404, detail="Master not found")
    return dict(master)


@app.get("/masters/{master_id}", response_model=MasterOut)
def get_master(master_id: int, conn: sqlite3.Connection = Depends(get_db)):
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

    free_slots = [
        s for s in all_slots
        if s not in booked_times and not (date == today and s <= now_time)
    ]

    return {"date": date, "slots": free_slots, "day_off": False}


@app.get("/masters/{master_id}/schedule")
def get_schedule(master_id: int, conn: sqlite3.Connection = Depends(get_db)):
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


@app.post("/masters/{master_id}/days_off")
def add_day_off(master_id: int, date: str, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("INSERT OR IGNORE INTO days_off (master_id, date) VALUES (?,?)", (master_id, date))
    conn.commit()
    return {"status": "ok", "date": date}


@app.delete("/masters/{master_id}/days_off/{date}")
def remove_day_off(master_id: int, date: str, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("DELETE FROM days_off WHERE master_id=? AND date=?", (master_id, date))
    conn.commit()
    return {"status": "ok", "date": date}


@app.patch("/masters/{master_id}/telegram")
def set_master_telegram(master_id: int, telegram_id: str, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE id = ?", (master_id,)).fetchone()
    if not master:
        raise HTTPException(status_code=404, detail="Master not found")
    
    conn.execute("UPDATE masters SET telegram_id = ? WHERE id = ?", (telegram_id, master_id))
    conn.commit()
    return {"status": "ok"}


@app.patch("/masters/{master_id}/bot-token")
def set_master_bot_token(master_id: int, bot_token: str, conn: sqlite3.Connection = Depends(get_db)):
    master = conn.execute("SELECT id FROM masters WHERE id = ?", (master_id,)).fetchone()
    if not master:
        raise HTTPException(status_code=404, detail="Master not found")
    
    conn.execute("UPDATE masters SET bot_token = ? WHERE id = ?", (bot_token, master_id))
    conn.commit()
    return {"status": "ok", "message": "Bot token saved"}


# === ЭНДПОИНТ ДЛЯ ПРИНУДИТЕЛЬНОГО ДОБАВЛЕНИЯ КОЛОНКИ ===
@app.post("/admin/add-bot-token-column")
def add_bot_token_column():
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("ALTER TABLE masters ADD COLUMN bot_token TEXT")
        conn.commit()
        return {"status": "ok", "message": "Column bot_token added successfully"}
    except Exception as e:
        error_msg = str(e)
        if "duplicate column name" in error_msg:
            return {"status": "ok", "message": "Column bot_token already exists"}
        return {"status": "error", "message": error_msg}
    finally:
        conn.close()


# === ИСПРАВЛЕННАЯ ФУНКЦИЯ CREATE BOOKING ===
@app.post("/bookings", response_model=BookingOut)
async def create_booking(data: BookingIn):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

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

        # === УВЕДОМЛЕНИЯ ===
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
async def update_booking_status(booking_id: int, status: str, conn: sqlite3.Connection = Depends(get_db)):
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


@app.get("/bookings/master/{master_id}")
def get_master_bookings(master_id: int, conn: sqlite3.Connection = Depends(get_db)):
    bookings = conn.execute(
        """SELECT b.*, s.name as service_name, s.price FROM bookings b
           JOIN services s ON b.service_id=s.id
           WHERE b.master_id=? AND b.status!='cancelled' ORDER BY b.date, b.time""",
        (master_id,)
    ).fetchall()
    return [dict(b) for b in bookings]


@app.get("/bookings/client/{telegram_id}")
def get_client_bookings(telegram_id: str, conn: sqlite3.Connection = Depends(get_db)):
    bookings = conn.execute(
        """SELECT b.*, m.name as master_name, s.name as service_name, s.price
           FROM bookings b JOIN masters m ON b.master_id=m.id JOIN services s ON b.service_id=s.id
           WHERE b.client_telegram_id=? ORDER BY b.date DESC, b.time DESC""",
        (telegram_id,)
    ).fetchall()
    return [dict(b) for b in bookings]


@app.get("/")
def root():
    return {"status": "Beauty Bot API running 🌸"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
