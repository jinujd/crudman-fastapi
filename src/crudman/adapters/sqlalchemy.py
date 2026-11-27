"""SQLAlchemy 2.0 (async) adapter.

Every list request is built as one ``Select``: filters, keyword search, fixed conditions, ownership and
sorting all go into the same statement, and ``on_before_query`` sees that statement. Keyword search on
relations uses ``EXISTS`` (``any()`` / ``has()``), so rows are never duplicated and counts stay correct.
"""

from __future__ import annotations

import datetime as dt
import decimal
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, Select, String, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.strategy_options import _AbstractLoad

from ..errors import CrudmanError
from ..query import FilterItem, SortItem
from ..schemas import ColumnInfo, columns_of, primary_key_of, relations_of


class FilterValueError(CrudmanError):
    """A query-string value could not be converted to the column type."""

    def __init__(self, field: str, value: Any, expected: str) -> None:
        super().__init__(f"Invalid value {value!r} for '{field}': expected {expected}")
        self.field = field
        self.value = value
        self.expected = expected


_TRUE = {"true", "1", "yes", "on"}
_FALSE = {"false", "0", "no", "off"}


def _is_date_only(text: str) -> bool:
    return len(text.strip()) == 10 and text.count("-") == 2


def cast_value(info: ColumnInfo, raw: Any, *, end_of_day: bool = False) -> Any:
    """Convert a query-string value to the column's Python type."""
    if raw is None:
        return None
    py = info.python_type
    text = str(raw).strip()
    try:
        if info.enum_values is not None:
            enum_class = getattr(info.column.type, "enum_class", None)
            if enum_class is not None:
                return enum_class(text)
            return text
        if py is bool:
            low = text.lower()
            if low in _TRUE:
                return True
            if low in _FALSE:
                return False
            raise ValueError(text)
        if py is int:
            return int(text)
        if py is float:
            return float(text)
        if py is decimal.Decimal:
            return decimal.Decimal(text)
        if py is dt.datetime:
            if _is_date_only(text):
                day = dt.date.fromisoformat(text)
                moment = dt.time.max if end_of_day else dt.time.min
                return dt.datetime.combine(day, moment)
            return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        if py is dt.date:
            return dt.date.fromisoformat(text[:10])
        if py is uuid.UUID:
            return uuid.UUID(text)
    except (ValueError, decimal.InvalidOperation) as exc:
        name = getattr(py, "__name__", str(py))
        raise FilterValueError(info.key, raw, name) from exc
    if isinstance(raw, (int, float)) and py is str:
        return text
    return raw


@dataclass
class ListQuery:
    filters: list[FilterItem]
    sorting: list[SortItem]
    keyword: str | None
    keyword_paths: list[str]
    keyword_case_sensitive: bool
    offset: int | None
    limit: int | None
    relations: list[str]
    where: list[Any]


