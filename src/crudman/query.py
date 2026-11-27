"""Query-string parsing for list endpoints.

Port of ``query-utils.ts`` from crudman-nestjs. The wire format is the same, so front-ends written
for the NestJS version work unchanged:

* pagination: ``page``, ``perPage`` (alias ``per_page``), ``paginate=false|0|no``, ``perPage=0``
* sorting:    ``sort.<field>=asc|desc`` (repeatable)
* filters:    ``field=value``, ``field.like``, ``field.min``, ``field.max``, ``field.gt``, ``field.lt``,
              ``field.between=a,b``
* keyword:    ``keyword=...``

Differences from the NestJS version, on purpose:

* Field names are matched against the whitelist in either camelCase or snake_case, so
  ``sort.createdAt`` reaches a ``created_at`` column. The whitelist spelling is what is returned.
* Range operators keep non-numeric values (for example ISO dates) instead of silently dropping them.
* Reserved parameters (page, perPage, paginate, keyword, sort.*, format, x-content-type) are never
  treated as filters, even when no whitelist is given.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

SortOrder = Literal["ASC", "DESC"]
FilterOp = Literal["eq", "like", "gte", "lte", "gt", "lt", "between"]

_DISABLE_VALUES = {"false", "0", "no"}


# ── naming helpers ────────────────────────────────────────────────────────────


def to_camel(name: str) -> str:
    """``per_page`` / ``per-page`` → ``perPage``. Already-camel names are unchanged."""
    return re.sub(r"[_-](\w)", lambda m: m.group(1).upper(), name)


def to_snake(name: str) -> str:
    """``perPage`` / ``per-page`` → ``per_page``. Already-snake names are unchanged."""
    name = name.replace("-", "_")
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    return name.lower()


def _spellings(name: str) -> tuple[str, ...]:
    """Every spelling a client may use for ``name``: as given, camelCase and snake_case."""
    out: list[str] = []
    for candidate in (name, to_camel(name), to_snake(name)):
        if candidate not in out:
            out.append(candidate)
    return tuple(out)


def _get(query: Mapping[str, Any], name: str) -> Any:
    """Read ``name`` from the query in any accepted spelling; ``None`` when absent."""
    for key in _spellings(name):
        if key in query:
            return query[key]
    return None


def resolve_field(name: str, whitelist: Iterable[str] | None) -> str | None:
    """Return the whitelisted spelling of ``name``, or ``None`` if it is not allowed.

    An empty or missing whitelist allows any field (NestJS behaviour); the adapter always passes the
    model's columns, so in practice this is only reached in tests and custom adapters.
    """
    allowed = list(whitelist or [])
    if not allowed:
        return name
    for candidate in _spellings(name):
        if candidate in allowed:
            return candidate
    snake = to_snake(name)
    for item in allowed:
        if to_snake(item) == snake:
            return item
    return None


# ── configuration objects ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class QueryParamNames:
    """Names of the list query parameters. Override per action with ``query_param_names``."""

    page: str = "page"
    per_page: str = "perPage"
    paginate: str = "paginate"
    sort_prefix: str = "sort."
    keyword: str = "keyword"
    between_op: str = "between"
    min_op: str = "min"
    max_op: str = "max"
    gt_op: str = "gt"
    lt_op: str = "lt"
    like_op: str = "like"

    @classmethod
    def from_mapping(cls, data: Mapping[str, str] | None) -> QueryParamNames:
        """Build from a dict that may use snake_case or camelCase keys (``perPage`` or ``per_page``)."""
        if not data:
            return cls()
        known = {f for f in cls.__dataclass_fields__}
        kwargs: dict[str, str] = {}
        for key, value in data.items():
            snake = to_snake(key)
            if snake not in known:
                raise ValueError(f"Unknown query param name '{key}'. Known: {sorted(known)}")
            kwargs[snake] = value
        return cls(**kwargs)

    def reserved(self) -> set[str]:
        """Parameter names that are never filters."""
        names = {self.page, self.per_page, self.paginate, self.keyword, "format", "x-content-type"}
        out: set[str] = set()
        for name in names:
            out.update(_spellings(name))
        return out


@dataclass(frozen=True)
class PaginationOptions:
    """Per-action pagination behaviour (``pagination=`` in a section)."""

    is_pagination_enabled: bool = True
    is_disable_allowed: bool = False
    is_default_enabled: bool = True
    max_per_page: int | None = 100
    default_per_page: int = 30


# ── pagination ────────────────────────────────────────────────────────────────


@dataclass
class PaginationInfo:
    page: int
    per_page: int
    total_items_count: int = 0
    total_pages_count: int = 0
    is_having_next_page: bool = False
    is_having_previous_page: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Wire format (camelCase keys, identical to crudman-nestjs)."""
        return {
            "page": self.page,
            "perPage": self.per_page,
            "totalItemsCount": self.total_items_count,
            "totalPagesCount": self.total_pages_count,
            "isHavingNextPage": self.is_having_next_page,
            "isHavingPreviousPage": self.is_having_previous_page,
        }


