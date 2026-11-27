---
title: Import and export
---

# Import and export

## Export

Ask for CSV or Excel on list or details in any of these ways:

- header `x-content-type: csv` or `excel`
- header `Accept: text/csv`
- query `?format=csv` or `?x-content-type=excel`

```bash
curl -i -H 'x-content-type: csv' 'localhost:8000/companies?is_active=true'
```

Cells that start with `=`, `+`, `-`, `@`, tab or carriage return are escaped (CSV) or stored as plain text (Excel),
so exported data never runs as a spreadsheet formula.

For lists, the body holds only the rows. Pagination and query details go into headers:
`X-Pagination-Total`, `X-Pagination-Page`, `X-Pagination-PerPage`, `X-Filters`, `X-Sorting`.

Excel needs the `excel` extra; without it the API returns HTTP 400 with a JSON error saying so. Limit the allowed
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

Imports are limited to `CrudmanOptions.max_bulk_rows` rows (default 1000); larger imports get HTTP 413.

`POST /companies/bulk/delete` accepts `{"ids": [...]}` or a CSV list of ids.

Options can also go in a JSON object body: `{"items": [...], "policy": "upsert", "dry_run": true}`.

The response is a summary. `success` is false when any row failed:

```json
{
  "data": {
    "inserted": 1, "updated": 1, "deleted": 0, "skipped": 0, "errorsCount": 1,
    "dryRun": false, "policy": "upsert",
    "rowErrors": [ { "row": 3, "errors": [ { "type": "stringMin", "field": "name", "message": "..." } ] } ]
  },
  "errors": [],
  "success": false
}
```

Rows are validated like single creates and updates. A database error (for example a constraint the
validator cannot see) rolls back the whole import.
