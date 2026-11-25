---
title: Import and export
---

# Import and export

:::info Planned (phase 9)
:::

## Export

Ask for CSV or Excel on list or details in any of these ways:

- header `x-content-type: csv` or `excel`
- header `Accept: text/csv`
- query `?format=csv` or `?x-content-type=excel`

```bash
curl -i -H 'x-content-type: csv' 'localhost:8000/companies?is_active=true'
```

For lists, the body holds only the rows. Pagination and query details go into headers:
`X-Pagination-Total`, `X-Pagination-Page`, `X-Pagination-PerPage`, `X-Filters`, `X-Sorting`.

Excel needs the `excel` extra; without it the API returns a JSON error saying so. Limit the allowed
formats with `CrudmanOptions(export_content_types=["json", "csv"])`.

## Bulk import and delete

Opt in per router:

```python
crud_router(Company, actions=["*", "bulk_import", "bulk_delete"])
```

`POST /companies/bulk/import` accepts a JSON array, or CSV with `x-content-type: csv`.

| Option | Values |
| --- | --- |
| `policy` | `upsert` (default), `insert_only`, `update_only`, `ignore_on_conflict`, `replace` |
| `record_selection_field` | default from the section, or `id` |
| `batch_size` | rows per transaction |
| `dry_run` | validate only |
| `stop_on_error` | stop at the first failing row |

`POST /companies/bulk/delete` accepts `{"ids": [...]}` or a CSV list of ids.

The response is a summary: `{"inserted": 0, "updated": 0, "deleted": 0, "skipped": 0, "errorsCount": 0}`.
