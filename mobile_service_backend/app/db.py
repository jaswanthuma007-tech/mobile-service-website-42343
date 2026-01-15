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

    # New: bookings table matching the hero booking form + repair tracking.
    # status: Pending | In Progress | Completed
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            pincode TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending',
            notes TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # Lightweight schema migration for existing DBs created before status/notes fields existed.
    # SQLite supports ADD COLUMN; we keep it safe by checking PRAGMA table_info.
    cur.execute("PRAGMA table_info(bookings)")
    booking_cols = {r["name"] for r in cur.fetchall()}
    if "status" not in booking_cols:
        cur.execute("ALTER TABLE bookings ADD COLUMN status TEXT NOT NULL DEFAULT 'Pending'")
    if "notes" not in booking_cols:
        cur.execute("ALTER TABLE bookings ADD COLUMN notes TEXT")
    if "updated_at" not in booking_cols:
        cur.execute("ALTER TABLE bookings ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")

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
    # Required env vars (optional):
    # - ADMIN_DEFAULT_USERNAME
    # - ADMIN_DEFAULT_PASSWORD
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

    # Seed site content defaults if missing
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
def list_bookings(limit: int = 200) -> list[dict]:
    """Return recent bookings for the admin panel (most recent first)."""
    safe_limit = max(1, min(int(limit or 200), 1000))
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, name, phone, pincode, status, notes, created_at, updated_at
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
    """Fetch a booking by ID for tracking."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, name, phone, pincode, status, notes, created_at, updated_at
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
        SELECT id, name, phone, pincode, status, notes, created_at, updated_at
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
