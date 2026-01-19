"""
Persistence backend selection and CRUD helpers.

This module provides a unified interface to the rest of the Flask app so routes do not
need to care whether persistence is provided by Supabase or local SQLite.

Behavior:
- If Supabase env vars are configured, we use the existing `app.db` supabase-backed
  implementation (current production/default behavior).
- Otherwise, we fall back to SQLite using SQLAlchemy and the shared SQLite database
  file (SQLITE_DB env var), ensuring required tables exist.

This keeps the backend from crashing when Supabase is not configured while still
supporting persistent storage for bookings.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .supabase_client import is_supabase_configured

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for SQLite fallback models."""


class BookingRow(Base):
    """SQLite fallback booking row.

    Note: This model matches the OpenAPI Booking schema used by the frontend/admin:
      - id, name, phone, pincode, brand, model, service, status, notes, created_at, updated_at
    """

    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    pincode: Mapped[str] = mapped_column(String(6), nullable=False, index=True)

    brand: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    service: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(Text, nullable=False, default="Pending", server_default="Pending")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


_ENGINE = None
_SessionLocal = None


def _utcnow() -> datetime:
    """Return a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def _sqlite_db_url() -> str:
    """Return SQLAlchemy DB URL for the configured SQLite DB file."""
    # IMPORTANT: SQLITE_DB exists in the DB container; backend should have it set too.
    # The orchestrator sets env vars; do not hardcode file paths here.
    sqlite_path = (os.environ.get("SQLITE_DB") or "").strip()
    if not sqlite_path:
        raise RuntimeError(
            "Missing SQLITE_DB environment variable. "
            "Set SQLITE_DB to the SQLite file path (e.g. .../mobile_service_database/myapp.db)."
        )
    # Four slashes: absolute path.
    return f"sqlite:///{sqlite_path}"


def _get_sqlite_engine():
    """Create (or reuse) the SQLite engine."""
    global _ENGINE
    if _ENGINE is None:
        # check_same_thread=False allows usage from different threads in dev servers.
        _ENGINE = create_engine(_sqlite_db_url(), connect_args={"check_same_thread": False})
    return _ENGINE


def _get_sqlite_session_factory():
    """Create (or reuse) the SQLite session factory."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=_get_sqlite_engine(), autoflush=False, autocommit=False, expire_on_commit=False)
    return _SessionLocal


def _ensure_sqlite_tables_exist() -> None:
    """Ensure the SQLite schema has the tables needed by the backend.

    We create a minimal set of tables required for current API endpoints:
      - bookings
      - customer_requests (for /api/submit_form)
      - site_content (for /api/about and /api/contact)
      - services (for /api/services)
      - device_brands, device_models, repair_services (for booking flow catalogs)

    This is intentionally minimal and compatible with SQLite.
    """
    engine = _get_sqlite_engine()
    insp = inspect(engine)
    existing = set(insp.get_table_names())

    # Create the bookings table via SQLAlchemy metadata (portable).
    if "bookings" not in existing:
        Base.metadata.create_all(bind=engine, tables=[BookingRow.__table__])
        existing.add("bookings")

    # Create additional tables (SQLite-friendly) if missing. We use raw SQL here
    # to match the original sqlite template behavior without pulling in more models.
    ddl_statements: list[str] = []

    if "customer_requests" not in existing:
        ddl_statements.append(
            """
            CREATE TABLE IF NOT EXISTS customer_requests (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL,
              phone TEXT NOT NULL,
              email TEXT NOT NULL,
              mobile_model TEXT NOT NULL,
              problem TEXT NOT NULL,
              created_at TEXT NOT NULL
            )
            """
        )

    if "site_content" not in existing:
        ddl_statements.append(
            """
            CREATE TABLE IF NOT EXISTS site_content (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            )
            """
        )

    if "services" not in existing:
        ddl_statements.append(
            """
            CREATE TABLE IF NOT EXISTS services (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              title TEXT NOT NULL,
              description TEXT NOT NULL,
              icon TEXT,
              price_hint TEXT,
              sort_order INTEGER
            )
            """
        )

    if "device_brands" not in existing:
        ddl_statements.append(
            """
            CREATE TABLE IF NOT EXISTS device_brands (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL,
              sort_order INTEGER
            )
            """
        )

    if "device_models" not in existing:
        ddl_statements.append(
            """
            CREATE TABLE IF NOT EXISTS device_models (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              brand TEXT NOT NULL,
              name TEXT NOT NULL,
              sort_order INTEGER
            )
            """
        )

    if "repair_services" not in existing:
        ddl_statements.append(
            """
            CREATE TABLE IF NOT EXISTS repair_services (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              title TEXT NOT NULL,
              icon TEXT,
              price_hint TEXT,
              sort_order INTEGER
            )
            """
        )

    if ddl_statements:
        with engine.begin() as conn:
            for stmt in ddl_statements:
                conn.execute(text(stmt))


