"""Response envelopes. The first two tests are ports of crudman-nestjs tests/response-formatter.test.ts."""

from __future__ import annotations

from crudman.response import (
    DELETE_PAYLOAD,
    FormatInput,
    default_response_formatter,
    empty_pagination,
    error_body,
)

PAGINATION = {
    "page": 1,
    "perPage": 2,
    "totalItemsCount": 2,
    "totalPagesCount": 1,
    "isHavingNextPage": False,
    "isHavingPreviousPage": False,
}


def test_formats_list_responses() -> None:
    body = default_response_formatter(
        FormatInput(action="list", payload={"items": [1, 2]}, pagination=PAGINATION, filters=[], sorting=[])
    )
    assert len(body["data"]) == 2
    assert body["success"] is True
    assert body["pagination"]["totalItemsCount"] == 2


def test_formats_detail_responses() -> None:
    body = default_response_formatter(FormatInput(action="details", payload={"id": 1}))
    assert body["data"]["id"] == 1
    assert body["success"] is True


def test_list_envelope_shape_matches_nestjs() -> None:
    body = default_response_formatter(FormatInput(action="list", payload={"items": []}))
    assert list(body) == ["data", "errors", "success", "pagination", "filters", "sorting"]
    assert body["pagination"] == empty_pagination()


def test_list_accepts_plain_sequence() -> None:
    assert default_response_formatter(FormatInput(action="list", payload=[{"id": 1}]))["data"] == [{"id": 1}]


def test_meta_only_when_present() -> None:
    assert "meta" not in default_response_formatter(FormatInput(action="details", payload={}))
    meta = {"baseUrls": {"a": "/"}}
    body = default_response_formatter(FormatInput(action="details", payload={}, meta=meta))
    assert body["meta"] == {"baseUrls": {"a": "/"}}


def test_missing_record_is_null_data() -> None:
    body = default_response_formatter(FormatInput(action="details", payload=None, success=False))
    assert body == {"data": None, "errors": [], "success": False}


def test_error_body() -> None:
    errors = [{"type": "unique", "field": "email", "message": "email must be unique"}]
    assert error_body("create", errors) == {"data": None, "errors": errors, "success": False}


def test_error_body_uses_custom_formatter() -> None:
    def fmt(f: FormatInput) -> dict[str, object]:
        return {"ok": f.success, "problems": f.errors}

    assert error_body("update", ["x"], fmt) == {"ok": False, "problems": ["x"]}


def test_delete_payload() -> None:
    body = default_response_formatter(FormatInput(action="delete", payload=DELETE_PAYLOAD))
    assert body["data"] == {"message": "Successfully deleted"}
