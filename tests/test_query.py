"""Query parsing. The first three tests are ports of crudman-nestjs tests/query-utils.test.ts."""

from __future__ import annotations

import pytest

from crudman.query import (
    KeywordOptions,
    PaginationOptions,
    QueryParamNames,
    SortItem,
    finalize_pagination,
    keyword_paths,
    parse_filters,
    parse_keyword,
    parse_pagination,
    parse_sorting,
    resolve_field,
    to_camel,
    to_snake,
)

# ── ported from crudman-nestjs ────────────────────────────────────────────────


def test_parses_pagination_defaults() -> None:
    r = parse_pagination({})
    assert r.info.page == 1
    assert r.info.per_page == 30
    assert r.offset == 0
    assert r.limit == 30
    assert r.disabled is False


def test_parses_sorting_with_whitelist() -> None:
    s = parse_sorting({"sort.createdAt": "asc", "sort.email": "desc"}, ["createdAt"])
    assert s == [SortItem(field="createdAt", order="ASC")]


def test_parses_filters_with_whitelist_and_operators() -> None:
    filters = parse_filters(
        {"createdAt.between": "2024-01-01,2024-01-31", "role": "admin", "price.min": "10"},
        ["createdAt", "role", "price"],
    )
    by_field = {f.field: f for f in filters}
    assert by_field["role"].op == "eq" and by_field["role"].value == "admin"
    assert by_field["createdAt"].op == "between"
    assert by_field["createdAt"].value == ["2024-01-01", "2024-01-31"]
    assert by_field["price"].op == "gte" and by_field["price"].value == 10
    assert len(filters) == 3


# ── naming helpers ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "camel", "snake"),
    [
        ("per_page", "perPage", "per_page"),
        ("perPage", "perPage", "per_page"),
        ("per-page", "perPage", "per_page"),
        ("created_at", "createdAt", "created_at"),
        ("name", "name", "name"),
    ],
)
def test_case_conversion(raw: str, camel: str, snake: str) -> None:
    assert to_camel(raw) == camel
    assert to_snake(raw) == snake


def test_resolve_field_accepts_camel_for_snake_columns() -> None:
    assert resolve_field("createdAt", ["created_at", "name"]) == "created_at"
    assert resolve_field("created_at", ["createdAt"]) == "createdAt"
    assert resolve_field("secret", ["name"]) is None
    assert resolve_field("anything", []) == "anything"


# ── pagination ────────────────────────────────────────────────────────────────


def test_page_and_per_page() -> None:
    r = parse_pagination({"page": "3", "perPage": "20"})
    assert (r.info.page, r.info.per_page, r.offset, r.limit) == (3, 20, 40, 20)
    assert r.info.is_having_previous_page is True


def test_per_page_snake_case_alias() -> None:
    assert parse_pagination({"per_page": "15"}).info.per_page == 15


ALLOW_DISABLE = PaginationOptions(is_disable_allowed=True)


@pytest.mark.parametrize("value", ["false", "0", "no", "FALSE"])
def test_paginate_flag_disables_when_allowed(value: str) -> None:
    r = parse_pagination({"paginate": value}, options=ALLOW_DISABLE)
    assert r.disabled is True
    assert r.offset is None and r.limit is None


def test_per_page_zero_disables_when_allowed() -> None:
    assert parse_pagination({"perPage": "0"}, options=ALLOW_DISABLE).disabled is True


def test_disabling_is_off_by_default() -> None:
    # 0.1.1: clients can no longer dump a whole table unless the section allows it
    assert parse_pagination({"paginate": "false"}).disabled is False
    assert parse_pagination({"perPage": "0"}).disabled is False


def test_default_max_per_page_is_100() -> None:
    assert parse_pagination({"perPage": "1000000"}).info.per_page == 100
    assert parse_pagination({"perPage": "500"}, options=PaginationOptions(max_per_page=None)).info.per_page == 500


def test_pagination_turned_off_for_action() -> None:
    assert parse_pagination({"page": "2"}, options=PaginationOptions(is_pagination_enabled=False)).disabled


def test_default_disabled_until_client_asks() -> None:
    opts = PaginationOptions(is_default_enabled=False)
    assert parse_pagination({}, options=opts).disabled is True
    assert parse_pagination({"page": "1"}, options=opts).disabled is False


def test_max_per_page_caps() -> None:
    r = parse_pagination({"perPage": "500"}, options=PaginationOptions(max_per_page=100))
    assert r.info.per_page == 100


@pytest.mark.parametrize(("raw", "expected"), [("abc", 30), ("-5", 1), ("", 30)])
def test_bad_per_page_values(raw: str, expected: int) -> None:
    assert parse_pagination({"perPage": raw}).info.per_page == expected


@pytest.mark.parametrize("raw", ["0", "-3", "x"])
def test_bad_page_values_fall_back_to_one(raw: str) -> None:
    assert parse_pagination({"page": raw}).info.page == 1


def test_renamed_param_names() -> None:
    names = QueryParamNames.from_mapping({"page": "p", "perPage": "pp", "paginate": "pg"})
    r = parse_pagination({"p": "2", "pp": "5"}, names)
    assert (r.info.page, r.info.per_page) == (2, 5)
    assert parse_pagination({"pg": "false"}, names, ALLOW_DISABLE).disabled


