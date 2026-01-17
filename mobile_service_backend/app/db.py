import logging
from typing import Any

from .supabase_client import get_supabase_client, get_supabase_schema

logger = logging.getLogger(__name__)


def _table(name: str) -> str:
    """Return table name including schema if configured."""
    schema = get_supabase_schema()
    # Supabase postgrest accepts "schema.table" for non-public schemas.
    return f"{schema}.{name}" if schema and schema != "public" else name


def _sb() -> Any:
    """Shorthand to access cached supabase client."""
    return get_supabase_client()


def _sb_exec(query) -> Any:
    """Execute a supabase-py query and return parsed data.

    supabase-py returns objects that can vary by version. We normalize to `data`.
    """
    resp = query.execute()
    # supabase-py typically returns APIResponse with `.data` / `.error`
    data = getattr(resp, "data", None)
    err = getattr(resp, "error", None)
    if err:
        raise RuntimeError(str(err))
    return data


def _ensure_catalog_seeded() -> None:
    """Best-effort seeding for demo catalogs.

    Supabase databases are persistent; this is only to keep parity with the previous
    SQLite template (which auto-seeded on startup).
    """
    try:
        brands = _sb_exec(_sb().table(_table("device_brands")).select("id", count="exact").limit(1))
        # Some versions return [] with count in response; be tolerant:
        # If we can't infer count reliably, skip seeding.
        if isinstance(brands, list) and len(brands) > 0:
            return
    except Exception:
        # If tables are missing or count failed, do not crash startup; endpoints will fail
        # with a clearer error and the operator can create schema from supabase.md.
        logger.info("Supabase seed check skipped/failed (schema might not be created yet).")
        return

    # If count inference not available, still attempt seed only if select returns empty.
    try:
        existing = _sb_exec(_sb().table(_table("device_brands")).select("id").limit(1))
        if existing:
            return
    except Exception:
        return

    try:
        seed_brands = [
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
        _sb_exec(_sb().table(_table("device_brands")).insert([{"name": b} for b in seed_brands]))

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
        model_rows = []
        for brand, models in model_seed.items():
            for m in models:
                model_rows.append({"brand": brand, "name": m})
        _sb_exec(_sb().table(_table("device_models")).insert(model_rows))

        services = [
            {"title": "Display Replacement", "icon": "📱", "price_hint": "From ₹1999"},
            {"title": "Battery Replacement", "icon": "🔋", "price_hint": "From ₹999"},
            {"title": "Charging Port", "icon": "🔌", "price_hint": "From ₹799"},
            {"title": "Camera", "icon": "📷", "price_hint": "From ₹1199"},
            {"title": "Speaker", "icon": "🔊", "price_hint": "From ₹699"},
            {"title": "Software Issue", "icon": "🧠", "price_hint": "From ₹499"},
        ]
        _sb_exec(_sb().table(_table("repair_services")).insert(services))
    except Exception:
        logger.info("Supabase seeding failed; continuing without seed.", exc_info=True)


# PUBLIC_INTERFACE
def init_schema() -> None:
    """Initialize database layer.

    Previously created/ensured SQLite schema. With Supabase/Postgres this function:
    - verifies configuration is present (fails fast if missing)
    - attempts a best-effort seed of catalog tables to preserve demo behavior

    Note: Creating tables is not performed by the backend; use Supabase SQL editor
    according to assets/supabase.md.
    """
    # Force client creation early to surface missing env vars at startup.
    _ = get_supabase_client()
    _ensure_catalog_seeded()


# PUBLIC_INTERFACE
def list_services() -> list[dict]:
    """Return services shown on the Services section."""
    data = _sb_exec(
        _sb()
        .table(_table("services"))
        .select("id,title,description,icon,price_hint")
        .order("sort_order", desc=False)
        .order("id", desc=False)
    )
    return list(data or [])


# PUBLIC_INTERFACE
def list_booking_services() -> list[dict]:
    """Return repair service options used in the booking step-3 UI."""
    data = _sb_exec(
        _sb()
        .table(_table("repair_services"))
        .select("id,title,icon,price_hint")
        .order("sort_order", desc=False)
        .order("id", desc=False)
    )
    return list(data or [])


# PUBLIC_INTERFACE
def list_brands() -> list[dict]:
    """Return available device brands for the booking flow."""
    data = _sb_exec(
        _sb().table(_table("device_brands")).select("id,name").order("sort_order", desc=False).order("name", desc=False)
    )
    return list(data or [])


# PUBLIC_INTERFACE
def list_models_for_brand(brand: str) -> list[dict]:
    """Return available models for a given brand."""
    data = _sb_exec(
        _sb()
        .table(_table("device_models"))
        .select("id,brand,name")
        .eq("brand", brand)
        .order("sort_order", desc=False)
        .order("name", desc=False)
    )
    return list(data or [])


# PUBLIC_INTERFACE
def get_site_content(keys: list[str]) -> dict:
    """Fetch key/value site content entries for the given keys."""
    if not keys:
        return {}
    data = _sb_exec(_sb().table(_table("site_content")).select("key,value").in_("key", keys))
    out: dict[str, str] = {}
    for row in data or []:
        k = row.get("key")
        if k is not None:
            out[str(k)] = str(row.get("value") or "")
    return out


# PUBLIC_INTERFACE
def create_customer_request(name: str, phone: str, email: str, mobile_model: str, problem: str) -> int:
    """Insert a customer request row and return the new ID."""
    inserted = _sb_exec(
        _sb()
        .table(_table("customer_requests"))
        .insert(
            {
                "name": name,
                "phone": phone,
                "email": email,
                "mobile_model": mobile_model,
                "problem": problem,
            }
        )
        .select("id")
        .single()
    )
    return int(inserted["id"])


# PUBLIC_INTERFACE
def create_booking(name: str, phone: str, pincode: str) -> int:
    """Insert a booking row (hero booking form) and return the new ID."""
    inserted = _sb_exec(
        _sb()
        .table(_table("bookings"))
        .insert({"name": name, "phone": phone, "pincode": pincode})
        .select("id")
        .single()
    )
    return int(inserted["id"])


# PUBLIC_INTERFACE
def update_booking_device_selection(
    booking_id: int, brand: str | None, model: str | None, service: str | None
) -> dict | None:
    """Update booking device/service selection fields and return updated booking, or None if not found."""
    # Ensure booking exists
    existing = get_booking_by_id(int(booking_id))
    if not existing:
        return None

    _sb_exec(
        _sb()
        .table(_table("bookings"))
        .update({"brand": brand, "model": model, "service": service})
        .eq("id", int(booking_id))
    )
    return get_booking_by_id(int(booking_id))


# PUBLIC_INTERFACE
def list_bookings(limit: int = 200) -> list[dict]:
    """Return recent bookings for the admin panel (most recent first)."""
    safe_limit = max(1, min(int(limit or 200), 1000))
    data = _sb_exec(
        _sb()
        .table(_table("bookings"))
        .select("id,name,phone,pincode,brand,model,service,status,notes,created_at,updated_at")
        .order("id", desc=True)
        .limit(safe_limit)
    )
    return list(data or [])


# PUBLIC_INTERFACE
def get_booking_by_id(booking_id: int) -> dict | None:
    """Fetch a booking by ID for tracking/confirmation."""
    try:
        data = _sb_exec(
            _sb()
            .table(_table("bookings"))
            .select("id,name,phone,pincode,brand,model,service,status,notes,created_at,updated_at")
            .eq("id", int(booking_id))
            .maybe_single()
        )
        return dict(data) if data else None
    except Exception:
        # maybe_single is not available in all versions; fallback to select+limit
        rows = _sb_exec(
            _sb()
            .table(_table("bookings"))
            .select("id,name,phone,pincode,brand,model,service,status,notes,created_at,updated_at")
            .eq("id", int(booking_id))
            .limit(1)
        )
        return dict(rows[0]) if rows else None


# PUBLIC_INTERFACE
def get_latest_booking_by_phone(phone: str) -> dict | None:
    """Fetch the latest booking for a given phone number (normalized by caller)."""
    rows = _sb_exec(
        _sb()
        .table(_table("bookings"))
        .select("id,name,phone,pincode,brand,model,service,status,notes,created_at,updated_at")
        .eq("phone", phone)
        .order("id", desc=True)
        .limit(1)
    )
    return dict(rows[0]) if rows else None


# PUBLIC_INTERFACE
def update_booking_status(booking_id: int, status: str, notes: str | None = None) -> dict | None:
    """Update booking status/notes and return updated row, or None if not found."""
    existing = get_booking_by_id(int(booking_id))
    if not existing:
        return None

    _sb_exec(
        _sb().table(_table("bookings")).update({"status": status, "notes": notes}).eq("id", int(booking_id))
    )
    return get_booking_by_id(int(booking_id))


# PUBLIC_INTERFACE
def verify_admin_credentials(username: str, password: str) -> bool:
    """Verify admin username/password.

    This project keeps admin auth env-based and/or table-based in SQLite.
    With Supabase migration, admin user storage is intentionally left out to preserve
    the existing flow without adding new auth dependencies. If needed, implement an
    `admin_users` table and query it here.

    Current behavior:
    - If ADMIN_DEFAULT_USERNAME/ADMIN_DEFAULT_PASSWORD env vars are set and match, allow.
    - Else, deny.
    """
    import os

    env_user = (os.environ.get("ADMIN_DEFAULT_USERNAME") or "").strip()
    env_pass = (os.environ.get("ADMIN_DEFAULT_PASSWORD") or "").strip()
    if env_user and env_pass and username == env_user and password == env_pass:
        return True
    return False