def _seed_sqlite_if_needed() -> None:
    """Best-effort seed for SQLite catalogs/content to keep frontend functional."""
    engine = _get_sqlite_engine()
    with engine.begin() as conn:
        # site_content defaults
        conn.execute(
            text("INSERT OR IGNORE INTO site_content(key,value) VALUES (:k,:v)"),
            {"k": "about_description", "v": "We provide fast, reliable mobile repair services with transparent pricing."},
        )
        conn.execute(
            text("INSERT OR IGNORE INTO site_content(key,value) VALUES (:k,:v)"),
            {"k": "contact_hours", "v": "Mon–Sat: 9am–7pm • Sun: 11am–4pm"},
        )
        conn.execute(
            text("INSERT OR IGNORE INTO site_content(key,value) VALUES (:k,:v)"),
            {"k": "contact_phone", "v": "+1 (555) 123-4567"},
        )
        conn.execute(
            text("INSERT OR IGNORE INTO site_content(key,value) VALUES (:k,:v)"),
            {"k": "contact_email", "v": "support@example.com"},
        )

        # services (if empty)
        count = conn.execute(text("SELECT COUNT(1) AS c FROM services")).mappings().first()["c"]
        if int(count) == 0:
            conn.execute(
                text(
                    """
                    INSERT INTO services(title, description, icon, price_hint, sort_order)
                    VALUES
                      ('Screen Replacement','High-quality display replacement','📱','From ₹1999',1),
                      ('Battery Replacement','Battery health restore','🔋','From ₹999',2),
                      ('Charging Port','Fix charging issues','🔌','From ₹799',3),
                      ('Camera Repair','Camera module service','📷','From ₹1199',4),
                      ('Speaker Repair','Fix speaker/audio','🔊','From ₹699',5),
                      ('Software Issues','OS and performance fixes','🧠','From ₹499',6)
                    """
                )
            )

        # brands + models (if empty)
        bcount = conn.execute(text("SELECT COUNT(1) AS c FROM device_brands")).mappings().first()["c"]
        if int(bcount) == 0:
            brands = ["iPhone", "Samsung", "OnePlus", "Vivo", "Oppo", "Xiaomi", "Realme", "Nokia", "Motorola"]
            for i, b in enumerate(brands, start=1):
                conn.execute(text("INSERT INTO device_brands(name, sort_order) VALUES (:n,:o)"), {"n": b, "o": i})

            models = {
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
            for b, ms in models.items():
                for j, m in enumerate(ms, start=1):
                    conn.execute(
                        text("INSERT INTO device_models(brand, name, sort_order) VALUES (:b,:n,:o)"),
                        {"b": b, "n": m, "o": j},
                    )

        # repair services (if empty)
        rcount = conn.execute(text("SELECT COUNT(1) AS c FROM repair_services")).mappings().first()["c"]
        if int(rcount) == 0:
            conn.execute(
                text(
                    """
                    INSERT INTO repair_services(title, icon, price_hint, sort_order)
                    VALUES
                      ('Display Replacement','📱','From ₹1999',1),
                      ('Battery Replacement','🔋','From ₹999',2),
                      ('Charging Port','🔌','From ₹799',3),
                      ('Camera','📷','From ₹1199',4),
                      ('Speaker','🔊','From ₹699',5),
                      ('Software Issue','🧠','From ₹499',6)
                    """
                )
            )


# PUBLIC_INTERFACE
def init_schema() -> None:
    """Initialize persistence.

    - If Supabase is configured: delegate to existing supabase init in app.db.
    - Else: ensure SQLite tables exist + seed catalogs/content.
    """
    if is_supabase_configured():
        # Import here to avoid side effects when Supabase isn't configured.
        from . import db as supabase_db

        supabase_db.init_schema()
        return

    try:
        _ensure_sqlite_tables_exist()
        _seed_sqlite_if_needed()
        logger.info("SQLite persistence initialized (Supabase not configured).")
    except Exception:
        # Do not crash startup; log. Routes will return safe errors.
        logger.exception("SQLite init_schema failed; continuing without DB-backed features.")


# PUBLIC_INTERFACE
def list_services() -> list[dict]:
    """Return services shown on the Services section."""
    if is_supabase_configured():
        from . import db as supabase_db

        return supabase_db.list_services()

    engine = _get_sqlite_engine()
    with engine.begin() as conn:
        rows = (
            conn.execute(
                text(
                    """
                    SELECT id, title, description, icon, price_hint
                    FROM services
                    ORDER BY COALESCE(sort_order, 999999), id
                    """
                )
            )
            .mappings()
            .all()
        )
        return [dict(r) for r in rows]


# PUBLIC_INTERFACE
def list_booking_services() -> list[dict]:
    """Return repair service options used in booking step-3 UI."""
    if is_supabase_configured():
        from . import db as supabase_db

        return supabase_db.list_booking_services()

    engine = _get_sqlite_engine()
    with engine.begin() as conn:
        rows = (
            conn.execute(
                text(
                    """
                    SELECT id, title, icon, price_hint
                    FROM repair_services
                    ORDER BY COALESCE(sort_order, 999999), id
                    """
                )
            )
            .mappings()
            .all()
        )
        return [dict(r) for r in rows]


# PUBLIC_INTERFACE
def list_brands() -> list[dict]:
    """Return available brands for step-1 (Select Brand)."""
    if is_supabase_configured():
        from . import db as supabase_db

        return supabase_db.list_brands()

    engine = _get_sqlite_engine()
    with engine.begin() as conn:
        rows = (
            conn.execute(
                text(
                    """
                    SELECT id, name
                    FROM device_brands
                    ORDER BY COALESCE(sort_order, 999999), name
                    """
                )
            )
            .mappings()
            .all()
        )
        return [dict(r) for r in rows]


# PUBLIC_INTERFACE
def list_models_for_brand(brand: str) -> list[dict]:
    """Return models for step-2 (Select Model)."""
    if is_supabase_configured():
        from . import db as supabase_db

        return supabase_db.list_models_for_brand(brand)

    engine = _get_sqlite_engine()
    with engine.begin() as conn:
        rows = (
            conn.execute(
                text(
                    """
                    SELECT id, brand, name
                    FROM device_models
                    WHERE brand = :brand
                    ORDER BY COALESCE(sort_order, 999999), name
                    """
                ),
                {"brand": brand},
            )
            .mappings()
            .all()
        )
        return [dict(r) for r in rows]


# PUBLIC_INTERFACE
def get_site_content(keys: list[str]) -> dict:
    """Fetch key/value site content entries for the given keys."""
    if is_supabase_configured():
        from . import db as supabase_db

        return supabase_db.get_site_content(keys)

    if not keys:
        return {}

    engine = _get_sqlite_engine()
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT key, value FROM site_content WHERE key IN :keys"),
            {"keys": tuple(keys)},
        ).mappings()
        out: dict[str, str] = {}
        for r in rows:
            out[str(r["key"])] = str(r["value"] or "")
        return out


