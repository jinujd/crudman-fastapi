"""Section names and URL paths.

``crud_router(Company)`` needs a section name and a path without being told either:

* section name: the model's table name (``Company.__tablename__ == "companies"`` → ``"companies"``)
* path:         ``"/" + section``, optionally restyled with ``path_style``

The section name is what you use in ``@crud.list("companies")`` and ``call_action("companies", ...)``;
``path_style`` only changes the URL.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from .errors import CrudmanConfigError

PathStyle = Literal["as_is", "kebab", "snake", "camel", "pascal"]
PATH_STYLES: tuple[str, ...] = ("as_is", "kebab", "snake", "camel", "pascal")

_SECTION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]*$")


def table_name_of(model: Any) -> str:
    """The table name of a SQLAlchemy (or SQLModel) mapped class.

    Uses the mapper's local table, so it works for ``__tablename__``, ``__table__`` and imperative
    mappings. Raises :class:`CrudmanConfigError` for anything that is not a mapped class.
    """
    try:
        from sqlalchemy import inspect as sa_inspect
        from sqlalchemy.exc import NoInspectionAvailable
    except ImportError as exc:  # pragma: no cover - sqlalchemy is a hard dependency
        raise CrudmanConfigError("SQLAlchemy is required to derive section names") from exc

    try:
        mapper = sa_inspect(model)
    except NoInspectionAvailable:
        mapper = None
    table = getattr(mapper, "local_table", None)
    name = getattr(table, "name", None)
    if not name:
        name = getattr(model, "__tablename__", None)
    if not name or not isinstance(name, str):
        label = getattr(model, "__name__", repr(model))
        raise CrudmanConfigError(
            f"{label} is not a mapped SQLAlchemy model, so crudman cannot derive a section name. "
            "Pass the section name explicitly: crud_router(Model, 'name')."
        )
    return name


def section_name_for(model: Any, section: str | None = None) -> str:
    """The explicit ``section`` if given, otherwise the model's table name."""
    name = section if section is not None else table_name_of(model)
    validate_section_name(name)
    return name


def validate_section_name(name: str) -> None:
    if not isinstance(name, str) or not _SECTION_RE.match(name):
        raise CrudmanConfigError(
            f"Invalid section name {name!r}: use letters, digits, '_' or '-', "
            "starting with a letter or digit."
        )


def split_words(name: str) -> list[str]:
    """Split a name into lower-case words.

    ``user_profiles`` / ``user-profiles`` / ``userProfiles`` / ``UserProfiles`` → ``['user', 'profiles']``.
    """
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", spaced)
    return [w.lower() for w in re.split(r"[\s_\-]+", spaced) if w]


def apply_path_style(name: str, style: PathStyle | None = None) -> str:
    """Restyle a section name for use in a URL."""
    if style is None or style == "as_is":
        return name
    if style not in PATH_STYLES:
        raise CrudmanConfigError(f"Unknown path_style {style!r}. Use one of {', '.join(PATH_STYLES)}.")
    words = split_words(name)
    if not words:
        return name
    if style == "kebab":
        return "-".join(words)
    if style == "snake":
        return "_".join(words)
    if style == "camel":
        return words[0] + "".join(w.capitalize() for w in words[1:])
    return "".join(w.capitalize() for w in words)  # pascal


def normalize_path(path: str) -> str:
    """``"orgs"`` → ``"/orgs"``, ``"/orgs/"`` → ``"/orgs"``, ``""`` and ``"/"`` → ``""``."""
    stripped = path.strip().strip("/")
    return f"/{stripped}" if stripped else ""


def default_path(section: str, style: PathStyle | None = None, route_prefix: str | None = None) -> str:
    """Path a section is mounted at when ``path=`` is not given."""
    base = normalize_path(apply_path_style(section, style))
    prefix = normalize_path(route_prefix or "")
    return f"{prefix}{base}"


def resolve_path(
    section: str,
    path: str | None = None,
    style: PathStyle | None = None,
    route_prefix: str | None = None,
) -> str:
    """``path=None`` → default path; ``path=""`` → no section segment; anything else is used as given."""
    if path is None:
        return default_path(section, style, route_prefix)
    prefix = normalize_path(route_prefix or "")
    return f"{prefix}{normalize_path(path)}"


__all__ = [
    "PATH_STYLES",
    "PathStyle",
    "apply_path_style",
    "default_path",
    "normalize_path",
    "resolve_path",
    "section_name_for",
    "split_words",
    "table_name_of",
    "validate_section_name",
]
