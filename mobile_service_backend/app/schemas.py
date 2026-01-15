from marshmallow import Schema, fields, validate


class ServiceSchema(Schema):
    id = fields.Int(required=True, metadata={"description": "Service ID"})
    title = fields.Str(required=True, metadata={"description": "Service title"})
    description = fields.Str(required=True, metadata={"description": "Service description"})
    icon = fields.Str(required=False, allow_none=True, metadata={"description": "Optional icon/emoji"})
    price_hint = fields.Str(required=False, allow_none=True, metadata={"description": "Optional pricing hint"})


class ServicesResponseSchema(Schema):
    services = fields.List(fields.Nested(ServiceSchema), required=True, metadata={"description": "List of services"})


class BookingServiceOptionSchema(Schema):
    id = fields.Int(required=True, metadata={"description": "Service option ID"})
    title = fields.Str(required=True, metadata={"description": "Service title"})
    icon = fields.Str(required=False, allow_none=True, metadata={"description": "Optional icon/emoji"})
    price_hint = fields.Str(required=False, allow_none=True, metadata={"description": "Optional price hint"})


class BookingServicesResponseSchema(Schema):
    services = fields.List(fields.Nested(BookingServiceOptionSchema), required=True, metadata={"description": "Selectable repair services"})


class BrandSchema(Schema):
    id = fields.Int(required=True, metadata={"description": "Brand ID"})
    name = fields.Str(required=True, metadata={"description": "Brand name"})


class BrandsResponseSchema(Schema):
    brands = fields.List(fields.Nested(BrandSchema), required=True, metadata={"description": "Available brands"})


class ModelSchema(Schema):
    id = fields.Int(required=True, metadata={"description": "Model ID"})
    brand = fields.Str(required=True, metadata={"description": "Brand name"})
    name = fields.Str(required=True, metadata={"description": "Model name"})


class ModelsResponseSchema(Schema):
    models = fields.List(fields.Nested(ModelSchema), required=True, metadata={"description": "Available models for the selected brand"})


class AboutResponseSchema(Schema):
    description = fields.Str(required=True, metadata={"description": "About section description"})
    highlights = fields.List(
        fields.Dict(),
        required=False,
        metadata={"description": "Optional highlight stats (label/value)"},
    )
    bullets = fields.List(fields.Str(), required=False, metadata={"description": "Optional about bullet points"})


class ContactResponseSchema(Schema):
    hours = fields.Str(required=True, metadata={"description": "Business hours"})
    phone = fields.Str(required=True, metadata={"description": "Phone number"})
    email = fields.Email(required=True, metadata={"description": "Support email"})


class SubmitFormRequestSchema(Schema):
    name = fields.Str(required=True, validate=validate.Length(min=1), metadata={"description": "Customer name"})
    phone = fields.Str(required=True, validate=validate.Length(min=7), metadata={"description": "Customer phone"})
    email = fields.Email(required=True, metadata={"description": "Customer email"})
    mobile_model = fields.Str(
        required=True,
        validate=validate.Length(min=1),
        metadata={"description": "Mobile device model"},
    )
    problem = fields.Str(
        required=True,
        validate=validate.Length(min=10),
        metadata={"description": "Problem description"},
    )


class SubmitFormResponseSchema(Schema):
    id = fields.Int(required=True, metadata={"description": "Created request ID"})
    message = fields.Str(required=True, metadata={"description": "User-facing success message"})


class PincodeCheckResponseSchema(Schema):
    valid = fields.Bool(required=True, metadata={"description": "Whether the pincode is serviceable"})
    message = fields.Str(required=True, metadata={"description": "User-facing validation message"})


class BookingRequestSchema(Schema):
    name = fields.Str(required=True, validate=validate.Length(min=1), metadata={"description": "Customer name"})
    phone = fields.Str(required=True, validate=validate.Length(min=7), metadata={"description": "Customer phone"})
    pincode = fields.Str(
        required=True,
        validate=validate.Regexp(r"^[0-9]{6}$", error="Pincode must be exactly 6 digits."),
        metadata={"description": "6-digit pincode"},
    )


class BookingResponseSchema(Schema):
    id = fields.Int(required=True, metadata={"description": "Created booking ID"})
    message = fields.Str(required=True, metadata={"description": "User-facing success message"})


class BookingUpdateRequestSchema(Schema):
    brand = fields.Str(required=False, allow_none=True, metadata={"description": "Selected device brand"})
    model = fields.Str(required=False, allow_none=True, metadata={"description": "Selected device model"})
    service = fields.Str(required=False, allow_none=True, metadata={"description": "Selected service(s) as comma-separated string"})


class BookingUpdateResponseSchema(Schema):
    booking = fields.Nested(lambda: BookingSchema(), required=True, metadata={"description": "Updated booking object"})


class BookingSchema(Schema):
    id = fields.Int(required=True, metadata={"description": "Booking ID"})
    name = fields.Str(required=True, metadata={"description": "Customer name"})
    phone = fields.Str(required=True, metadata={"description": "Customer phone"})
    pincode = fields.Str(required=True, metadata={"description": "6-digit pincode"})
    brand = fields.Str(required=False, allow_none=True, metadata={"description": "Selected device brand"})
    model = fields.Str(required=False, allow_none=True, metadata={"description": "Selected device model"})
    service = fields.Str(required=False, allow_none=True, metadata={"description": "Selected service(s) string"})
    status = fields.Str(required=True, metadata={"description": "Repair status (Pending/In Progress/Completed)"})
    notes = fields.Str(required=False, allow_none=True, metadata={"description": "Optional admin notes"})
    created_at = fields.Str(required=True, metadata={"description": "Creation timestamp"})
    updated_at = fields.Str(required=False, allow_none=True, metadata={"description": "Last update timestamp"})


class AdminBookingsResponseSchema(Schema):
    bookings = fields.List(fields.Nested(BookingSchema), required=True, metadata={"description": "Recent bookings"})


class AdminLoginRequestSchema(Schema):
    username = fields.Str(required=True, validate=validate.Length(min=1), metadata={"description": "Admin username"})
    password = fields.Str(required=True, validate=validate.Length(min=1), metadata={"description": "Admin password"})


class AdminLoginResponseSchema(Schema):
    token = fields.Str(required=True, metadata={"description": "Admin session token"})
    message = fields.Str(required=True, metadata={"description": "User-facing success message"})


class AdminUpdateBookingStatusRequestSchema(Schema):
    status = fields.Str(
        required=True,
        validate=validate.OneOf(["Pending", "In Progress", "Completed"]),
        metadata={"description": "New status value"},
    )
    notes = fields.Str(required=False, allow_none=True, metadata={"description": "Optional notes"})


class AdminUpdateBookingStatusResponseSchema(Schema):
    booking = fields.Nested(BookingSchema, required=True, metadata={"description": "Updated booking"})


class TrackStatusResponseSchema(Schema):
    found = fields.Bool(required=True, metadata={"description": "Whether a booking was found"})
    booking = fields.Nested(BookingSchema, required=False, allow_none=True, metadata={"description": "Found booking"})
    message = fields.Str(required=True, metadata={"description": "User-facing message"})