# PUBLIC_INTERFACE
def create_customer_request(name: str, phone: str, email: str, mobile_model: str, problem: str) -> int:
    """Insert a customer request row and return the new ID."""
    if is_supabase_configured():
        from . import db as supabase_db

        return supabase_db.create_customer_request(
            name=name, phone=phone, email=email, mobile_model=mobile_model, problem=problem
        )

    engine = _get_sqlite_engine()
    with engine.begin() as conn:
        res = conn.execute(
            text(
                """
                INSERT INTO customer_requests(name, phone, email, mobile_model, problem, created_at)
                VALUES (:name,:phone,:email,:mobile_model,:problem,:created_at)
                """
            ),
            {
                "name": name,
                "phone": phone,
                "email": email,
                "mobile_model": mobile_model,
                "problem": problem,
                "created_at": _utcnow().isoformat(),
            },
        )
        return int(res.lastrowid)


# PUBLIC_INTERFACE
def create_booking(name: str, phone: str, pincode: str) -> int:
    """Insert a booking row and return the new ID.

    Raises:
      ValueError: for user-facing validation errors discovered at persistence layer.
      RuntimeError: for unexpected errors.
    """
    if is_supabase_configured():
        from . import db as supabase_db

        return supabase_db.create_booking(name=name, phone=phone, pincode=pincode)

    SessionLocal = _get_sqlite_session_factory()
    now = _utcnow()

    try:
        with SessionLocal() as session:
            row = BookingRow(
                name=name,
                phone=phone,
                pincode=pincode,
                status="Pending",
                notes=None,
                brand=None,
                model=None,
                service=None,
                created_at=now,
                updated_at=None,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return int(row.id)
    except IntegrityError as e:
        # Should not typically happen without unique constraints, but be safe.
        raise ValueError("Unable to create booking due to invalid data.") from e
    except OperationalError as e:
        # Typically missing table or locked DB.
        logger.exception("SQLite operational error while creating booking.")
        raise RuntimeError("Database error.") from e


# PUBLIC_INTERFACE
def update_booking_device_selection(booking_id: int, brand: str | None, model: str | None, service: str | None) -> dict | None:
    """Update booking selection fields; returns updated booking dict or None if not found."""
    if is_supabase_configured():
        from . import db as supabase_db

        return supabase_db.update_booking_device_selection(booking_id=booking_id, brand=brand, model=model, service=service)

    SessionLocal = _get_sqlite_session_factory()
    with SessionLocal() as session:
        row = session.get(BookingRow, int(booking_id))
        if not row:
            return None
        row.brand = brand
        row.model = model
        row.service = service
        row.updated_at = _utcnow()
        session.commit()
        session.refresh(row)
        return _booking_row_to_dict(row)


def _booking_row_to_dict(row: BookingRow) -> dict:
    """Convert BookingRow -> dict matching API shape."""
    return {
        "id": int(row.id),
        "name": row.name,
        "phone": row.phone,
        "pincode": row.pincode,
        "brand": row.brand,
        "model": row.model,
        "service": row.service,
        "status": row.status,
        "notes": row.notes,
        "created_at": (row.created_at.isoformat() if isinstance(row.created_at, datetime) else str(row.created_at)),
        "updated_at": (row.updated_at.isoformat() if row.updated_at else None),
    }


# PUBLIC_INTERFACE
def list_bookings(limit: int = 200) -> list[dict]:
    """Return recent bookings for admin panel (most recent first)."""
    if is_supabase_configured():
        from . import db as supabase_db

        return supabase_db.list_bookings(limit=limit)

    safe_limit = max(1, min(int(limit or 200), 1000))
    SessionLocal = _get_sqlite_session_factory()
    with SessionLocal() as session:
        rows = session.query(BookingRow).order_by(BookingRow.id.desc()).limit(safe_limit).all()
        return [_booking_row_to_dict(r) for r in rows]


# PUBLIC_INTERFACE
def get_booking_by_id(booking_id: int) -> dict | None:
    """Fetch a booking by id."""
    if is_supabase_configured():
        from . import db as supabase_db

        return supabase_db.get_booking_by_id(booking_id)

    SessionLocal = _get_sqlite_session_factory()
    with SessionLocal() as session:
        row = session.get(BookingRow, int(booking_id))
        return _booking_row_to_dict(row) if row else None


# PUBLIC_INTERFACE
def get_latest_booking_by_phone(phone: str) -> dict | None:
    """Fetch latest booking for given phone (caller normalizes phone)."""
    if is_supabase_configured():
        from . import db as supabase_db

        return supabase_db.get_latest_booking_by_phone(phone)

    SessionLocal = _get_sqlite_session_factory()
    with SessionLocal() as session:
        row = session.query(BookingRow).filter(BookingRow.phone == phone).order_by(BookingRow.id.desc()).first()
        return _booking_row_to_dict(row) if row else None


# PUBLIC_INTERFACE
def update_booking_status(booking_id: int, status: str, notes: str | None = None) -> dict | None:
    """Update booking status/notes and return updated booking, or None if not found."""
    if is_supabase_configured():
        from . import db as supabase_db

        return supabase_db.update_booking_status(booking_id=booking_id, status=status, notes=notes)

    SessionLocal = _get_sqlite_session_factory()
    with SessionLocal() as session:
        row = session.get(BookingRow, int(booking_id))
        if not row:
            return None
        row.status = status
        row.notes = notes
        row.updated_at = _utcnow()
        session.commit()
        session.refresh(row)
        return _booking_row_to_dict(row)


# PUBLIC_INTERFACE
def verify_admin_credentials(username: str, password: str) -> bool:
    """Verify admin username/password (delegated to existing supabase db module)."""
    from . import db as supabase_db

    return supabase_db.verify_admin_credentials(username=username, password=password)


# PUBLIC_INTERFACE
def is_pincode_serviceable(pincode: str) -> bool:
    """Return whether pincode is serviceable (delegated to existing supabase db module if configured).

    If Supabase is not configured, we default to True (matching the old stub behavior).
    """
    if is_supabase_configured():
        from . import db as supabase_db

        return supabase_db.is_pincode_serviceable(pincode)

    # Local SQLite schema doesn't include a serviceability table in the template.
    return True
