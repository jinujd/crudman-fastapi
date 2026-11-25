---
title: Response format
---

# Response format

:::tip Implemented
The default formatter is implemented and unit-tested (`crudman.response`).
:::

The envelope is identical to crudman-nestjs.

## List

```json
{
  "data": [ { "id": 1, "name": "Acme Air" } ],
  "errors": [],
  "success": true,
  "pagination": {
    "page": 1, "perPage": 30, "totalItemsCount": 1, "totalPagesCount": 1,
    "isHavingNextPage": false, "isHavingPreviousPage": false
  },
  "filters": [],
  "sorting": [ { "field": "created_at", "order": "DESC" } ]
}
```

## Details, create, update, save

```json
{ "data": { "id": 1, "name": "Acme Air" }, "errors": [], "success": true }
```

## Delete

```json
{ "data": { "message": "Successfully deleted" }, "errors": [], "success": true }
```

## Errors

```json
{ "data": null, "errors": [ { "type": "unique", "field": "name", "message": "name must be unique" } ], "success": false }
```

`meta` is added only when there is something in it: `additional_response`, upload base URLs, or
anything a hook puts there.

## Custom formatter

```python
from crudman import FormatInput

def my_formatter(f: FormatInput):
    return {"ok": f.success, "result": f.payload, "pageInfo": f.pagination}

CrudmanOptions(response_formatter=my_formatter)            # global
ListAction(response_handler=lambda result, ctx: {...})     # per action
```

`FormatInput` has `action`, `payload`, `errors`, `success`, `pagination`, `filters`, `sorting`, `meta` and
`request`.

## Status codes

| Case | Default | `strict_status=True` |
| --- | --- | --- |
| create / save | 200 | 201 |
| validation error | 400 | 400 |
| record not found | 404 | 404 |
| blocked by `on_before_action` | 403 | 403 |
