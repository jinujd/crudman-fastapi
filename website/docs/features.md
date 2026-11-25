---
title: Feature list
---

# Feature list

Status key: ✅ built and covered by tests (end-to-end on SQLite) · ⚠️ built, but not tested against a live service.

## Defining CRUDs
- ✅ `crud_router(Model)`: the model is the only required argument; the section name defaults to the table name
- ✅ `crud_router(Model, "name", config)`: optional section name and settings, positional or keyword
- ✅ Multi-model routers: `crud_router([Tag, Category, (Company, "orgs", cfg)])`
- ✅ Class-based `CrudController` for people coming from NestJS
- ✅ `crud.register(...)` + `@crud.list/details/create/update/delete/save("name")` on custom paths
- ✅ `CrudmanService` for your own handlers; `call_action(section, action, ...)` across sections
- ✅ Settings as a typed `Section(...)` or a plain dict, validated at startup
- ✅ Three settings layers: global defaults → section → action; `common` accepted as an alias
- ✅ Section naming from the table name; `path_style` kebab / snake / camel / pascal; default path `/{section}`
- ✅ Optional prefix; `route_prefix` global option; `path=` override; `actions=` filter
- ✅ PATCH (partial update, default) or PUT

## Endpoints
- ✅ list, details, create, update, delete
- ✅ save (upsert by `record_selection_field`), opt-in
- ✅ bulk import (JSON/CSV; policies `upsert`, `insert_only`, `update_only`, `ignore_on_conflict`, `replace`; `batch_size`, `dry_run`, `stop_on_error`) and bulk delete
- ✅ `record_selection_field` (e.g. slug) also names the path param

## Querying (list)
- ✅ Pagination: `page`, `perPage`/`per_page`, `paginate=false`, `perPage=0`, `max_per_page`, `is_default_enabled`, `is_pagination_enabled`, `is_disable_allowed`
- ✅ Sorting: `sort.<field>=asc|desc`, multi-sort, whitelist, empty value means desc
- ✅ Filters: equals, `.like`, `.min`, `.max`, `.gt`, `.lt`, `.between`; whitelist; `filters[]` echoed with `param`
- ✅ Renameable query params (`query_param_names`); camelCase and snake_case keys both accepted
- ✅ Keyword search across columns and relation dot paths (depth ≤ 3), case-insensitive by default, `min_length`
- ✅ Default sort `created_at DESC, pk DESC`; `order_by`; fixed `conditions`
- ✅ Filters and keyword always ANDed, in a single query path (fixes the NestJS OR bug)

## Data shaping
- ✅ Relations: `"*"` (default), list, include / exclude, `get_relations(ctx)`; eager-loaded
- ✅ Attributes: separate read and write include / exclude
- ✅ Standard response envelope (`data`, `errors`, `success`, `pagination`, `filters`, `sorting`, `meta`), identical to NestJS
- ✅ Global `response_formatter`, per-action `response_handler`, `additional_response` / `get_additional_response` into `meta`
- ✅ `field_alias="camel"` for front-ends written against the NestJS version

## Validation
- ✅ Pydantic models generated from the SQLAlchemy model (types, nullability, length, defaults)
- ✅ Create rejects unknown fields; update drops them; PK and timestamp columns skipped
- ✅ `get_final_validation_rules` returning a Pydantic class or a fastest-validator-style dict
- ✅ Uniqueness checks (`or` / `and`), excluding the current record and checking only fields sent
- ✅ Errors as `{type, field, message}` with HTTP 400

## Hooks and context
- ✅ `on_before_action`, `on_before_query` (receives a SQLAlchemy `Select`), `on_after_fetch`, `on_before_validate`, `get_final_validation_rules`, `on_after_validate`, `on_after_action` (its return value replaces the response)
- ✅ `ctx` with service, session, repository helper, section, action, model, request, identity, params, query, body, files
- ✅ Context builders: dict (with `Depends`), function, `get_hook_context`; reserved keys protected
- ✅ `custom_implementation` to fully override an action

## Access control
- ✅ `identity_accessor`, `role_checker`, `required_roles`, `ownership` (enforced, unlike in NestJS)

## Uploads
- ✅ Multipart and base64; shorthand `uploadable={"avatar": "image"}` with `[]`, `:base64`, `:blob`
- ✅ Storage modes `filename`, `filename_in_field`, `base64`, `blob`; local disk storage
- ⚠️ S3 storage (`S3Storage`)
- ✅ About 30 presets (image, avatar, video, audio, pdf, doc, spreadsheet, text, csv, xml, html, json, archive, binary, any)
- ✅ Size / MIME / extension / avatar dimension checks; `delete_on_replace`, `key_pattern`, append mode
- ✅ `meta.baseUrls`, `x-file-url: full|key_only`

## Output, cache, docs
- ✅ CSV and Excel export via `x-content-type`, `Accept` or `?format=`; `X-Pagination-*` headers
- ✅ TTL cache per action with custom keys; per-section invalidation on writes
- ⚠️ Redis cache adapter (`RedisCache`)
- ✅ OpenAPI: typed request bodies (json/form/multipart), query params, envelope schemas, tags, operation ids
- ✅ Error mode `throw_on_error`; `strict_status` (201 on create, 404 on missing)
- ✅ Transactions around writes, so `call_action` inside hooks shares the transaction
- ✅ Pluggable adapters: `OrmAdapter`, `ValidatorAdapter`, `CacheAdapter`, `FileStorageAdapter`

## Project
- ✅ README in the crudman-nestjs style
- ✅ Docusaurus documentation site (`website/`)
- ✅ Test suite (pytest): unit tests plus end-to-end tests on SQLite
- ✅ Runnable example app (`examples/fastapi_sqlalchemy_sqlite`)
