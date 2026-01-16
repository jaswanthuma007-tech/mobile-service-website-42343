import os
import re

from flask import request
from flask.views import MethodView
from flask_smorest import Blueprint, abort

from .. import db
from ..schemas import (
    AboutResponseSchema,
    AdminBookingsResponseSchema,
    BookingRequestSchema,
    BookingResponseSchema,
    BookingServicesResponseSchema,
    BookingUpdateRequestSchema,
    BookingUpdateResponseSchema,
    BrandsResponseSchema,
    ContactResponseSchema,
    ModelsResponseSchema,
    PincodeCheckResponseSchema,
    ServicesResponseSchema,
    SubmitFormRequestSchema,
    SubmitFormResponseSchema,
)

blp = Blueprint("Mobile Service API", "mobile_service_api", url_prefix="/api", description="Mobile Service Website APIs")

_PHONE_INVALID_MESSAGE = "Only numbers are allowed. Please enter a valid 10-digit mobile number."


def _normalize_and_validate_10_digit_phone(value: str) -> str:
    """Normalize and validate a phone number to exactly 10 digits.

    Rules (per requirement):
    - Normalize by stripping all non-digits.
    - After normalization, the phone must be exactly 10 digits.
    - On invalid input, raise a 400 with a fixed user-facing message.

    Returns:
        Normalized 10-digit phone string (digits only).
    """
    raw = (value or "").strip()
    normalized = re.sub(r"\D", "", raw)

    # "Only numbers are allowed" + "valid 10-digit" message is required, even if
    # user entered punctuation/spaces; we normalize then validate length.
    if len(normalized) != 10:
        abort(400, message=_PHONE_INVALID_MESSAGE)

    # Defensive: ensure digits-only (should already be true after regex).
    if not normalized.isdigit():
        abort(400, message=_PHONE_INVALID_MESSAGE)

    return normalized


def _require_admin_api_key(request_obj) -> None:
    """Require admin shared-secret header if ADMIN_API_KEY is configured."""
    admin_key = os.environ.get("ADMIN_API_KEY")
    if not admin_key:
        return
    provided = request_obj.headers.get("X-Admin-Key", "")
    if provided != admin_key:
        from flask_smorest import abort

        abort(401, message="Unauthorized")


def _admin_tokens_from_env() -> set[str]:
    """Return configured admin tokens from ADMIN_TOKENS env var (comma-separated)."""
    raw = os.environ.get("ADMIN_TOKENS", "").strip()
    if not raw:
        return set()
    return {t.strip() for t in raw.split(",") if t.strip()}


def _issue_admin_token(username: str) -> str:
    """Issue an admin token.

    Implementation note: uses a static configured token list if provided; otherwise derives
    a simple token from username + ADMIN_API_KEY (dev-friendly). For production, use JWT.
    """
    tokens = _admin_tokens_from_env()
    if tokens:
        # If tokens are pre-configured, just return the first for simplicity.
        return sorted(tokens)[0]

    # Fallback: deterministic token based on env key; avoids adding new dependencies.
    secret = os.environ.get("ADMIN_API_KEY", "dev-admin-key")
    return f"admin:{username}:{secret}"


def _require_admin_token(request_obj) -> None:
    """Require Bearer token for admin session endpoints if admin auth is enabled.

    Rules:
    - If ADMIN_LOGIN_ENABLED is not set/false and ADMIN_API_KEY is also not set, allow (dev).
    - If ADMIN_LOGIN_ENABLED is true OR ADMIN_API_KEY is set, require:
        Authorization: Bearer <token>
      Tokens allowed:
        - any token in ADMIN_TOKENS (comma-separated), OR
        - token that matches the fallback token format returned by _issue_admin_token for
          the default admin username (or any username, if using the fallback).
    """
    login_enabled = (os.environ.get("ADMIN_LOGIN_ENABLED") or "").strip().lower() in ("1", "true", "yes", "on")
    admin_key = os.environ.get("ADMIN_API_KEY")
    if not login_enabled and not admin_key:
        return

    auth = request_obj.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        from flask_smorest import abort

        abort(401, message="Missing admin token")

    token = auth.split(" ", 1)[1].strip()
    allowed = _admin_tokens_from_env()
    if token in allowed:
        return

    # Accept fallback token pattern for any username (basic).
    # This is only intended for small demos; production should use JWT.
    secret = admin_key or "dev-admin-key"
    if token.endswith(f":{secret}") and token.startswith("admin:"):
        return

    from flask_smorest import abort

    abort(401, message="Invalid admin token")


