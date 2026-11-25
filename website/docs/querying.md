---
title: Querying
---

# Querying (list)

:::tip Implemented
The query-string parser is implemented and unit-tested (`crudman.query`).
:::

## Pagination

| Parameter | Default | Notes |
| --- | --- | --- |
| `page` | `1` | values below 1 become 1 |
| `perPage` | `30` | alias `per_page`; capped by `max_per_page` |
| `paginate` | | `false`, `0` or `no` returns everything (when allowed) |
| `perPage=0` | | also returns everything |

Per-action toggles:

```python
ListAction(pagination=Pagination(
    is_pagination_enabled=True,   # False: always return everything
    is_disable_allowed=True,      # honour paginate=false / perPage=0
    is_default_enabled=True,      # False: return everything unless page/perPage is sent
    max_per_page=100,
))
```

## Sorting

`sort.<field>=asc|desc`, repeatable for multi-sort. Anything other than `asc` (including an empty value)
means descending. With no sort, the default is `created_at DESC` then the primary key, or `order_by` if you
set it.

```text
GET /companies?sort.created_at=desc&sort.name=asc
```

## Filters

| Syntax | Meaning |
| --- | --- |
| `field=value` | equals |
| `field.like=value` | contains, case-insensitive |
| `field.min=value` | greater than or equal |
| `field.max=value` | less than or equal |
| `field.gt=value` | greater than |
| `field.lt=value` | less than |
| `field.between=a,b` | inclusive range |

Range values may be numbers or ISO dates (`created_at.min=2024-01-01`). Unknown operators are ignored.
Only whitelisted fields are used; the default whitelist is every root column.

```text
GET /companies?is_active=true&name.like=air
GET /companies?created_at.between=2024-01-01,2024-12-31&page=2&perPage=20
```

## camelCase or snake_case

Front-ends written for crudman-nestjs send camelCase. Both spellings reach the same column:
`sort.createdAt` and `sort.created_at` both sort by `created_at`.

## Keyword search

```text
GET /companies?keyword=acme
```

```python
ListAction(keyword=Keyword(
    is_enabled=True,
    is_case_sensitive=False,
    min_length=2,
    searchable_fields=["name", "contacts.email", "contacts.address.city"],
    max_relation_depth=2,          # 1 to 3
))
```

Without `searchable_fields`, all root columns are searched. Keyword search is always combined with filters
using AND.

## Renaming parameters

```python
ListAction(query_param_names={
    "page": "p", "per_page": "pp", "paginate": "pg",
    "sort_prefix": "order.", "keyword": "q",
    "min_op": "from", "max_op": "to", "between_op": "range", "like_op": "contains",
})
```

Reserved parameters (`page`, `perPage`, `paginate`, `keyword`, `sort.*`, `format`, `x-content-type`) are
never treated as filters.

## Echoed in the response

```json
"filters": [ { "field": "name", "op": "like", "value": "air", "param": "name.like" } ],
"sorting": [ { "field": "created_at", "order": "DESC" } ]
```
