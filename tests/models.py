"""Models used by the end-to-end tests (mirrors the crudman-nestjs example app)."""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, ForeignKey, LargeBinary, Numeric, String, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Country(Base):
    __tablename__ = "countries"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    code: Mapped[str | None] = mapped_column(String(3))
    states: Mapped[list[State]] = relationship(back_populates="country", cascade="all, delete-orphan")


class State(Base):
    __tablename__ = "states"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    country_id: Mapped[int] = mapped_column(ForeignKey("countries.id"))
    country: Mapped[Country] = relationship(back_populates="states")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Plan(enum.Enum):
    free = "free"
    pro = "pro"


class Company(Base):
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    email: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True)
    revenue: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    employees: Mapped[int | None]
    founded_on: Mapped[date | None]
    plan: Mapped[Plan] = mapped_column(SAEnum(Plan), default=Plan.free)
    secret: Mapped[str | None] = mapped_column(String(50))
    tenant_id: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    contacts: Mapped[list[Contact]] = relationship(back_populates="company", cascade="all, delete-orphan")


class Contact(Base):
    __tablename__ = "contacts"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255))
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    company: Mapped[Company] = relationship(back_populates="contacts")
    address_id: Mapped[int | None] = mapped_column(ForeignKey("addresses.id"))
    address: Mapped[Address | None] = relationship()


class Address(Base):
    __tablename__ = "addresses"
    id: Mapped[int] = mapped_column(primary_key=True)
    city: Mapped[str] = mapped_column(String(100))


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(30))
    role: Mapped[str] = mapped_column(String(20), default="user")
    created_at: Mapped[datetime] = mapped_column(default=func.now())


class Post(Base):
    __tablename__ = "posts"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[int | None]
    tenant_id: Mapped[int | None]


class Note(Base):
    __tablename__ = "notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(String(200))
    owner_id: Mapped[int]


class Profile(Base):
    __tablename__ = "profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    avatar: Mapped[str | None] = mapped_column(String(255))
    avatarKey: Mapped[str | None] = mapped_column(String(255))  # noqa: N815 - matches NestJS key/url naming
    avatarUrl: Mapped[str | None] = mapped_column(String(255))  # noqa: N815
    thumbBase64: Mapped[str | None] = mapped_column(Text)  # noqa: N815
    rawBlob: Mapped[bytes | None] = mapped_column(LargeBinary)  # noqa: N815
    rawMime: Mapped[str | None] = mapped_column(String(100))  # noqa: N815
    photos: Mapped[list[str] | None] = mapped_column(JSON)


class Tag(Base):
    __tablename__ = "tags"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))


class UserProfile(Base):
    __tablename__ = "user_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    bio: Mapped[str | None] = mapped_column(String(200))


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(String(200))
