---
title: Feature list
---

# Feature list

Status key: ✅ built and unit-tested today · 🔜 planned (phase number in parentheses; see the [roadmap](./roadmap.md)).

## Defining CRUDs
- 🔜 `crud_router(Model)`: the model is the only required argument; the section name defaults to the table name (phase 4)
- 🔜 `crud_router(Model, "name", config)`: optional section name and settings, positional or keyword (phase 4)
- 🔜 Multi-model routers: `crud_router([Tag, Category, (Company, "orgs", cfg)])` (phase 4)
- 🔜 Class-based `CrudController` for people coming from NestJS (phase 4)
- 🔜 `crud.register(...)` + `@crud.list/details/create/update/delete/save("name")` on custom paths (phase 4)
- 🔜 `CrudmanService` for your own handlers; `call_action(section, action, ...)` across sections (phase 5)
- 🔜 Settings as a typed `Section(...)` or a plain dict, validated at startup (phase 1)
- 🔜 Three settings layers: global defaults → section → action; `common` accepted as an alias (phase 1)
- ✅ Section naming from the table name; `path_style` kebab / snake / camel / pascal; default path `/{section}`
- 🔜 Optional prefix; `route_prefix` global option; `path=` override; `actions=` filter (phase 4)
- 🔜 PATCH (partial update, default) or PUT (phase 4)

## Endpoints
- 🔜 list, details, create, update, delete (phase 2, 4)
- 🔜 save (upsert by `record_selection_field`), opt-in (phase 2)
- 🔜 bulk import (JSON/CSV; policies `upsert`, `insert_only`, `update_only`, `ignore_on_conflict`, `replace`; `batch_size`, `dry_run`, `stop_on_error`) and bulk delete (phase 9)
- 🔜 `record_selection_field` (e.g. slug) also names the path param (phase 2)

## Querying (list)
- ✅ Pagination: `page`, `perPage`/`per_page`, `paginate=false`, `perPage=0`, `max_per_page`, `is_default_enabled`, `is_pagination_enabled`, `is_disable_allowed`
- ✅ Sorting: `sort.<field>=asc|desc`, multi-sort, whitelist, empty value means desc
- ✅ Filters: equals, `.like`, `.min`, `.max`, `.gt`, `.lt`, `.between`; whitelist; `filters[]` echoed with `param`
- ✅ Renameable query params (`query_param_names`); camelCase and snake_case keys both accepted
- 🔜 Keyword search across columns and relation dot paths (depth ≤ 3), case-insensitive by default, `min_length` (phase 2)
- 🔜 Default sort `created_at DESC, pk DESC`; `order_by`; fixed `conditions` (phase 2)
- 🔜 Filters and keyword always ANDed, in a single query path (fixes the NestJS OR bug) (phase 2)

## Data shaping
- 🔜 Relations: `"*"` (default), list, include / exclude, `get_relations(ctx)`; eager-loaded (phase 2)
- 🔜 Attributes: separate read and write include / exclude (phase 2, 3)
- ✅ Standard response envelope (`data`, `errors`, `success`, `pagination`, `filters`, `sorting`, `meta`), identical to NestJS
- 🔜 Global `response_formatter`, per-action `response_handler`, `additional_response` / `get_additional_response` into `meta` (phase 5)
- 🔜 `field_alias="camel"` for front-ends written against the NestJS version (phase 2)

## Validation
- 🔜 Pydantic models generated from the SQLAlchemy model (types, nullability, length, defaults) (phase 3)
- 🔜 Create rejects unknown fields; update drops them; PK and timestamp columns skipped (phase 3)
- 🔜 `get_final_validation_rules` returning a Pydantic class or a fastest-validator-style dict (phase 3)
- 🔜 Uniqueness checks (`or` / `and`), excluding the current record and checking only fields sent (phase 2)
- 🔜 Errors as `{type, field, message}` with HTTP 400 (phase 3)

## Hooks and context
- 🔜 `on_before_action`, `on_before_query` (receives a SQLAlchemy `Select`), `on_after_fetch`, `on_before_validate`, `get_final_validation_rules`, `on_after_validate`, `on_after_action` (its return value replaces the response) (phase 5)
- 🔜 `ctx` with service, session, repository helper, section, action, model, request, identity, params, query, body, files (phase 5)
- 🔜 Context builders: dict (with `Depends`), function, `get_hook_context`; reserved keys protected (phase 5)
- 🔜 `custom_implementation` to fully override an action (phase 5)

## Access control
- 🔜 `identity_accessor`, `role_checker`, `required_roles`, `ownership` (enforced, unlike in NestJS) (phase 6)

## Uploads
- 🔜 Multipart and base64; shorthand `uploadable={"avatar": "image"}` with `[]`, `:base64`, `:blob` (phase 8)
- 🔜 Storage modes `filename`, `filename_in_field`, `base64`, `blob`; Local and S3 storage (phase 8)
- 🔜 About 30 presets (image, avatar, video, audio, pdf, doc, spreadsheet, text, csv, xml, html, json, archive, binary, any) (phase 8)
- 🔜 Size / MIME / extension / avatar dimension checks; `delete_on_replace`, `key_pattern`, append mode (phase 8)
- 🔜 `meta.baseUrls`, `x-file-url: full|key_only` (phase 8)

## Output, cache, docs
- 🔜 CSV and Excel export via `x-content-type`, `Accept` or `?format=`; `X-Pagination-*` headers (phase 9)
- 🔜 TTL cache per action with custom keys; per-section invalidation on writes; Redis adapter (phase 7)
- 🔜 OpenAPI: typed request bodies (json/form/multipart), query params, envelope schemas, tags, operation ids (phase 4)
- 🔜 Error mode `throw_on_error`; `strict_status` (201 on create, 404 on missing) (phase 5)
- 🔜 Transactions around writes, so `call_action` inside hooks shares the transaction (phase 5)
- 🔜 Pluggable adapters: `OrmAdapter`, `ValidatorAdapter`, `CacheAdapter`, `FileStorageAdapter` (phase 1)

## Project
- ✅ README in the crudman-nestjs style
- ✅ Docusaurus documentation site (`website/`)
- ✅ Unit test suite (pytest) for the modules built so far; it grows with each phase