class SqlAlchemyAdapter:
    """Default ORM adapter."""

    # ── relations ─────────────────────────────────────────────────────────

    def resolve_relations(self, model: Any, spec: Any, required: Iterable[str] = ()) -> list[str]:
        all_rels = list(relations_of(model))
        if spec is None or spec == "*":
            base = all_rels
        elif isinstance(spec, str):
            base = [spec]
        elif isinstance(spec, (list, tuple)):
            base = list(spec)
        elif isinstance(spec, Mapping):
            if spec.get("include") and spec["include"] != "*":
                base = list(spec["include"])
            elif spec.get("exclude"):
                base = [r for r in all_rels if r not in spec["exclude"]]
            else:
                base = all_rels
        else:
            base = []
        out: list[str] = []
        for path in [*base, *required]:
            if path not in out:
                out.append(path)
        return out

    def loader_options(self, model: Any, paths: Sequence[str]) -> list[_AbstractLoad]:
        options: list[_AbstractLoad] = []
        for path in paths:
            current_model = model
            loader: Any = None
            for segment in path.split("."):
                rels = relations_of(current_model)
                if segment not in rels:
                    loader = None
                    break
                attr = getattr(current_model, segment)
                loader = selectinload(attr) if loader is None else loader.selectinload(attr)
                current_model = rels[segment].target
            if loader is not None:
                options.append(loader)
        return options

    # ── expressions ───────────────────────────────────────────────────────

    def filter_clause(self, model: Any, item: FilterItem) -> ColumnElement[bool]:
        infos = {c.key: c for c in columns_of(model)}
        info = infos.get(item.field)
        if info is None:
            raise FilterValueError(item.field, item.value, "a column of this model")
        col = getattr(model, item.field)
        if item.op == "eq":
            return col == cast_value(info, item.value)  # type: ignore[no-any-return]
        if item.op == "like":
            target = col if info.python_type is str else cast(col, String)
            return target.icontains(str(item.value), autoescape=True)
        if item.op == "between":
            start, end = item.value
            return col.between(cast_value(info, start), cast_value(info, end, end_of_day=True))  # type: ignore[no-any-return]
        value = cast_value(info, item.value, end_of_day=item.op == "lte")
        if item.op == "gte":
            return col >= value  # type: ignore[no-any-return]
        if item.op == "lte":
            return col <= value  # type: ignore[no-any-return]
        if item.op == "gt":
            return col > value  # type: ignore[no-any-return]
        return col < value  # type: ignore[no-any-return]

    _SEARCHABLE = (str, int, float, decimal.Decimal, uuid.UUID)

    def keyword_clause(
        self, model: Any, paths: Sequence[str], keyword: str, case_sensitive: bool
    ) -> ColumnElement[bool] | None:
        clauses: list[ColumnElement[bool]] = []
        for path in paths:
            clause = self._keyword_path(model, path.split("."), keyword, case_sensitive)
            if clause is not None:
                clauses.append(clause)
        return or_(*clauses) if clauses else None

    def _keyword_path(
        self, model: Any, segments: list[str], keyword: str, case_sensitive: bool
    ) -> ColumnElement[bool] | None:
        head, rest = segments[0], segments[1:]
        if not rest:
            infos = {c.key: c for c in columns_of(model)}
            info = infos.get(head)
            if info is None or (info.python_type not in self._SEARCHABLE and not info.enum_values):
                return None
            col = getattr(model, head)
            target = col if info.python_type is str else cast(col, String)
            if case_sensitive:
                return target.contains(keyword, autoescape=True)
            return target.icontains(keyword, autoescape=True)
        rels = relations_of(model)
        if head not in rels:
            return None
        inner = self._keyword_path(rels[head].target, rest, keyword, case_sensitive)
        if inner is None:
            return None
        attr = getattr(model, head)
        return attr.any(inner) if rels[head].uselist else attr.has(inner)  # type: ignore[no-any-return]

    def default_sorting(self, model: Any) -> list[SortItem]:
        keys = {c.key for c in columns_of(model)}
        pk = primary_key_of(model)
        for name in ("created_at", "createdAt"):
            if name in keys:
                return [SortItem(name, "DESC")] + ([SortItem(pk, "DESC")] if pk != name else [])
        return [SortItem(pk, "DESC")]

    def order_clauses(self, model: Any, sorting: Sequence[SortItem]) -> list[Any]:
        out: list[Any] = []
        keys = {c.key for c in columns_of(model)}
        for item in sorting:
            if item.field not in keys:
                continue
            col = getattr(model, item.field)
            out.append(col.asc() if item.order == "ASC" else col.desc())
        return out

    # ── reads ─────────────────────────────────────────────────────────────

    def build_list_statement(self, model: Any, q: ListQuery) -> Select[Any]:
        stmt = select(model)
        conditions: list[Any] = list(q.where)
        conditions.extend(self.filter_clause(model, f) for f in q.filters)
        if q.keyword and q.keyword_paths:
            clause = self.keyword_clause(model, q.keyword_paths, q.keyword, q.keyword_case_sensitive)
            if clause is not None:
                conditions.append(clause)
        if conditions:
            stmt = stmt.where(and_(*conditions))
        order = self.order_clauses(model, q.sorting)
        if order:
            stmt = stmt.order_by(*order)
        return stmt.options(*self.loader_options(model, q.relations))

    async def run_list(
        self, session: AsyncSession, stmt: Select[Any], offset: int | None, limit: int | None
    ) -> tuple[list[Any], int]:
        count_stmt = select(func.count()).select_from(
            stmt.order_by(None).limit(None).offset(None).subquery()
        )
        total = int((await session.execute(count_stmt)).scalar_one())
        if offset is not None:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = (await session.execute(stmt)).scalars().unique().all()
        return list(rows), total

    def build_one_statement(
        self, model: Any, field: str, value: Any, relations: Sequence[str], where: Sequence[Any] = ()
    ) -> Select[Any]:
        infos = {c.key: c for c in columns_of(model)}
        info = infos.get(field)
        if info is None:
            raise FilterValueError(field, value, "a column of this model")
        stmt = select(model).where(getattr(model, field) == cast_value(info, value), *where)
        return stmt.options(*self.loader_options(model, relations))

    async def run_one(self, session: AsyncSession, stmt: Select[Any]) -> Any | None:
        return (await session.execute(stmt)).scalars().first()

    # ── writes ────────────────────────────────────────────────────────────

    async def create(self, session: AsyncSession, model: Any, data: Mapping[str, Any]) -> Any:
        obj = model(**data)
        session.add(obj)
        await session.flush()
        return obj

    async def update(self, session: AsyncSession, obj: Any, data: Mapping[str, Any]) -> Any:
        for key, value in data.items():
            setattr(obj, key, value)
        await session.flush()
        return obj

    async def delete(self, session: AsyncSession, obj: Any) -> None:
        await session.delete(obj)
        await session.flush()

    async def reload(self, session: AsyncSession, model: Any, obj: Any, relations: Sequence[str]) -> Any:
        pk = primary_key_of(model)
        ident = getattr(obj, pk)
        # Expire so the select below refreshes server defaults and relations. (populate_existing
        # would reset collections when a nested loader points back at the parent.)
        session.expire(obj)
        stmt = select(model).where(getattr(model, pk) == ident)
        stmt = stmt.options(*self.loader_options(model, relations))
        return await self.run_one(session, stmt)

    async def unique_conflicts(
        self,
        session: AsyncSession,
        model: Any,
        fields: Sequence[str],
        values: Mapping[str, Any],
        condition: str,
        exclude: Any = None,
    ) -> list[str]:
        """Fields whose values already exist. Only fields present in ``values`` are checked."""
        pk = primary_key_of(model)
        pk_col = getattr(model, pk)
        present = [f for f in fields if f in values and values[f] is not None]
        if not present:
            return []

        async def exists(clause: ColumnElement[bool]) -> bool:
            stmt = select(pk_col).where(clause)
            if exclude is not None:
                stmt = stmt.where(pk_col != exclude)
            return (await session.execute(stmt.limit(1))).first() is not None

        if condition == "and":
            if len(present) != len(fields):
                return []
            clause = and_(*(getattr(model, f) == values[f] for f in present))
            return list(present) if await exists(clause) else []
        return [f for f in present if await exists(getattr(model, f) == values[f])]


__all__ = ["FilterValueError", "ListQuery", "SqlAlchemyAdapter", "cast_value"]