def test_query_param_names_rejects_unknown_keys() -> None:
    with pytest.raises(ValueError):
        QueryParamNames.from_mapping({"pageSize": "x"})


def test_finalize_pagination_paged() -> None:
    r = parse_pagination({"page": "2", "perPage": "25"})
    info = finalize_pagination(r, total=137, item_count=25)
    assert info.to_dict() == {
        "page": 2,
        "perPage": 25,
        "totalItemsCount": 137,
        "totalPagesCount": 6,
        "isHavingNextPage": True,
        "isHavingPreviousPage": True,
    }


def test_finalize_pagination_last_page() -> None:
    info = finalize_pagination(parse_pagination({"page": "6", "perPage": "25"}), total=137, item_count=12)
    assert info.is_having_next_page is False


def test_finalize_pagination_disabled() -> None:
    info = finalize_pagination(parse_pagination({"paginate": "false"}, options=ALLOW_DISABLE), total=7, item_count=7)
    assert info.to_dict() == {
        "page": 1,
        "perPage": 7,
        "totalItemsCount": 7,
        "totalPagesCount": 1,
        "isHavingNextPage": False,
        "isHavingPreviousPage": False,
    }


# ── sorting ───────────────────────────────────────────────────────────────────


def test_multi_sort_keeps_order() -> None:
    s = parse_sorting({"sort.createdAt": "desc", "sort.name": "asc"}, ["created_at", "name"])
    assert s == [SortItem("created_at", "DESC"), SortItem("name", "ASC")]


@pytest.mark.parametrize("value", ["", "DESC", "whatever"])
def test_sort_defaults_to_desc(value: str) -> None:
    assert parse_sorting({"sort.name": value})[0].order == "DESC"


def test_custom_sort_prefix() -> None:
    assert parse_sorting({"order.name": "asc"}, sort_prefix="order.") == [SortItem("name", "ASC")]


def test_duplicate_spellings_sort_once() -> None:
    s = parse_sorting({"sort.createdAt": "asc", "sort.created_at": "desc"}, ["created_at"])
    assert s == [SortItem("created_at", "ASC")]


# ── filters ───────────────────────────────────────────────────────────────────


def test_like_and_range_operators() -> None:
    filters = parse_filters(
        {"name.like": "air", "price.max": "99.5", "stock.gt": "0", "stock.lt": "10"},
        ["name", "price", "stock"],
    )
    got = {(f.field, f.op): f.value for f in filters}
    assert got == {
        ("name", "like"): "air",
        ("price", "lte"): 99.5,
        ("stock", "gt"): 0,
        ("stock", "lt"): 10,
    }


def test_range_on_dates_keeps_value() -> None:
    # The NestJS version drops this filter because Number("2024-01-01") is NaN.
    [f] = parse_filters({"createdAt.min": "2024-01-01"}, ["created_at"])
    assert (f.field, f.op, f.value, f.param) == ("created_at", "gte", "2024-01-01", "createdAt.min")


def test_filter_param_echo() -> None:
    [f] = parse_filters({"name.like": "x"}, ["name"])
    assert f.to_dict() == {"field": "name", "op": "like", "value": "x", "param": "name.like"}


def test_non_whitelisted_and_empty_are_ignored() -> None:
    assert parse_filters({"secret": "x", "name": ""}, ["name"]) == []


def test_unknown_operator_is_ignored() -> None:
    assert parse_filters({"name.regex": ".*"}, ["name"]) == []


def test_reserved_params_never_become_filters_even_without_whitelist() -> None:
    query = {"page": "1", "perPage": "10", "per_page": "10", "paginate": "false", "keyword": "abc",
             "sort.name": "asc", "format": "csv", "x-content-type": "csv", "name": "acme"}
    assert [f.field for f in parse_filters(query)] == ["name"]


def test_renamed_operators() -> None:
    names = QueryParamNames.from_mapping({"min_op": "from", "max_op": "to", "like_op": "contains"})
    filters = parse_filters({"price.from": "1", "price.to": "5", "name.contains": "a"}, None, names)
    assert {(f.field, f.op) for f in filters} == {("price", "gte"), ("price", "lte"), ("name", "like")}


# ── keyword ───────────────────────────────────────────────────────────────────


def test_keyword_basic_and_trimmed() -> None:
    assert parse_keyword({"keyword": "  acme "}) == "acme"


def test_keyword_min_length_and_disabled() -> None:
    assert parse_keyword({"keyword": "a"}) is None
    assert parse_keyword({"keyword": "acme"}, options=KeywordOptions(is_enabled=False)) is None
    assert parse_keyword({"keyword": "ab"}, options=KeywordOptions(min_length=3)) is None


def test_keyword_renamed_param() -> None:
    assert parse_keyword({"q": "acme"}, QueryParamNames(keyword="q")) == "acme"


def test_keyword_paths_respect_depth() -> None:
    opts = KeywordOptions(searchable_fields=("name", "contacts.email", "contacts.address.city", "a.b.c.d"))
    assert keyword_paths(opts, []) == ["name", "contacts.email"]
    deeper = KeywordOptions(searchable_fields=opts.searchable_fields, max_relation_depth=2)
    assert keyword_paths(deeper, []) == ["name", "contacts.email", "contacts.address.city"]


def test_keyword_paths_default_to_columns() -> None:
    assert keyword_paths(KeywordOptions(), ["id", "name"]) == ["id", "name"]
