"""Content negotiation and CSV / Excel output for list and details."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import quote

EXCEL_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def requested_format(headers: Mapping[str, str], query: Mapping[str, Any]) -> str:
    """``json`` | ``csv`` | ``excel`` from ``x-content-type``, ``?format=``/``?x-content-type=`` or ``Accept``."""
    sources = [
        headers.get("x-content-type", ""),
        str(query.get("x-content-type") or query.get("x_content_type") or query.get("format") or ""),
    ]
    accept = headers.get("accept", "")
    for raw in sources:
        fmt = _normalize(raw)
        if fmt:
            return fmt
    low = accept.lower()
    if "text/csv" in low:
        return "csv"
    if "spreadsheetml" in low or "excel" in low:
        return "excel"
    return "json"


def _normalize(raw: str) -> str:
    low = raw.strip().lower()
    if not low:
        return ""
    if "excel" in low or "xlsx" in low or "sheet" in low:
        return "excel"
    if "csv" in low:
        return "csv"
    if "json" in low:
        return "json"
    return ""


def flatten(row: Any, depth: int = 1, prefix: str = "") -> dict[str, Any]:
    """Nested dicts become ``parent.child`` columns (one level deep); lists become JSON."""
    if not isinstance(row, Mapping):
        return {prefix or "value": row}
    out: dict[str, Any] = {}
    for key, value in row.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, Mapping) and depth > 0:
            out.update(flatten(value, depth - 1, name))
        elif isinstance(value, (list, Mapping)):
            out[name] = json.dumps(value, default=str)
        else:
            out[name] = value
    return out


def _headers(rows: Iterable[Mapping[str, Any]]) -> list[str]:
    seen: list[str] = []
    for row in rows:
        for key in row:
            if key not in seen:
                seen.append(key)
    return seen


_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def escape_formula(value: Any) -> Any:
    """Neutralise text that a spreadsheet would run as a formula (CSV/formula injection)."""
    if isinstance(value, str) and value.startswith(_FORMULA_START):
        return "'" + value
    return value


def _cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return escape_formula(value)


def to_csv(rows: list[Any]) -> str:
    flat = [flatten(r) for r in rows]
    headers = _headers(flat)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([escape_formula(h) for h in headers])
    for row in flat:
        writer.writerow([_cell(row.get(h)) for h in headers])
    return buf.getvalue()


def parse_csv(text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text))
    return [{k: v for k, v in row.items() if k is not None} for row in reader]


def to_excel(rows: list[Any]) -> bytes:
    try:
        from openpyxl import Workbook
    except ImportError as exc:
        raise ImportError('Excel export requires the excel extra: pip install "crudman-fastapi[excel]"') from exc
    flat = [flatten(r) for r in rows]
    headers = _headers(flat)
    wb = Workbook()
    ws = wb.active
    ws.title = "data"
    ws.append([escape_formula(h) for h in headers])
    for row in flat:
        ws.append([_excel_cell(row.get(h)) for h in headers])
    # openpyxl stores any string starting with "=" as a formula; force every text cell to plain text
    for ws_row in ws.iter_rows(min_row=1):
        for cell in ws_row:
            if isinstance(cell.value, str):
                cell.data_type = "s"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _excel_cell(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "tzinfo") and getattr(value, "tzinfo", None) is not None:
        return value.replace(tzinfo=None)
    return value if hasattr(value, "isoformat") else str(value)


def list_headers(body: Mapping[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    pagination = body.get("pagination") or {}
    if "totalItemsCount" in pagination:
        out["X-Pagination-Total"] = str(pagination["totalItemsCount"])
    if "page" in pagination:
        out["X-Pagination-Page"] = str(pagination["page"])
    if "perPage" in pagination:
        out["X-Pagination-PerPage"] = str(pagination["perPage"])
    if "filters" in body:
        out["X-Filters"] = quote(json.dumps(body["filters"], default=str))
    if "sorting" in body:
        out["X-Sorting"] = quote(json.dumps(body["sorting"], default=str))
    return out


__all__ = [
    "EXCEL_MIME", "escape_formula", "flatten", "list_headers", "parse_csv", "requested_format", "to_csv", "to_excel",
]
