import re

from flask import request
from flask.views import MethodView
from flask_smorest import Blueprint, abort

from .. import db
from ..schemas import (
    AdminLoginRequestSchema,
    AdminLoginResponseSchema,
    AdminUpdateBookingStatusRequestSchema,
    AdminUpdateBookingStatusResponseSchema,
    TrackStatusResponseSchema,
)

blp = Blueprint(
    "Admin & Tracking API",
    "admin_tracking_api",
    url_prefix="/api",
    description="Admin auth, admin actions, and customer tracking endpoints",
)

_STATUS_ALLOWED = {"Pending", "In Progress", "Completed"}


def _normalize_phone(value: str) -> str:
    """Normalize phone input by removing spaces/dashes while keeping leading +."""
    v = (value or "").strip()
    if not v:
        return ""
    # Keep leading +, strip other non-digits
    if v.startswith("+"):
        return "+" + re.sub(r"\D", "", v[1:])
    return re.sub(r"\D", "", v)


def _admin_tokens_from_env() -> set[str]:
    raw = (request.environ.get("ADMIN_TOKENS") or "").strip()  # type: ignore[attr-defined]
    if not raw:
        return set()
    return {t.strip() for t in raw.split(",") if t.strip()}


def _issue_admin_token(username: str) -> str:
    # NOTE: mirrored logic to routes/api.py without cross-import to keep blueprint modular.
    secret = request.environ.get("ADMIN_API_KEY") or "dev-admin-key"  # type: ignore[attr-defined]
    return f"admin:{username}:{secret}"


def _require_admin_token() -> None:
    login_enabled = (request.environ.get("ADMIN_LOGIN_ENABLED") or "").strip().lower() in ("1", "true", "yes", "on")  # type: ignore[attr-defined]
    admin_key = request.environ.get("ADMIN_API_KEY")  # type: ignore[attr-defined]
    if not login_enabled and not admin_key:
        return

    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        abort(401, message="Missing admin token")

    token = auth.split(" ", 1)[1].strip()
    allowed = _admin_tokens_from_env()
    if token in allowed:
        return

    secret = admin_key or "dev-admin-key"
    if token.endswith(f":{secret}") and token.startswith("admin:"):
        return

    abort(401, message="Invalid admin token")


@blp.route("/admin/login")
class AdminLogin(MethodView):
    """Admin login endpoint."""

    @blp.arguments(AdminLoginRequestSchema)
    @blp.response(200, AdminLoginResponseSchema)
    def post(self, creds):
        """Login admin and return a token.

        If ADMIN_LOGIN_ENABLED is true, this endpoint is used by the frontend admin panel.

        Expects JSON:
        - username
        - password

        Returns:
        - token
        - message
        """
        username = (creds.get("username") or "").strip()
        password = (creds.get("password") or "").strip()
        if not username or not password:
            abort(400, message="Username and password are required.")

        if not db.verify_admin_credentials(username, password):
            abort(401, message="Invalid credentials")

        token = _issue_admin_token(username)
        return {"token": token, "message": "Login successful."}


@blp.route("/admin/bookings/<int:booking_id>/status")
class AdminBookingStatus(MethodView):
    """Admin endpoint to update booking status."""

    @blp.arguments(AdminUpdateBookingStatusRequestSchema)
    @blp.response(200, AdminUpdateBookingStatusResponseSchema)
    def put(self, status_payload, booking_id: int):
        """Update booking status.

        Auth:
        - Authorization: Bearer <token>

        Path params:
        - booking_id

        JSON body:
        - status: Pending | In Progress | Completed
        - notes: optional
        """
        _require_admin_token()

        status = (status_payload.get("status") or "").strip()
        notes = status_payload.get("notes")
        if status not in _STATUS_ALLOWED:
            abort(400, message="Invalid status")

        updated = db.update_booking_status(booking_id=int(booking_id), status=status, notes=notes)
        if not updated:
            abort(404, message="Booking not found")

        return {"booking": updated}


@blp.route("/track")
class TrackStatus(MethodView):
    """Customer tracking endpoint."""

    @blp.response(200, TrackStatusResponseSchema)
    def get(self):
        """Track repair status by booking ID or phone.

        Query params:
        - booking_id: integer (optional)
        - phone: string (optional)

        Behavior:
        - If booking_id provided, returns that booking if exists.
        - Else if phone provided, returns the latest booking for that phone.
        """
        booking_id = (request.args.get("booking_id") or "").strip()
        phone = _normalize_phone(request.args.get("phone") or "")

        if not booking_id and not phone:
            return {"found": False, "booking": None, "message": "Enter booking ID or phone number to track status."}

        booking = None
        if booking_id:
            try:
                booking = db.get_booking_by_id(int(booking_id))
            except ValueError:
                booking = None
        elif phone:
            booking = db.get_latest_booking_by_phone(phone)

        if not booking:
            return {"found": False, "booking": None, "message": "No booking found for the provided details."}

        return {"found": True, "booking": booking, "message": "Booking found."}
