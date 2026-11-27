"""Model introspection, validation rules and serialization.

Validation works in two steps, like crudman-nestjs:

1. Generate a **rule dict** from the SQLAlchemy model (fastest-validator style), e.g.
   ``{"name": {"type": "string", "max": 150, "min": 1}, "email": {"type": "string", "optional": True}}``.
2. ``get_final_validation_rules`` may edit that dict (or return a Pydantic model); the result is turned
   into a Pydantic model and the body is validated with it.
"""

from __future__ import annotations

import base64
import datetime as dt
import decimal
import enum
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, create_model
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Mapper
from sqlalchemy.sql import sqltypes

from .query import to_camel

AUTO_TIMESTAMP_NAMES = {
    "created_at", "updated_at", "modified_at", "deleted_at",
    "createdAt", "updatedAt", "modifiedAt", "deletedAt",
}

# ── introspection ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ColumnInfo:
    key: str
    column: Any
    python_type: Any
    nullable: bool
    has_default: bool
    is_pk: bool
    autoincrement: bool
    length: int | None
    enum_values: tuple[Any, ...] | None
    is_auto_timestamp: bool


@dataclass(frozen=True)
class RelationInfo:
    key: str
    target: Any
    uselist: bool


def mapper_of(model: Any) -> Mapper[Any]:
    return sa_inspect(model)  # type: ignore[no-any-return]


def _python_type(col: Any) -> Any:
    # JSON columns hold any JSON value (object, list, scalar). SQLAlchemy reports their python_type
    # differently across versions (dict in 2.0, object in 2.1), so treat them explicitly as "any".
    if isinstance(col.type, sqltypes.JSON):
        return Any
    try:
        return col.type.python_type
    except (NotImplementedError, AttributeError):
        return Any


def columns_of(model: Any) -> list[ColumnInfo]:
    mapper = mapper_of(model)
    pk_cols = set(mapper.primary_key)
    out: list[ColumnInfo] = []
    for prop in mapper.column_attrs:
        if len(prop.columns) != 1:
            continue
        col = prop.columns[0]
        py = _python_type(col)
        enum_values: tuple[Any, ...] | None = None
        enums = getattr(col.type, "enums", None)
        if enums:
            enum_class = getattr(col.type, "enum_class", None)
            enum_values = tuple(e.value for e in enum_class) if enum_class else tuple(enums)
        is_pk = col in pk_cols
        autoinc = bool(
            is_pk and col.autoincrement in (True, "auto") and py is int and len(pk_cols) == 1
        )
        out.append(
            ColumnInfo(
                key=prop.key,
                column=col,
                python_type=py,
                nullable=bool(col.nullable),
                has_default=col.default is not None or col.server_default is not None,
                is_pk=is_pk,
                autoincrement=autoinc,
                length=getattr(col.type, "length", None),
                enum_values=enum_values,
                is_auto_timestamp=prop.key in AUTO_TIMESTAMP_NAMES
                or col.onupdate is not None
                or col.server_onupdate is not None,
            )
        )
    return out


def column_keys(model: Any) -> list[str]:
    return [c.key for c in columns_of(model)]


def relations_of(model: Any) -> dict[str, RelationInfo]:
    mapper = mapper_of(model)
    return {
        rel.key: RelationInfo(key=rel.key, target=rel.mapper.class_, uselist=bool(rel.uselist))
        for rel in mapper.relationships
    }


def primary_key_of(model: Any) -> str:
    mapper = mapper_of(model)
    pk = mapper.primary_key[0]
    for prop in mapper.column_attrs:
        if pk in prop.columns:
            return str(prop.key)
    return str(pk.key)


def select_attributes(spec: Any, keys: Iterable[str]) -> list[str]:
    """Apply ``"*"`` / list / ``{"include": [...], "exclude": [...]}`` to ``keys``."""
    all_keys = list(keys)
    if spec is None or spec == "*":
        return all_keys
    if isinstance(spec, (list, tuple)):
        return [k for k in all_keys if k in spec]
    if isinstance(spec, Mapping):
        selected = all_keys
        include = spec.get("include")
        if include and include != "*":
            selected = [k for k in selected if k in include]
        exclude = spec.get("exclude")
        if exclude:
            selected = [k for k in selected if k not in exclude]
        return selected
    return all_keys


# ── rule generation ───────────────────────────────────────────────────────────


def _rule_for(info: ColumnInfo) -> dict[str, Any]:
    py = info.python_type
    rule: dict[str, Any]
    if info.enum_values:
        rule = {"type": "enum", "values": list(info.enum_values)}
    elif py is bool:
        rule = {"type": "boolean"}
    elif py is int:
        rule = {"type": "number", "integer": True}
    elif py in (float, decimal.Decimal):
        rule = {"type": "number"}
    elif py is dt.datetime:
        rule = {"type": "date"}
    elif py is dt.date:
        rule = {"type": "date", "dateOnly": True}
    elif py is dt.time:
        rule = {"type": "time"}
    elif py is uuid.UUID:
        rule = {"type": "uuid"}
    elif py is str:
        rule = {"type": "string"}
        if info.length:
            rule["max"] = int(info.length)
    elif py is bytes:
        rule = {"type": "any"}
    elif py in (dict,):
        rule = {"type": "object"}
    elif py in (list,):
        rule = {"type": "array"}
    else:
        rule = {"type": "any"}
    return rule