@blp.route("/services")
class Services(MethodView):
    """Service catalog endpoints."""

    @blp.response(200, ServicesResponseSchema)
    def get(self):
        """Return a list of services shown on the Services section."""
        return {"services": db.list_services()}


@blp.route("/brands")
class Brands(MethodView):
    """Device brand catalog for the booking flow."""

    @blp.response(200, BrandsResponseSchema)
    def get(self):
        """Return available brands for step-1 (Select Brand)."""
        return {"brands": db.list_brands()}


@blp.route("/models")
class Models(MethodView):
    """Device model catalog for the booking flow."""

    @blp.response(200, ModelsResponseSchema)
    def get(self):
        """Return models for step-2 (Select Model).

        Query params:
        - brand: selected brand name
        """
        brand = (request.args.get("brand") or "").strip()
        if not brand:
            abort(400, message="brand query param is required")
        return {"models": db.list_models_for_brand(brand)}


@blp.route("/booking/services")
class BookingServices(MethodView):
    """Repair service options for step-3 (Select Repair Service)."""

    @blp.response(200, BookingServicesResponseSchema)
    def get(self):
        """Return selectable repair services (icons + price hints)."""
        return {"services": db.list_booking_services()}


@blp.route("/about")
class About(MethodView):
    """About content endpoint."""

    @blp.response(200, AboutResponseSchema)
    def get(self):
        """Return content for the About section."""
        content = db.get_site_content(["about_description"])
        return {
            "description": content.get("about_description", ""),
            # Optional extras for frontend; keep stable defaults.
            "highlights": [
                {"label": "Response time", "value": "24h"},
                {"label": "Customer care", "value": "5★"},
                {"label": "Clarity", "value": "100%"},
            ],
            "bullets": [
                "Mobile-first process with a smooth, fast form",
                "Clear updates and realistic timelines",
                "Focus on the right fix (not the most expensive fix)",
            ],
        }


@blp.route("/contact")
class Contact(MethodView):
    """Contact information endpoint."""

    @blp.response(200, ContactResponseSchema)
    def get(self):
        """Return contact info for the Contact section."""
        content = db.get_site_content(["contact_hours", "contact_phone", "contact_email"])
        return {
            "hours": content.get("contact_hours", "Mon–Sat: 9am–7pm • Sun: 11am–4pm"),
            "phone": content.get("contact_phone", "+1 (555) 123-4567"),
            "email": content.get("contact_email", "support@example.com"),
        }


@blp.route("/submit_form")
class SubmitForm(MethodView):
    """Customer request form endpoint."""

    @blp.arguments(SubmitFormRequestSchema)
    @blp.response(201, SubmitFormResponseSchema)
    def post(self, form_data):
        """Store a customer request submission.

        Expects JSON body:
        - name, phone, email, mobile_model, problem

        Returns:
        - id: created request ID
        - message: user-facing message
        """
        new_id = db.create_customer_request(
            name=form_data["name"].strip(),
            phone=form_data["phone"].strip(),
            email=form_data["email"].strip(),
            mobile_model=form_data["mobile_model"].strip(),
            problem=form_data["problem"].strip(),
        )
        return {"id": new_id, "message": "Thanks! We received your request and will contact you shortly."}


