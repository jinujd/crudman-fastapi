"""Response envelopes.

The default formatter produces exactly the JSON shape of crudman-nestjs, so clients can switch
backends without changes:

* list:    ``{data: [...], errors, success, pagination, filters, sorting, meta?}``
* others:  ``{data: {...} | null, errors, success, meta?}``

``meta`` is omitted when there is nothing to put in it, matching how ``undefined`` keys disappear
from the NestJS JSON output.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

Action = Literal["list", "details", "create", "update", "save", "delete"]


def empty_pagination() -> dict[str, Any]:
    return {
        "page": 1,
        "perPage": 0,
        "totalItemsCount": 0,
        "totalPagesCount": 0,
        "isHavingNextPage": False,
        "isHavingPreviousPage": False,
    }


@dataclass
class FormatInput:
    """Everything a response formatter receives."""

    action: Action
    payload: Any = None
    errors: list[Any] = field(default_factory=list)
    success: bool = True
    pagination: Mapping[str, Any] | None = None
    filters: list[Any] | None = None
    sorting: list[Any] | None = None
    meta: Mapping[str, Any] | None = None
    request: Any = None


ResponseFormatter = Callable[[FormatInput], Any]


def default_response_formatter(f: FormatInput) -> dict[str, Any]:
    """The standard crudman envelope."""
    body: dict[str, Any]
    if f.action == "list":
        payload = f.payload
        if isinstance(payload, Mapping):
            items = payload.get("items") or []
        elif payload is None:
            items = []
        else:
            items = list(payload)
        body = {
            "data": items,
            "errors": list(f.errors or []),
            "success": f.success is not False,
            "pagination": dict(f.pagination) if f.pagination else empty_pagination(),
            "filters": list(f.filters or []),
            "sorting": list(f.sorting or []),
        }
    else:
        body = {
            "data": f.payload if f.payload is not None else None,
            "errors": list(f.errors or []),
            "success": f.success is not False,
        }
    if f.meta:
        body["meta"] = dict(f.meta)
    return body


def error_body(action: Action, errors: list[Any], formatter: ResponseFormatter | None = None) -> Any:
    """Envelope for a failed request (validation errors, not found, blocked by a hook)."""
    fmt = formatter or default_response_formatter
    return fmt(FormatInput(action=action, payload=None, errors=errors, success=False))


DELETE_PAYLOAD: dict[str, str] = {"message": "Successfully deleted"}

__all__ = [
    "DELETE_PAYLOAD",
    "Action",
    "FormatInput",
    "ResponseFormatter",
    "default_response_formatter",
    "empty_pagination",
    "error_body",
]
