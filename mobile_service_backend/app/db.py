import os
import sqlite3


# PUBLIC_INTERFACE
def get_db_path() -> str:
    """Return the SQLite database path from environment.

    Uses SQLITE_DB if present; otherwise falls back to a local myapp.db for dev.
    """
    return os.environ.get("SQLITE_DB") or os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "myapp.db")
    )


def _connect() -> sqlite3.Connection:
    """Create a SQLite connection with row access by column name."""
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _table_columns(cur: sqlite3.Cursor, table: str) -> set[str]:
    """Return column names for a table via PRAGMA table_info."""
    cur.execute(f"PRAGMA table_info({table})")
    return {r["name"] for r in cur.fetchall()}


def _seed_device_catalog(cur: sqlite3.Cursor) -> None:
    """Seed brands/models/services catalog tables if empty.

    This keeps the demo self-contained and supports the required dynamic UI:
    - GET /api/brands
    - GET /api/models?brand=...
    - GET /api/booking/services
    """
    # Brands
    cur.execute("SELECT COUNT(1) AS n FROM device_brands")
    if int(cur.fetchone()["n"]) == 0:
        brands = [
            "iPhone",
            "Samsung",
            "OnePlus",
            "Vivo",
            "Oppo",
            "Xiaomi",
            "Realme",
            "Nokia",
            "Motorola",
        ]
        for b in brands:
            cur.execute("INSERT INTO device_brands (name) VALUES (?)", (b,))

    # Models (simple demo coverage)
    cur.execute("SELECT COUNT(1) AS n FROM device_models")
    if int(cur.fetchone()["n"]) == 0:
        model_seed = {
            "iPhone": ["iPhone 11", "iPhone 12", "iPhone 13", "iPhone 14", "iPhone 15"],
            "Samsung": ["Galaxy S21", "Galaxy S22", "Galaxy S23", "Galaxy A52", "Galaxy A54"],
            "OnePlus": ["OnePlus 8", "OnePlus 9", "OnePlus 10", "OnePlus 11", "OnePlus 12"],
            "Vivo": ["Vivo V21", "Vivo V23", "Vivo V25", "Vivo V27"],
            "Oppo": ["Oppo F19", "Oppo F21", "Oppo Reno 7", "Oppo Reno 8"],
            "Xiaomi": ["Redmi Note 10", "Redmi Note 11", "Redmi Note 12", "Mi 11X"],
            "Realme": ["Realme 8", "Realme 9", "Realme 10", "Realme 11"],
            "Nokia": ["Nokia 5.4", "Nokia 6.1", "Nokia 7.2"],
            "Motorola": ["Moto G60", "Moto G71", "Moto Edge 20"],
        }

        for brand, models in model_seed.items():
            for m in models:
                cur.execute("INSERT INTO device_models (brand, name) VALUES (?, ?)", (brand, m))

    # Service options (for step 3)
    cur.execute("SELECT COUNT(1) AS n FROM repair_services")
    if int(cur.fetchone()["n"]) == 0:
        services = [
            ("Display Replacement", "📱", "From ₹1999"),
            ("Battery Replacement", "🔋", "From ₹999"),
            ("Charging Port", "🔌", "From ₹799"),
            ("Camera", "📷", "From ₹1199"),
            ("Speaker", "🔊", "From ₹699"),
            ("Software Issue", "🧠", "From ₹499"),
        ]
        for title, icon, price_hint in services:
            cur.execute(
                "INSERT INTO repair_services (title, icon, price_hint) VALUES (?, ?, ?)",
                (title, icon, price_hint),
            )