@blp.route("/pincode/check")
class PincodeCheck(MethodView):
    """Pincode validation endpoint used by the booking form UI."""

    @blp.response(200, PincodeCheckResponseSchema)
    def get(self):
        """Validate the provided pincode.

        Query params:
        - pincode: 6-digit pincode

        Note: In a real system this would query a serviceability table.
        For now, we accept any 6-digit pincode starting with 1-9.
        """
        pincode = (request.args.get("pincode") or "").strip()
        if len(pincode) == 6 and pincode.isdigit() and not pincode.startswith("0"):
            return {"valid": True, "message": "Great! Service is available in your area."}
        return {"valid": False, "message": "Please enter a valid 6-digit pincode."}


@blp.route("/bookings")
class Bookings(MethodView):
    """Booking form submission endpoint (hero form)."""

    @blp.arguments(BookingRequestSchema)
    @blp.response(201, BookingResponseSchema)
    def post(self, booking_data):
        """Create a booking.

        Expects JSON body:
        - name, phone, pincode

        Phone handling:
        - Phone is normalized by stripping non-digits.
        - Phone must normalize to exactly 10 digits, otherwise HTTP 400 is returned.

        Returns:
        - id: created booking ID
        - message: user-facing message
        """
        normalized_phone = _normalize_and_validate_10_digit_phone(booking_data.get("phone") or "")

        new_id = db.create_booking(
            name=booking_data["name"].strip(),
            phone=normalized_phone,
            pincode=booking_data["pincode"].strip(),
        )
        return {"id": new_id, "message": "Booking received! Our team will contact you shortly."}


@blp.route("/book")
class BookAlias(MethodView):
    """Alias endpoint for create booking (matches requested POST /book)."""

    @blp.arguments(BookingRequestSchema)
    @blp.response(201, BookingResponseSchema)
    def post(self, booking_data):
        """Create a booking (alias for /api/bookings).

        Phone handling:
        - Phone is normalized by stripping non-digits.
        - Phone must normalize to exactly 10 digits, otherwise HTTP 400 is returned.
        """
        normalized_phone = _normalize_and_validate_10_digit_phone(booking_data.get("phone") or "")

        new_id = db.create_booking(
            name=booking_data["name"].strip(),
            phone=normalized_phone,
            pincode=booking_data["pincode"].strip(),
        )
        return {"id": new_id, "message": "Booking received! Our team will contact you shortly."}


@blp.route("/booking/<int:booking_id>")
class BookingUpdate(MethodView):
    """Update booking with brand/model/service selections (same Booking ID)."""

    @blp.arguments(BookingUpdateRequestSchema)
    @blp.response(200, BookingUpdateResponseSchema)
    def put(self, update_payload, booking_id: int):
        """Update booking fields used by the multi-step flow.

        Path params:
        - booking_id

        JSON body (any subset):
        - brand: string
        - model: string
        - service: string (comma-separated; frontend may send joined values)

        Returns:
        - booking: updated booking
        """
        brand = update_payload.get("brand")
        model = update_payload.get("model")
        service = update_payload.get("service")
        updated = db.update_booking_device_selection(
            booking_id=int(booking_id),
            brand=(brand.strip() if isinstance(brand, str) else None),
            model=(model.strip() if isinstance(model, str) else None),
            service=(service.strip() if isinstance(service, str) else None),
        )
        if not updated:
            abort(404, message="Booking not found")
        return {"booking": updated}


@blp.route("/admin/bookings")
class AdminBookings(MethodView):
    """Admin endpoint to list recent bookings."""

    @blp.response(200, AdminBookingsResponseSchema)
    def get(self):
        """List recent bookings (admin).

        Auth:
        - Prefer: Authorization: Bearer <token>
        - Back-compat: X-Admin-Key if ADMIN_API_KEY is configured

        Optional query params:
        - limit: max rows (1..1000)
        """
        # Back-compat: allow the old shared-secret header.
        _require_admin_api_key(request)
        _require_admin_token(request)

        limit = request.args.get("limit", "200")
        try:
            limit_int = int(limit)
        except ValueError:
            limit_int = 200
        return {"bookings": db.list_bookings(limit=limit_int)}
