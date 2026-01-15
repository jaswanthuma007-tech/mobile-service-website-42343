import os

from flask import request
from flask.views import MethodView
from flask_smorest import Blueprint

from .. import db
from ..schemas import (
    AboutResponseSchema,
    AdminBookingsResponseSchema,
    BookingRequestSchema,
    BookingResponseSchema,
    ContactResponseSchema,
    PincodeCheckResponseSchema,
    ServicesResponseSchema,
    SubmitFormRequestSchema,
    SubmitFormResponseSchema,
)

blp = Blueprint("Mobile Service API", "mobile_service_api", url_prefix="/api", description="Mobile Service Website APIs")


def _require_admin(request_obj) -> None:
    """Simple shared-secret auth for admin endpoints (optional).

    If ADMIN_API_KEY is set in environment, require header `X-Admin-Key`.
    If not set, admin endpoints are accessible (dev-friendly).
    """
    admin_key = os.environ.get("ADMIN_API_KEY")
    if not admin_key:
        return
    provided = request_obj.headers.get("X-Admin-Key", "")
    if provided != admin_key:
        # flask-smorest will turn this into a 401 JSON error
        from flask_smorest import abort

        abort(401, message="Unauthorized")


@blp.route("/services")
class Services(MethodView):
    """Service catalog endpoints."""

    @blp.response(200, ServicesResponseSchema)
    def get(self):
        """Return a list of services shown on the Services section."""
        return {"services": db.list_services()}


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

        Returns:
        - id: created booking ID
        - message: user-facing message
        """
        new_id = db.create_booking(
            name=booking_data["name"].strip(),
            phone=booking_data["phone"].strip(),
            pincode=booking_data["pincode"].strip(),
        )
        return {"id": new_id, "message": "Booking received! Our team will contact you shortly."}


@blp.route("/admin/bookings")
class AdminBookings(MethodView):
    """Admin endpoint to list recent bookings."""

    @blp.response(200, AdminBookingsResponseSchema)
    def get(self):
        """List recent bookings.

        Optional query params:
        - limit: max rows (1..1000)
        """
        _require_admin(request)
        limit = request.args.get("limit", "200")
        try:
            limit_int = int(limit)
        except ValueError:
            limit_int = 200
        return {"bookings": db.list_bookings(limit=limit_int)}
