"""Section names come from the table name; paths default to /{section}."""

from __future__ import annotations

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, registry

from crudman.errors import CrudmanConfigError
from crudman.naming import (
    apply_path_style,
    default_path,
    normalize_path,
    resolve_path,
    section_name_for,
    split_words,
    table_name_of,
)


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(primary_key=True)


class UserProfile(Base):
    __tablename__ = "user_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)


class Legacy(Base):
    __table__ = Table("tbl_legacy_orders", Base.metadata, Column("id", Integer, primary_key=True))


_imperative = registry()
_tags_table = Table("tags", MetaData(), Column("id", Integer, primary_key=True), Column("name", String))


class Tag:
    pass


_imperative.map_imperatively(Tag, _tags_table)


class NotAModel:
    pass


# ── table name → section name ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("model", "expected"),
    [(Company, "companies"), (UserProfile, "user_profiles"), (Legacy, "tbl_legacy_orders"), (Tag, "tags")],
)
def test_table_name_of(model: type, expected: str) -> None:
    assert table_name_of(model) == expected


def test_section_defaults_to_table_name() -> None:
    assert section_name_for(Company) == "companies"


def test_explicit_section_wins() -> None:
    assert section_name_for(Company, "orgs") == "orgs"


def test_unmapped_class_needs_explicit_name() -> None:
    with pytest.raises(CrudmanConfigError, match="crud_router\\(Model, 'name'\\)"):
        section_name_for(NotAModel)
    assert section_name_for(NotAModel, "things") == "things"


@pytest.mark.parametrize("bad", ["", "has space", "/slash", "-leading", "dot.ted"])
def test_invalid_section_names(bad: str) -> None:
    with pytest.raises(CrudmanConfigError):
        section_name_for(Company, bad)


# ── path styles ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("name", "words"),
    [
        ("user_profiles", ["user", "profiles"]),
        ("user-profiles", ["user", "profiles"]),
        ("userProfiles", ["user", "profiles"]),
        ("UserProfiles", ["user", "profiles"]),
        ("HTTPLogs", ["http", "logs"]),
        ("companies", ["companies"]),
    ],
)
def test_split_words(name: str, words: list[str]) -> None:
    assert split_words(name) == words


@pytest.mark.parametrize(
    ("style", "expected"),
    [
        (None, "user_profiles"),
        ("as_is", "user_profiles"),
        ("kebab", "user-profiles"),
        ("snake", "user_profiles"),
        ("camel", "userProfiles"),
        ("pascal", "UserProfiles"),
    ],
)
def test_apply_path_style(style: str | None, expected: str) -> None:
    assert apply_path_style("user_profiles", style) == expected  # type: ignore[arg-type]


def test_unknown_path_style() -> None:
    with pytest.raises(CrudmanConfigError):
        apply_path_style("x", "screaming")  # type: ignore[arg-type]


# ── paths ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"), [("orgs", "/orgs"), ("/orgs/", "/orgs"), ("", ""), ("/", ""), ("/a/b", "/a/b")]
)
def test_normalize_path(raw: str, expected: str) -> None:
    assert normalize_path(raw) == expected


def test_default_path_is_section() -> None:
    assert default_path("companies") == "/companies"
    assert default_path("user_profiles", "kebab") == "/user-profiles"
    assert default_path("companies", route_prefix="/api/") == "/api/companies"


def test_resolve_path_variants() -> None:
    assert resolve_path("companies") == "/companies"
    assert resolve_path("companies", path="/orgs") == "/orgs"
    assert resolve_path("companies", path="") == ""
    assert resolve_path("companies", path="", route_prefix="/api") == "/api"
    assert resolve_path("user_profiles", style="kebab", route_prefix="api") == "/api/user-profiles"