def generate_rules(model: Any, is_update: bool, write_attributes: Any = "*") -> dict[str, Any]:
    """Validation rules for create (``is_update=False``) or update, generated from the model."""
    rules: dict[str, Any] = {}
    infos = columns_of(model)
    allowed = set(select_attributes(write_attributes, [c.key for c in infos]))
    for info in infos:
        if info.key not in allowed:
            continue
        if info.is_auto_timestamp:
            continue
        if info.is_pk and (is_update or info.autoincrement or info.has_default):
            continue
        rule = _rule_for(info)
        required = not info.nullable and not info.has_default and not is_update
        rule["optional"] = not required
        if info.nullable:
            rule["nullable"] = True
        if required and rule["type"] == "string":
            rule["min"] = 1
        rules[info.key] = rule
    return rules


# ── rule dict → Pydantic ──────────────────────────────────────────────────────

_EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
_URL = r"^https?://\S+$"
_UUID = r"^[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}$"


def _type_for_rule(rule: Mapping[str, Any]) -> Any:
    kind = rule.get("type", "string")
    if kind in ("string", "email", "url", "uuid"):
        pattern = rule.get("pattern")
        if kind == "email":
            pattern = _EMAIL
        elif kind == "url":
            pattern = _URL
        elif kind == "uuid":
            pattern = _UUID
        min_len = rule.get("min")
        if rule.get("empty") is False and not min_len:
            min_len = 1
        return Annotated[
            str,
            StringConstraints(
                min_length=min_len, max_length=rule.get("max"),
                pattern=getattr(pattern, "pattern", pattern),
                strip_whitespace=bool(rule.get("trim")),
            ),
        ]
    if kind == "number":
        base: Any = int if rule.get("integer") else float
        return Annotated[
            base,
            Field(
                ge=rule.get("min"), le=rule.get("max"),
                gt=0 if rule.get("positive") else None, lt=0 if rule.get("negative") else None,
            ),
        ]
    if kind == "boolean":
        return bool
    if kind == "date":
        return dt.date if rule.get("dateOnly") else dt.datetime
    if kind == "time":
        return dt.time
    if kind == "enum":
        values = tuple(rule.get("values") or ())
        return Literal[values] if values else Any
    if kind == "array":
        return Annotated[list[Any], Field(min_length=rule.get("min"), max_length=rule.get("max"))]
    if kind == "object":
        return dict[str, Any]
    return Any


def rules_to_model(name: str, rules: Mapping[str, Any], *, forbid_extra: bool) -> type[BaseModel]:
    """Build a Pydantic model from a fastest-validator style rule dict."""
    fields: dict[str, Any] = {}
    for field_name, raw in rules.items():
        if field_name.startswith("$$"):
            continue
        rule: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {"type": str(raw)}
        typ = _type_for_rule(rule)
        if rule.get("nullable"):
            typ = typ | None
        if rule.get("optional"):
            fields[field_name] = (typ, None)  # may be omitted; explicit null still checked
        else:
            fields[field_name] = (typ, ...)
    config = ConfigDict(extra="forbid" if forbid_extra else "ignore")
    return create_model(name, __config__=config, **fields)


_ERROR_TYPES = {
    "missing": "required",
    "extra_forbidden": "forbidden",
    "string_too_short": "stringMin",
    "string_too_long": "stringMax",
    "string_pattern_mismatch": "stringPattern",
    "greater_than_equal": "numberMin",
    "less_than_equal": "numberMax",
    "greater_than": "numberPositive",
    "less_than": "numberNegative",
    "literal_error": "enumValue",
    "too_short": "arrayMin",
    "too_long": "arrayMax",
}


def _error_type(kind: str) -> str:
    if kind in _ERROR_TYPES:
        return _ERROR_TYPES[kind]
    if kind.startswith(("int", "float", "decimal")):
        return "number"
    if kind.startswith("bool"):
        return "boolean"
    if kind.startswith(("datetime", "date", "time")):
        return "date"
    if kind.startswith("string"):
        return "string"
    return kind


def validation_errors(exc: ValidationError) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for err in exc.errors():
        loc = [str(p) for p in err.get("loc", ())]
        field = ".".join(loc) if loc else ""
        kind = _error_type(str(err.get("type", "")))
        if kind == "required":
            message = f"The '{field}' field is required."
        elif kind == "forbidden":
            message = f"The '{field}' field is not allowed."
        else:
            message = f"The '{field}' field: {err.get('msg', 'is invalid')}."
        out.append({"type": kind, "field": field, "message": message})
    return out


