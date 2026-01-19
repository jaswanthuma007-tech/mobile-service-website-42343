"""
SQLAlchemy ORM models for the Mobile Service Management System.

This file is intentionally self-contained and does not change the existing Supabase-based
db.py module. It provides Flask-SQLAlchemy models requested by the task.

Important:
- The backend can run with Supabase persistence OR local SQLite persistence.
- Runtime SQLite persistence is implemented in `app/persistence.py` (minimal models + table ensure/seed).
- This file provides a richer ORM model set for a broader "management system" schema and can be used
  later for migrations/admin tooling, but is not currently wired into the Flask app runtime.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates
from flask_sqlalchemy import SQLAlchemy

# Global SQLAlchemy handle. In a typical Flask app you would do:
#   from app.models import db as orm_db
#   orm_db.init_app(app)
orm_db = SQLAlchemy()

_PINCODE_RE = re.compile(r"^[0-9]{6}$")


class TimestampMixin:
    """Shared created_at/updated_at columns."""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class User(orm_db.Model, TimestampMixin):
    """User account model."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    # Relationships
    customer: Mapped[Optional["Customer"]] = relationship(back_populates="user", uselist=False)
    technician: Mapped[Optional["Technician"]] = relationship(back_populates="user", uselist=False)
    notifications: Mapped[list["Notification"]] = relationship(back_populates="user")


class ServiceArea(orm_db.Model, TimestampMixin):
    """Serviceable area, keyed by pincode."""

    __tablename__ = "service_areas"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    pincode: Mapped[str] = mapped_column(String(6), unique=True, nullable=False, index=True)
    city: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    district: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    state: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    # Relationships
    bookings: Mapped[list["Booking"]] = relationship(back_populates="service_area")

    __table_args__ = (
        CheckConstraint("pincode ~ '^[0-9]{6}$'", name="service_areas_pincode_format_chk"),
        Index("ix_service_areas_is_active", "is_active"),
        Index("ix_service_areas_city", "city"),
    )

    @validates("pincode")
    def _validate_pincode_format(self, key: str, value: str) -> str:
        """Validate pincode format."""
        v = (value or "").strip()
        if not _PINCODE_RE.match(v):
            raise ValueError("service_areas.pincode must be exactly 6 digits")
        return v


class Customer(orm_db.Model, TimestampMixin):
    """Customer record, optionally linked to a user account."""

    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), unique=True, nullable=True)

    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    email: Mapped[Optional[str]] = mapped_column(Text, nullable=True, index=True)

    # Relationships
    user: Mapped[Optional[User]] = relationship(back_populates="customer")
    bookings: Mapped[list["Booking"]] = relationship(back_populates="customer")


class Technician(orm_db.Model, TimestampMixin):
    """Technician record, optionally linked to a user account."""

    __tablename__ = "technicians"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), unique=True, nullable=True
    )

    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    skill_level: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    # Relationships
    user: Mapped[Optional[User]] = relationship(back_populates="technician")
    repair_jobs: Mapped[list["RepairJob"]] = relationship(back_populates="technician")

    __table_args__ = (Index("ix_technicians_is_active", "is_active"),)


class Service(orm_db.Model, TimestampMixin):
    """Service catalog entry."""

    __tablename__ = "services"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    base_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    # Relationships
    bookings: Mapped[list["Booking"]] = relationship(back_populates="service")

    __table_args__ = (Index("ix_services_is_active", "is_active"),)


class Booking(orm_db.Model, TimestampMixin):
    """Customer booking for a service.

    Pincode validation rule:
    - bookings.pincode must match service_areas.pincode (enforced by FK).
    - Additionally validated at ORM level via @validates.
    """

    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="RESTRICT"), nullable=False, index=True)

    # FK to service_areas.pincode (natural key)
    pincode: Mapped[str] = mapped_column(ForeignKey("service_areas.pincode", ondelete="RESTRICT"), nullable=False, index=True)

    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    address_line1: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    address_line2: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="Pending", server_default="Pending", index=True)

    # Relationships
    customer: Mapped[Customer] = relationship(back_populates="bookings")
    service: Mapped[Service] = relationship(back_populates="bookings")
    service_area: Mapped[ServiceArea] = relationship(back_populates="bookings", primaryjoin="Booking.pincode==ServiceArea.pincode")

    repair_jobs: Mapped[list["RepairJob"]] = relationship(back_populates="booking", cascade="all, delete-orphan")
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="booking", cascade="all, delete-orphan")
    notifications: Mapped[list["Notification"]] = relationship(back_populates="booking", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("pincode ~ '^[0-9]{6}$'", name="bookings_pincode_format_chk"),
        Index("ix_bookings_created_at", "created_at"),
    )

    @validates("pincode")
    def _validate_booking_pincode(self, key: str, value: str) -> str:
        """Validate booking pincode format.

        Note: serviceability is enforced by FK to service_areas.pincode.
        This validation only ensures format correctness before hitting DB.
        """
        v = (value or "").strip()
        if not _PINCODE_RE.match(v):
            raise ValueError("bookings.pincode must be exactly 6 digits")
        return v


class RepairJob(orm_db.Model, TimestampMixin):
    """Repair job associated with a booking."""

    __tablename__ = "repair_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False, index=True)
    technician_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("technicians.id", ondelete="SET NULL"), nullable=True, index=True
    )

    issue_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    diagnosis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resolution: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(Text, nullable=False, default="Open", server_default="Open", index=True)

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    booking: Mapped[Booking] = relationship(back_populates="repair_jobs")
    technician: Mapped[Optional[Technician]] = relationship(back_populates="repair_jobs")


class Invoice(orm_db.Model, TimestampMixin):
    """Invoice issued for a booking."""

    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False, index=True)

    invoice_number: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)

    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"), server_default="0")
    tax: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"), server_default="0")
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"), server_default="0")

    status: Mapped[str] = mapped_column(Text, nullable=False, default="Draft", server_default="Draft", index=True)

    issued_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    booking: Mapped[Booking] = relationship(back_populates="invoices")
    payments: Mapped[list["Payment"]] = relationship(back_populates="invoice", cascade="all, delete-orphan")


class Payment(orm_db.Model):
    """Payment record linked to an invoice."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True)

    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="Captured", server_default="Captured", index=True)

    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    reference: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    invoice: Mapped[Invoice] = relationship(back_populates="payments")


class Notification(orm_db.Model):
    """Outbound notification (SMS/email/push) related to user and/or booking."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    booking_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("bookings.id", ondelete="CASCADE"), nullable=True, index=True
    )

    channel: Mapped[str] = mapped_column(Text, nullable=False, default="sms", server_default="sms")
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued", server_default="queued", index=True)

    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user: Mapped[Optional[User]] = relationship(back_populates="notifications")
    booking: Mapped[Optional[Booking]] = relationship(back_populates="notifications")
