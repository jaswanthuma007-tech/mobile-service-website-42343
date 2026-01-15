from marshmallow import Schema, fields, validate


class ServiceSchema(Schema):
    id = fields.Int(required=True, metadata={"description": "Service ID"})
    title = fields.Str(required=True, metadata={"description": "Service title"})
    description = fields.Str(required=True, metadata={"description": "Service description"})
    icon = fields.Str(required=False, allow_none=True, metadata={"description": "Optional icon/emoji"})
    price_hint = fields.Str(required=False, allow_none=True, metadata={"description": "Optional pricing hint"})


class ServicesResponseSchema(Schema):
    services = fields.List(fields.Nested(ServiceSchema), required=True, metadata={"description": "List of services"})


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