class PydanticValidator:
    """Default validator adapter."""

    def generate_rules(self, model: Any, is_update: bool, write_attributes: Any) -> dict[str, Any]:
        return generate_rules(model, is_update, write_attributes)

    def build(self, name: str, rules_or_model: Any, is_update: bool) -> type[BaseModel]:
        if isinstance(rules_or_model, type) and issubclass(rules_or_model, BaseModel):
            return rules_or_model
        return rules_to_model(name, rules_or_model, forbid_extra=not is_update)

    def validate(self, schema: type[BaseModel], data: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        try:
            instance = schema.model_validate(dict(data))
        except ValidationError as exc:
            return {}, validation_errors(exc)
        return instance.model_dump(exclude_unset=True), []


# ── serialization ─────────────────────────────────────────────────────────────


def _plain(value: Any) -> Any:
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if isinstance(value, enum.Enum):
        return value.value
    return value


def serialize(
    obj: Any,
    attributes: Any = "*",
    *,
    alias: str | None = None,
    depth: int = 0,
    max_depth: int = 3,
    _seen: set[int] | None = None,
) -> dict[str, Any] | None:
    """ORM object → dict. Only loaded attributes are read, so async lazy loads never happen."""
    if obj is None:
        return None
    seen = set(_seen or ())
    seen.add(id(obj))
    state = sa_inspect(obj)
    unloaded = state.unloaded
    mapper = state.mapper
    keys = [p.key for p in mapper.column_attrs if p.key not in unloaded]
    if depth == 0:
        keys = select_attributes(attributes, keys)
    out: dict[str, Any] = {}
    for key in keys:
        out[_alias(key, alias)] = _plain(getattr(obj, key))
    if depth < max_depth:
        for rel in mapper.relationships:
            if rel.key in unloaded:
                continue
            value = getattr(obj, rel.key)
            if value is None:
                out[_alias(rel.key, alias)] = None
            elif rel.uselist:
                out[_alias(rel.key, alias)] = [
                    serialize(v, alias=alias, depth=depth + 1, max_depth=max_depth, _seen=seen)
                    for v in value
                    if id(v) not in seen
                ]
            elif id(value) not in seen:
                out[_alias(rel.key, alias)] = serialize(
                    value, alias=alias, depth=depth + 1, max_depth=max_depth, _seen=seen
                )
    return out


def _alias(key: str, alias: str | None) -> str:
    return to_camel(key) if alias == "camel" else key


# ── OpenAPI helpers ───────────────────────────────────────────────────────────


def _json_type(info: ColumnInfo) -> dict[str, Any]:
    py = info.python_type
    if info.enum_values:
        return {"enum": list(info.enum_values)}
    if py is bool:
        return {"type": "boolean"}
    if py is int:
        return {"type": "integer"}
    if py in (float, decimal.Decimal):
        return {"type": "number"}
    if py is dt.datetime:
        return {"type": "string", "format": "date-time"}
    if py is dt.date:
        return {"type": "string", "format": "date"}
    if py is uuid.UUID:
        return {"type": "string", "format": "uuid"}
    if py is str:
        schema: dict[str, Any] = {"type": "string"}
        if info.length:
            schema["maxLength"] = info.length
        return schema
    if py is dict:
        return {"type": "object"}
    if py is list:
        return {"type": "array", "items": {}}
    return {}


def read_schema(
    model: Any, attributes: Any = "*", alias: str | None = None, with_relations: bool = True
) -> dict[str, Any]:
    infos = {c.key: c for c in columns_of(model)}
    keys = select_attributes(attributes, list(infos))
    props: dict[str, Any] = {}
    for key in keys:
        schema = _json_type(infos[key])
        if infos[key].nullable:
            schema = {"anyOf": [schema or {}, {"type": "null"}]}
        props[_alias(key, alias)] = schema
    if with_relations:
        for rel in relations_of(model).values():
            child = read_schema(rel.target, alias=alias, with_relations=False)
            props[_alias(rel.key, alias)] = {"type": "array", "items": child} if rel.uselist else child
    return {"type": "object", "title": getattr(model, "__name__", "Item"), "properties": props}


def body_schema(model_cls: type[BaseModel], file_fields: Iterable[str] = (), multipart: bool = False) -> dict[str, Any]:
    schema = model_cls.model_json_schema()
    schema.pop("title", None)
    schema.pop("$defs", None)
    if multipart:
        props = schema.setdefault("properties", {})
        for name in file_fields:
            props[name] = {"type": "string", "format": "binary"}
    return schema


__all__ = [
    "ColumnInfo",
    "PydanticValidator",
    "RelationInfo",
    "body_schema",
    "column_keys",
    "columns_of",
    "generate_rules",
    "primary_key_of",
    "read_schema",
    "relations_of",
    "rules_to_model",
    "select_attributes",
    "serialize",
    "validation_errors",
]