# PUBLIC_INTERFACE
def init_schema() -> None:
    """Ensure required tables exist.

    This is intentionally minimal and idempotent to support easy startup in dev/CI.
    """
    conn = _connect()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            icon TEXT,
            price_hint TEXT,
            sort_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS customer_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            email TEXT NOT NULL,
            mobile_model TEXT NOT NULL,
            problem TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # Booking table:
    # - created via hero booking form (name/phone/pincode)
    # - later updated with brand/model/services during the multi-step flow
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            pincode TEXT NOT NULL,
            brand TEXT,
            model TEXT,
            service TEXT,
            status TEXT NOT NULL DEFAULT 'Pending',
            notes TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    booking_cols = _table_columns(cur, "bookings")
    # Lightweight migration: add columns if the DB existed before these fields.
    if "brand" not in booking_cols:
        cur.execute("ALTER TABLE bookings ADD COLUMN brand TEXT")
    if "model" not in booking_cols:
        cur.execute("ALTER TABLE bookings ADD COLUMN model TEXT")
    if "service" not in booking_cols:
        cur.execute("ALTER TABLE bookings ADD COLUMN service TEXT")
    if "status" not in booking_cols:
        cur.execute("ALTER TABLE bookings ADD COLUMN status TEXT NOT NULL DEFAULT 'Pending'")
    if "notes" not in booking_cols:
        cur.execute("ALTER TABLE bookings ADD COLUMN notes TEXT")
    if "updated_at" not in booking_cols:
        cur.execute("ALTER TABLE bookings ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")

    # Simple device catalog tables used by the flow (brands/models/services).
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS device_brands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            sort_order INTEGER DEFAULT 0
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS device_models (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            brand TEXT NOT NULL,
            name TEXT NOT NULL,
            sort_order INTEGER DEFAULT 0
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS repair_services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            icon TEXT,
            price_hint TEXT,
            sort_order INTEGER DEFAULT 0
        )
        """
    )

    # Seed catalog rows if empty (idempotent).
    _seed_device_catalog(cur)

    # Admin users (simple username/password for the assignment).
    # In production: store salted hashes. Here we keep it env-configurable and minimal.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # Seed a default admin if env vars are provided.
    default_admin_user = os.environ.get("ADMIN_DEFAULT_USERNAME")
    default_admin_pass = os.environ.get("ADMIN_DEFAULT_PASSWORD")
    if default_admin_user and default_admin_pass:
        cur.execute(
            "INSERT OR IGNORE INTO admin_users (username, password) VALUES (?, ?)",
            (default_admin_user, default_admin_pass),
        )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS site_content (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    defaults = {
        "about_description": "We provide practical, honest mobile repair and troubleshooting. Our goal is to get your device working with clear options and fair pricing.",
        "contact_hours": "Mon–Sat: 9am–7pm • Sun: 11am–4pm",
        "contact_phone": "+1 (555) 123-4567",
        "contact_email": "support@example.com",
    }
    for k, v in defaults.items():
        cur.execute("INSERT OR IGNORE INTO site_content (key, value) VALUES (?, ?)", (k, v))

    conn.commit()
    conn.close()


# PUBLIC_INTERFACE
def list_services() -> list[dict]:
    """Return services in stable display order."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, title, description, icon, price_hint
        FROM services
        ORDER BY sort_order ASC, id ASC
        """
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# PUBLIC_INTERFACE
def list_booking_services() -> list[dict]:
    """Return repair service options used in the booking step-3 UI."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, title, icon, price_hint
        FROM repair_services
        ORDER BY sort_order ASC, id ASC
        """
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# PUBLIC_INTERFACE
def list_brands() -> list[dict]:
    """Return available device brands for the booking flow."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, name
        FROM device_brands
        ORDER BY sort_order ASC, name ASC
        """
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# PUBLIC_INTERFACE
def list_models_for_brand(brand: str) -> list[dict]:
    """Return available models for a given brand."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, brand, name
        FROM device_models
        WHERE brand = ?
        ORDER BY sort_order ASC, name ASC
        """,
        (brand,),
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# PUBLIC_INTERFACE
def get_site_content(keys: list[str]) -> dict:
    """Fetch key/value site content entries for the given keys."""
    if not keys:
        return {}
    placeholders = ",".join(["?"] * len(keys))
    conn = _connect()
    cur = conn.cursor()
    cur.execute(f"SELECT key, value FROM site_content WHERE key IN ({placeholders})", keys)
    rows = cur.fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}


# PUBLIC_INTERFACE
def create_customer_request(name: str, phone: str, email: str, mobile_model: str, problem: str) -> int:
    """Insert a customer request row and return the new ID."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO customer_requests (name, phone, email, mobile_model, problem)
        VALUES (?, ?, ?, ?, ?)
        """,
        (name, phone, email, mobile_model, problem),
    )
    conn.commit()
    new_id = int(cur.lastrowid)
    conn.close()
    return new_id


# PUBLIC_INTERFACE
def create_booking(name: str, phone: str, pincode: str) -> int:
    """Insert a booking row (hero booking form) and return the new ID."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO bookings (name, phone, pincode)
        VALUES (?, ?, ?)
        """,
        (name, phone, pincode),
    )
    conn.commit()
    new_id = int(cur.lastrowid)
    conn.close()
    return new_id


# PUBLIC_INTERFACE
def update_booking_device_selection(booking_id: int, brand: str | None, model: str | None, service: str | None) -> dict | None:
    """Update booking device/service selection fields and return updated booking, or None if not found."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT id FROM bookings WHERE id = ?", (int(booking_id),))
    exists = cur.fetchone()
    if not exists:
        conn.close()
        return None

    cur.execute(
        """
        UPDATE bookings
        SET brand = ?,
            model = ?,
            service = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (brand, model, service, int(booking_id)),
    )
    conn.commit()
    conn.close()
    return get_booking_by_id(int(booking_id))


# PUBLIC_INTERFACE
def list_bookings(limit: int = 200) -> list[dict]:
    """Return recent bookings for the admin panel (most recent first)."""
    safe_limit = max(1, min(int(limit or 200), 1000))
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, name, phone, pincode, brand, model, service, status, notes, created_at, updated_at
        FROM bookings
        ORDER BY id DESC
        LIMIT ?
        """,
        (safe_limit,),
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# PUBLIC_INTERFACE
def get_booking_by_id(booking_id: int) -> dict | None:
    """Fetch a booking by ID for tracking/confirmation."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, name, phone, pincode, brand, model, service, status, notes, created_at, updated_at
        FROM bookings
        WHERE id = ?
        """,
        (int(booking_id),),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


# PUBLIC_INTERFACE
def get_latest_booking_by_phone(phone: str) -> dict | None:
    """Fetch the latest booking for a given phone number (normalized by caller)."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, name, phone, pincode, brand, model, service, status, notes, created_at, updated_at
        FROM bookings
        WHERE phone = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (phone,),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


# PUBLIC_INTERFACE
def update_booking_status(booking_id: int, status: str, notes: str | None = None) -> dict | None:
    """Update booking status/notes and return updated row, or None if not found."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT id FROM bookings WHERE id = ?", (int(booking_id),))
    exists = cur.fetchone()
    if not exists:
        conn.close()
        return None

    cur.execute(
        """
        UPDATE bookings
        SET status = ?,
            notes = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (status, notes, int(booking_id)),
    )
    conn.commit()
    conn.close()
    return get_booking_by_id(int(booking_id))


# PUBLIC_INTERFACE
def verify_admin_credentials(username: str, password: str) -> bool:
    """Verify admin username/password against the admin_users table."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id
        FROM admin_users
        WHERE username = ? AND password = ?
        LIMIT 1
        """,
        (username, password),
    )
    row = cur.fetchone()
    conn.close()
    return bool(row)
