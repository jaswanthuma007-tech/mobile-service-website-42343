import os
import re
import logging

from flask import request
from flask.views import MethodView
from flask_smorest import Blueprint, abort

from .. import db
from ..anti_spam import enforce_booking_anti_spam
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

logger = logging.getLogger(__name__)


def _coerce_to_str(value) -> str:
    """Best-effort conversion of unknown JSON values into a string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _normalize_booking_payload(payload: dict) -> dict:
    """Normalize booking payload keys and value types.

    Accepts various client-side key names and returns a stable internal shape:
      { "name": str, "phone": str, "pincode": str }

    Supported aliases:
      - phone: phone | phoneNumber | phone_number
      - pincode: pincode | pin

    Notes:
      - This function only normalizes/coerces types; strict validation is done elsewhere.
    """
    if not isinstance(payload, dict):
        return {"name": "", "phone": "", "pincode": ""}

    # name
    name = _coerce_to_str(payload.get("name")).strip()

    # phone aliases
    phone_val = payload.get("phone")
    if phone_val is None:
        phone_val = payload.get("phoneNumber")
    if phone_val is None:
        phone_val = payload.get("phone_number")
    phone = _coerce_to_str(phone_val).strip()

    # pincode aliases (allow numbers)
    pincode_val = payload.get("pincode")
    if pincode_val is None:
        pincode_val = payload.get("pin")
    pincode = _coerce_to_str(pincode_val).strip()

    return {"name": name, "phone": phone, "pincode": pincode}


# PUBLIC_INTERFACE
def _safe_get_json_object() -> dict:
    """Safely parse request JSON and return a dict.

    Behavior:
      - Returns {} if body is empty or not JSON (silent=True).
      - If client sends JSON as a string (e.g. "{...}"), attempts to parse it.
      - Never raises raw parsing exceptions to callers; aborts with 415 if JSON is invalid.
    """
    try:
        payload = request.get_json(silent=True)
    except Exception:
        # Defensive: if Flask/json lib throws, return a safe error.
        abort(415, message="Request body must be valid JSON.")

    if payload is None:
        return {}

    if isinstance(payload, str):
        import json

        try:
            parsed = json.loads(payload)
        except Exception:
            abort(415, message="Request body must be valid JSON.")
        if not isinstance(parsed, dict):
            abort(415, message="Request body must be a JSON object.")
        return parsed

    if not isinstance(payload, dict):
        abort(415, message="Request body must be a JSON object.")

    return payload

blp = Blueprint("Mobile Service API", "mobile_service_api", url_prefix="/api", description="Mobile Service Website APIs")

_PHONE_INVALID_MESSAGE = "Only numbers are allowed. Please enter a valid 10-digit mobile number."
_PINCODE_INVALID_MESSAGE = "Please enter a valid 6-digit pincode."
_PINCODE_STRICT_REGEX = re.compile(r"^[0-9]{6}$")


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


def _validate_strict_6_digit_pincode(value: str) -> str:
    """Validate pincode as exactly 6 digits (numeric-only) and return trimmed value.

    Backend enforcement requirement:
    - Must be exactly 6 characters
    - Must be numeric-only (0-9)
    """
    pincode = (value or "").strip()
    if not _PINCODE_STRICT_REGEX.match(pincode):
        abort(400, message=_PINCODE_INVALID_MESSAGE)
    return pincode


def _get_client_ip() -> str:
    """Best-effort client IP extraction for rate limiting.

    Notes:
    - If running behind a reverse proxy and proxy passes X-Forwarded-For, we use the
      first IP in that list.
    - If not present, fall back to request.remote_addr.
    """
    xff = (request.headers.get("X-Forwarded-For") or "").strip()
    if xff:
        # "client, proxy1, proxy2"
        return xff.split(",")[0].strip()
    return (request.remote_addr or "").strip()


def _log_suspicious_user_agent_and_referer() -> None:
    """Log missing/suspicious UA/Referer; do not block legitimate clients."""
    ua = (request.headers.get("User-Agent") or "").strip()
    ref = (request.headers.get("Referer") or "").strip()

    suspicious = False
    reasons: list[str] = []
    if not ua:
        suspicious = True
        reasons.append("missing_user_agent")
    elif ua.lower() in ("python-requests", "curl", "wget"):
        # Some bots set minimal UAs; this is only a log signal.
        suspicious = True
        reasons.append("generic_user_agent")

    if not ref:
        # Many legitimate clients omit Referer; log-only.
        reasons.append("missing_referer")

    if suspicious:
        logger.warning(
            "Booking request has suspicious headers ip=%s reasons=%s ua=%r referer=%r",
            _get_client_ip(),
            ",".join(reasons),
            ua,
            ref,
        )


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


@blp.route("/serviceable_pincodes")
class ServiceablePincodes(MethodView):
    """Serviceability check for a pincode.

    This endpoint is used by the frontend "Check" button to determine whether service
    is available for a specific 6-digit pincode.

    Response shape:
      { "pincode": "<pin>", "serviceable": true|false }
    """

    def get(self):
        """Check whether a pincode is serviceable.

        Query params:
            pin: Required. 6-digit pincode (digits only).

        Returns:
            200: JSON { "pincode": "<pin>", "serviceable": true|false }
            400: If pin is missing/invalid
            500: If Supabase query fails (safe error message; no stack trace leakage)
        """
        pin = (request.args.get("pin") or "").strip()
        if not _PINCODE_STRICT_REGEX.match(pin):
            abort(400, message="pin must be exactly 6 digits")

        try:
            serviceable = bool(db.is_pincode_serviceable(pin))
            return {"pincode": pin, "serviceable": serviceable}
        except Exception:
            # Do not leak internal errors to clients; log server-side only.
            logger.exception("Failed to check pincode serviceability for pin=%s", pin)
            abort(500, message="Unable to check service availability right now. Please try again later.")


@blp.route("/bookings")
class Bookings(MethodView):
    """Booking form submission endpoint.

    IMPORTANT:
    The frontend "Book a Repair" flow may send:
    - `phoneNumber` or `phone_number` instead of `phone`
    - `pincode` as a number
    This endpoint accepts and normalizes these variations.
    """

    # NOTE: We still use BookingRequestSchema for OpenAPI, but we defensively accept
    # alternate client keys to avoid 422/500 issues from payload drift.
    @blp.arguments(BookingRequestSchema, required=False)
    @blp.response(201, BookingResponseSchema)
    def post(self, booking_data):
        """Create a booking.

        Accepts JSON body fields:
        - name: string
        - phone: string (10 digits) OR phoneNumber/phone_number
        - pincode: string OR number (must normalize to strict 6 digits)

        Returns:
        - 201 { id, message }
        - 400 for validation errors (user-facing message)
        - 409/429 for anti-spam blocks
        - 415 for invalid JSON bodies
        """
        _log_suspicious_user_agent_and_referer()

        # If schema parsing didn't run (required=False) or client uses alternate keys,
        # we fall back to safe JSON parsing and normalize ourselves.
        if not isinstance(booking_data, dict):
            booking_data = _safe_get_json_object()

        normalized_payload = _normalize_booking_payload(booking_data)

        # Validate name is a string-ish value with reasonable length.
        name = normalized_payload["name"]
        if not name:
            abort(400, message="name is required.")
        if len(name) > 120:
            abort(400, message="name is too long (max 120 characters).")

        phone_raw = normalized_payload["phone"]
        if not phone_raw:
            abort(400, message="phoneNumber is required.")
        pincode_raw = normalized_payload["pincode"]
        if not pincode_raw:
            abort(400, message="pincode is required.")

        normalized_phone = _normalize_and_validate_10_digit_phone(phone_raw)
        normalized_pincode = _validate_strict_6_digit_pincode(pincode_raw)

        allowed, code, msg = enforce_booking_anti_spam(
            ip=_get_client_ip(),
            name=name,
            phone_normalized_10=normalized_phone,
            pincode_normalized_6=normalized_pincode,
        )
        if not allowed:
            if code == "RATE_LIMITED":
                return {"code": code, "message": msg}, 429
            if code == "DUPLICATE_SUBMISSION":
                return {"code": code, "message": msg}, 409
            # Defensive fallback.
            return {"code": "ANTI_SPAM_BLOCKED", "message": "Request blocked. Please try again later."}, 429

        try:
            new_id = db.create_booking(
                name=name,
                phone=normalized_phone,
                pincode=normalized_pincode,
            )
            return {
                "id": new_id,
                "message": "Booking received! Our team will contact you shortly.",
                "next_step": {"type": "redirect", "url": f"/booking/{new_id}/brand"},
            }
        except Exception:
            logger.exception(
                "create_booking failed ip=%s name_len=%s phone_last2=%s pincode=%s",
                _get_client_ip(),
                len(name),
                normalized_phone[-2:] if normalized_phone else "",
                normalized_pincode,
            )
            abort(500, message="Unable to create booking right now. Please try again later.")


@blp.route("/book")
class BookAlias(MethodView):
    """Alias endpoint for create booking (matches requested POST /book).

    Accepts `phoneNumber`/`phone_number` as well as `phone` for compatibility with clients.
    """

    @blp.arguments(BookingRequestSchema, required=False)
    @blp.response(201, BookingResponseSchema)
    def post(self, booking_data):
        """Create a booking (alias for /api/bookings).

        Payload compatibility:
        - phone OR phoneNumber OR phone_number
        - pincode can be string or number
        """
        _log_suspicious_user_agent_and_referer()

        if not isinstance(booking_data, dict):
            booking_data = _safe_get_json_object()

        normalized_payload = _normalize_booking_payload(booking_data)

        name = normalized_payload["name"]
        if not name:
            abort(400, message="name is required.")
        if len(name) > 120:
            abort(400, message="name is too long (max 120 characters).")

        phone_raw = normalized_payload["phone"]
        if not phone_raw:
            abort(400, message="phoneNumber is required.")
        pincode_raw = normalized_payload["pincode"]
        if not pincode_raw:
            abort(400, message="pincode is required.")

        normalized_phone = _normalize_and_validate_10_digit_phone(phone_raw)
        normalized_pincode = _validate_strict_6_digit_pincode(pincode_raw)

        allowed, code, msg = enforce_booking_anti_spam(
            ip=_get_client_ip(),
            name=name,
            phone_normalized_10=normalized_phone,
            pincode_normalized_6=normalized_pincode,
        )
        if not allowed:
            if code == "RATE_LIMITED":
                return {"code": code, "message": msg}, 429
            if code == "DUPLICATE_SUBMISSION":
                return {"code": code, "message": msg}, 409
            return {"code": "ANTI_SPAM_BLOCKED", "message": "Request blocked. Please try again later."}, 429

        try:
            new_id = db.create_booking(
                name=name,
                phone=normalized_phone,
                pincode=normalized_pincode,
            )
            return {
                "id": new_id,
                "message": "Booking received! Our team will contact you shortly.",
                "next_step": {"type": "redirect", "url": f"/booking/{new_id}/brand"},
            }
        except Exception:
            logger.exception(
                "create_booking (alias) failed ip=%s name_len=%s phone_last2=%s pincode=%s",
                _get_client_ip(),
                len(name),
                normalized_phone[-2:] if normalized_phone else "",
                normalized_pincode,
            )
            abort(500, message="Unable to create booking right now. Please try again later.")


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


@blp.route("/booking/repair")
class BookingRepair(MethodView):
    """Booking repair endpoint (defensive).

    This endpoint is intended to accept the booking repair flow payloads that may vary
    between clients/versions and normalize them into a booking row.

    Key behaviors:
    - Accepts JSON bodies with either flat fields or nested objects.
    - Tolerates stringified JSON in the request body (e.g., body sent as a JSON string).
    - Validates phone (normalizes to 10 digits) and pincode (strict 6 digits).
    - Inserts a booking row and then updates optional brand/model/service fields.
    - Returns safe, user-facing errors (no stack trace leakage).
    """

    def post(self):
        """Create/repair a booking request.

        Returns:
            201: { "id": <booking_id>, "message": "..." }
            400: For validation errors with a user-facing message
            415: If body is not valid JSON
            500: Only for unexpected server issues (safe message)
        """
        # PUBLIC_INTERFACE
        def _is_nonempty_str(v) -> bool:
            """Return True if v is a non-empty string after stripping."""
            return isinstance(v, str) and bool(v.strip())

        def _coerce_to_str(v) -> str:
            """Best-effort convert unknown values to string."""
            if v is None:
                return ""
            if isinstance(v, str):
                return v
            return str(v)

        def _safe_json() -> dict:
            """Parse JSON body safely, tolerating stringified JSON."""
            payload = request.get_json(silent=True)
            if payload is None:
                abort(415, message="Request body must be JSON.")

            # Some clients accidentally send JSON as a string: "{...}"
            if isinstance(payload, str):
                import json

                try:
                    parsed = json.loads(payload)
                except Exception:
                    abort(415, message="Request body must be valid JSON.")
                if not isinstance(parsed, dict):
                    abort(415, message="Request body must be a JSON object.")
                return parsed

            if not isinstance(payload, dict):
                abort(415, message="Request body must be a JSON object.")
            return payload

        def _pick_first(payload: dict, paths: list[list[str]]) -> object | None:
            """Pick the first existing value at one of the given key paths."""
            for path in paths:
                cur: object = payload
                ok = True
                for key in path:
                    if not isinstance(cur, dict) or key not in cur:
                        ok = False
                        break
                    cur = cur.get(key)
                if ok:
                    return cur
            return None

        payload = _safe_json()

        # Extract likely fields from either flat or nested structures.
        # (Do not log or echo full payload; only log field presence.)
        name_val = _pick_first(payload, [["name"], ["customer", "name"], ["customerDetails", "name"]])
        phone_val = _pick_first(
            payload,
            [
                ["phone"],
                ["phoneNumber"],
                ["phone_number"],
                ["mobile"],
                ["customer", "phone"],
                ["customerDetails", "phone"],
            ],
        )
        pincode_val = _pick_first(payload, [["pincode"], ["pin"], ["customer", "pincode"], ["address", "pincode"]])

        # Optional booking selections
        brand_val = _pick_first(payload, [["brand"], ["device", "brand"], ["deviceSelection", "brand"]])
        model_val = _pick_first(payload, [["model"], ["device", "model"], ["deviceSelection", "model"]])
        service_val = _pick_first(payload, [["service"], ["services"], ["repair", "service"], ["repair", "services"]])

        name = _coerce_to_str(name_val).strip()
        phone_raw = _coerce_to_str(phone_val).strip()
        pincode_raw = _coerce_to_str(pincode_val).strip()

        if not name:
            abort(400, message="name is required.")
        if not phone_raw:
            abort(400, message="phone is required.")
        if not pincode_raw:
            abort(400, message="pincode is required.")

        try:
            normalized_phone = _normalize_and_validate_10_digit_phone(phone_raw)
            normalized_pincode = _validate_strict_6_digit_pincode(pincode_raw)
        except Exception:
            # abort() raises an HTTPException; let flask-smorest handle it.
            raise

        # Normalize optional strings.
        brand = _coerce_to_str(brand_val).strip() if _is_nonempty_str(_coerce_to_str(brand_val)) else None
        model = _coerce_to_str(model_val).strip() if _is_nonempty_str(_coerce_to_str(model_val)) else None

        # Services may arrive as list/str; normalize to comma-separated string.
        service: str | None
        if isinstance(service_val, list):
            parts = [str(x).strip() for x in service_val if str(x).strip()]
            service = ", ".join(parts) if parts else None
        else:
            s = _coerce_to_str(service_val).strip()
            service = s if s else None

        logger.info(
            "booking_repair_request received ip=%s has_brand=%s has_model=%s has_service=%s",
            _get_client_ip(),
            bool(brand),
            bool(model),
            bool(service),
        )

        try:
            # Insert base booking record
            booking_id = db.create_booking(name=name, phone=normalized_phone, pincode=normalized_pincode)

            # Apply optional selections if present
            if brand or model or service:
                db.update_booking_device_selection(
                    booking_id=int(booking_id),
                    brand=brand,
                    model=model,
                    service=service,
                )

            return {"id": int(booking_id), "message": "Booking received! Our team will contact you shortly."}, 201
        except Exception:
            # Log server-side with stack trace; do not leak to client.
            logger.exception(
                "booking_repair_request failed ip=%s name_len=%s phone_last2=%s pincode=%s",
                _get_client_ip(),
                len(name),
                normalized_phone[-2:] if normalized_phone else "",
                normalized_pincode,
            )
            abort(500, message="Unable to create booking right now. Please try again later.")


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