@dataclass
class PaginationResult:
    info: PaginationInfo
    disabled: bool
    offset: int | None = None
    limit: int | None = None


def _to_int(value: Any, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def parse_pagination(
    query: Mapping[str, Any] | None,
    names: QueryParamNames | None = None,
    options: PaginationOptions | None = None,
) -> PaginationResult:
    """Read page / perPage / paginate from the query string."""
    query = query or {}
    names = names or QueryParamNames()
    options = options or PaginationOptions()

    raw_page = _get(query, names.page)
    raw_per_page = _get(query, names.per_page)
    raw_paginate = _get(query, names.paginate)

    page = max(1, _to_int(raw_page, 1) or 1)
    # Same as NestJS: Math.max(1, parseInt(perPage) || default)
    per_page = max(1, _to_int(raw_per_page, options.default_per_page) or options.default_per_page)
    if options.max_per_page and per_page > options.max_per_page:
        per_page = options.max_per_page

    disabled = False
    asked_to_disable = (
        str(raw_paginate).strip().lower() in _DISABLE_VALUES if raw_paginate is not None else False
    ) or (raw_per_page is not None and str(raw_per_page).strip() == "0")
    if options.is_disable_allowed and asked_to_disable:
        disabled = True
    if not options.is_pagination_enabled:
        disabled = True
    if not options.is_default_enabled and raw_page is None and raw_per_page is None:
        disabled = True

    info = PaginationInfo(page=page, per_page=per_page, is_having_previous_page=page > 1)
    if disabled:
        return PaginationResult(info=info, disabled=True)
    return PaginationResult(info=info, disabled=False, offset=(page - 1) * per_page, limit=per_page)


def finalize_pagination(result: PaginationResult, total: int, item_count: int) -> PaginationInfo:
    """Fill totals once the query has run. Mirrors the NestJS adapter."""
    info = result.info
    if result.disabled:
        info.page = 1
        info.per_page = item_count
        info.total_items_count = total
        info.total_pages_count = 1
        info.is_having_next_page = False
        info.is_having_previous_page = False
        return info
    limit = result.limit or 0
    pages = math.ceil(total / limit) if limit else 0
    info.total_items_count = total
    info.total_pages_count = pages
    info.is_having_next_page = info.page < pages if limit else False
    return info


# ── sorting ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SortItem:
    field: str
    order: SortOrder

    def to_dict(self) -> dict[str, Any]:
        return {"field": self.field, "order": self.order}


def parse_sorting(
    query: Mapping[str, Any] | None,
    whitelist: Iterable[str] | None = None,
    sort_prefix: str = "sort.",
) -> list[SortItem]:
    """``sort.<field>=asc|desc``. Anything other than ``asc`` (including empty) means DESC."""
    out: list[SortItem] = []
    seen: set[str] = set()
    allowed = list(whitelist or [])
    for key, value in (query or {}).items():
        if not key.startswith(sort_prefix):
            continue
        name = key[len(sort_prefix):]
        if not name:
            continue
        resolved = resolve_field(name, allowed)
        if resolved is None or resolved in seen:
            continue
        order: SortOrder = "ASC" if str(value or "").strip().lower() == "asc" else "DESC"
        out.append(SortItem(field=resolved, order=order))
        seen.add(resolved)
    return out


# ── filters ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FilterItem:
    field: str
    op: FilterOp
    value: Any
    param: str

    def to_dict(self) -> dict[str, Any]:
        return {"field": self.field, "op": self.op, "value": self.value, "param": self.param}


def _coerce_number(value: str) -> Any:
    """``"10"`` → 10, ``"2.5"`` → 2.5, anything else unchanged (e.g. ISO dates)."""
    text = value.strip()
    try:
        return int(text)
    except ValueError:
        pass
    try:
        number = float(text)
    except ValueError:
        return value
    return value if math.isnan(number) or math.isinf(number) else number


def parse_filters(
    query: Mapping[str, Any] | None,
    whitelist: Iterable[str] | None = None,
    names: QueryParamNames | None = None,
) -> list[FilterItem]:
    """Turn ``field``/``field.<op>`` parameters into filter items. Unknown operators are ignored."""
    names = names or QueryParamNames()
    reserved = names.reserved()
    allowed = list(whitelist or [])
    range_ops: dict[str, FilterOp] = {
        names.min_op: "gte",
        names.max_op: "lte",
        names.gt_op: "gt",
        names.lt_op: "lt",
    }
    out: list[FilterItem] = []
    for key, raw in (query or {}).items():
        if raw is None or str(raw) == "":
            continue
        if key in reserved or key.startswith(names.sort_prefix):
            continue
        name, _, op = key.partition(".")
        if not name:
            continue
        field_name = resolve_field(name, allowed)
        if field_name is None:
            continue
        value = str(raw)
        if not op:
            out.append(FilterItem(field_name, "eq", value, name))
        elif op in range_ops:
            out.append(FilterItem(field_name, range_ops[op], _coerce_number(value), key))
        elif op == names.between_op:
            start, _, end = value.partition(",")
            out.append(FilterItem(field_name, "between", [start.strip(), end.strip()], key))
        elif op == names.like_op:
            out.append(FilterItem(field_name, "like", value, key))
    return out


# ── keyword ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class KeywordOptions:
    is_enabled: bool = True
    is_case_sensitive: bool = False
    min_length: int = 2
    searchable_fields: tuple[str, ...] = field(default_factory=tuple)
    max_relation_depth: int = 1


def parse_keyword(
    query: Mapping[str, Any] | None,
    names: QueryParamNames | None = None,
    options: KeywordOptions | None = None,
) -> str | None:
    """The trimmed keyword, or ``None`` when absent, disabled or shorter than ``min_length``."""
    names = names or QueryParamNames()
    options = options or KeywordOptions()
    if not options.is_enabled:
        return None
    raw = _get(query or {}, names.keyword)
    if raw is None:
        return None
    keyword = str(raw).strip()
    if not keyword or len(keyword) < options.min_length:
        return None
    return keyword


def keyword_paths(options: KeywordOptions, columns: Iterable[str]) -> list[str]:
    """Searchable dot paths after applying depth limits. Defaults to all root columns."""
    paths = list(options.searchable_fields) or list(columns)
    out: list[str] = []
    for path in paths:
        segments = path.split(".")
        if not segments or len(segments) > 3:
            continue
        if len(segments) - 1 > options.max_relation_depth:
            continue
        out.append(path)
    return out


__all__ = [
    "FilterItem",
    "KeywordOptions",
    "PaginationInfo",
    "PaginationOptions",
    "PaginationResult",
    "QueryParamNames",
    "SortItem",
    "finalize_pagination",
    "keyword_paths",
    "parse_filters",
    "parse_keyword",
    "parse_pagination",
    "parse_sorting",
    "resolve_field",
    "to_camel",
    "to_snake",
]
