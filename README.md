<h1 align="center" style="color:#352D77">crudman-fastapi</h1>

<p align="center">
  <img src="docs/assets/crudman-logo.svg" alt="CRUD Man Logo" width="140" />
  <br/>
  <sub style="color:#3F4C70">Minimal, adapter-driven CRUD layer for <strong>FastAPI</strong> + <strong>SQLAlchemy</strong>.</sub>
  <br/>
  <a href="https://jinujd.github.io/crudman-fastapi/">Docs</a> · <a href="https://github.com/jinujd/crudman-fastapi">GitHub</a> · <a href="https://github.com/jinujd/crudman-nestjs">NestJS version</a>
  <br/>
</p>

> **Status: 0.1.0 (alpha).** Everything below is implemented and covered by end-to-end tests on SQLite and PostgreSQL,
> except the Redis cache and S3 storage adapters, which are built but not yet tested against live services.

> Creating CRUD is so simple. This is a complete Companies CRUD:

```python
from crudman import Crudman, CrudmanOptions, crud_router
from app.models import Company

Crudman.init(app, CrudmanOptions(session_dependency=get_session))
app.include_router(crud_router(Company))
```

That gives you (the path comes from `Company.__tablename__`):
- `GET /companies` (with filters, sorting, pagination, keyword)
- `GET /companies/{id}` (includes relations by default)
- `POST /companies`
- `PATCH /companies/{id}`
- `DELETE /companies/{id}`

Plus OpenAPI docs at `/docs`, validation generated from your model, and CSV / Excel export
(`x-content-type: csv` or `excel`).

crudman-fastapi is the Python port of [crudman-nestjs](https://github.com/jinujd/crudman-nestjs). The HTTP
contract (query parameters, response envelope, headers) is identical, so the same front-end works against
either backend.

## Features

- 🔌 Launch-ready CRUD endpoints in one line
- 🐙 Adapter-first design (SQLAlchemy 2.0 async today; ORM, validator, cache and storage are pluggable)
- 🔎 Powerful querying: filters, sorting, pagination, keyword search
- 🧭 Relations and attributes control (include/exclude, sensible defaults)
- 🧪 Validation generated from your model with Pydantic v2, overridable per request
- 🎬 Hooks at every step, with a typed per-request context
- 🔧 Minimal config: global options, per-section and per-action settings
- ✏️ OpenAPI-native: typed request bodies and response envelopes
- 📦 File uploads: multipart/base64 with local/S3 storage and shorthand presets
- 🧊 Per-endpoint caching with invalidation on writes
- 📤 CSV/Excel export, bulk import and bulk delete

## At-a-glance capabilities

| Capability | What you get |
| --- | --- |
| Auto CRUD endpoints | List, details, create, update, delete from `crud_router(Model)` |
| Zero naming config | Section name and URL default to the table name |
| PATCH-first updates | Partial updates by default (configurable to PUT) |
| Relations by default | All relations eager-loaded; refine with include/exclude |
| Attributes selection | Separate read and write include/exclude |
| Powerful querying | Filters, sorting, pagination, keyword search with safe whitelists |
| Validation built-in | Pydantic models generated from SQLAlchemy columns |
| Uniqueness checks | `fields_for_uniqueness_validation` with OR/AND semantics |
| Hooks | Before/after action, query, fetch and validation |
| Access control | `required_roles`, `ownership`, identity accessor |
| Caching | TTL cache per endpoint, Redis optional |
| Save (upsert) | One endpoint that creates or updates |
| Programmatic calls | `call_action` across sections, inside the same transaction |
| Import / export | CSV and Excel export; bulk import and delete |

## Installation

```bash
pip install crudman-fastapi
# optional extras
pip install "crudman-fastapi[uploads,images,excel,s3,redis]"
```

Requires Python 3.10+, FastAPI 0.115+, SQLAlchemy 2.0+, Pydantic 2.7+.

## Quick start

### 1) Model

```python
# app/models.py
from datetime import datetime
from sqlalchemy import String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase): ...

class Company(Base):
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    email: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
```

### 2) Register crudman once

```python
# app/main.py
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from crudman import Crudman, CrudmanOptions, crud_router
from app.models import Company

engine = create_async_engine("sqlite+aiosqlite:///./app.db")
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def get_session():
    async with SessionLocal() as session:
        yield session

app = FastAPI()
Crudman.init(app, CrudmanOptions(session_dependency=get_session))
```

### 3) Mount the CRUD

```python
app.include_router(crud_router(Company))                  # /companies
app.include_router(crud_router(Company), prefix="/api")   # /api/companies
```

## crud_router

```python
crud_router(
    model,              # required: SQLAlchemy model (or a list of models)
    section=None,       # optional: defaults to the model's table name
    config=None,        # optional: Section(...) or dict with settings
    *,
    path=None,          # default "/{section}"; "" for no segment
    actions=None,       # default ["list", "details", "create", "update", "delete"]
    tags=None,          # default [section]
)
```

```python
crud_router(Company)                              # section "companies" → /companies
crud_router(Company, "orgs")                      # section "orgs"      → /orgs
crud_router(Company, config=companies)            # with settings
crud_router(model=Company, section="orgs")        # keyword form
crud_router(Company, path="/organisations")       # custom URL, section stays "companies"
crud_router(UserProfile, path_style="kebab")      # table user_profiles → /user-profiles
```

> `crud_router(model=Company, "orgs")` is a Python `SyntaxError` (positional after keyword). Use
> `crud_router(Company, "orgs")` or `crud_router(model=Company, section="orgs")`.

Several models in one router (each entry is `Model`, `(Model, "name")`, `(Model, config)` or
`(Model, "name", config)`):

```python
app.include_router(
    crud_router([Tag, Category, (Company, companies), (State, "regions", {"relations": ["country"]})]),
    prefix="/api",
)
# → /api/tags, /api/categories, /api/companies, /api/regions
```

Extra endpoints are opt-in: `actions=["*", "save", "bulk_import", "bulk_delete"]`.

## Sections

A **section** is a named CRUD resource: a model plus settings. Settings resolve in three layers, and the
later layer wins:

```
CrudmanOptions.defaults  →  section top-level keys  →  section.<action> block
```

Write a section as a typed object (IDE autocompletion) or a plain dict. Both are validated at startup.

```python
# app/crud/companies.py
from crudman import Section, ListAction, DetailsAction, WriteAction, Keyword, Pagination

companies = Section(
    title="Company",
    attributes={"read": {"exclude": ["secret"]}},           # every action
    required_roles=["admin"],
    list=ListAction(
        filters_whitelist=["name", "is_active", "created_at"],
        sorting_whitelist=["name", "created_at"],
        order_by=[("created_at", "DESC")],
        keyword=Keyword(searchable_fields=["name", "contacts.email"], min_length=2),
        pagination=Pagination(max_per_page=100),
        enable_cache={"ttl": 60},
    ),
    details=DetailsAction(relations=["contacts"]),
    create=WriteAction(fields_for_uniqueness_validation=["name"]),
    update=WriteAction(fields_for_uniqueness_validation=["name"]),
)
```

Section keys (any of these can also go inside an action block):

| Key | Meaning |
| --- | --- |
| `relations` / `get_relations(ctx)` | `"*"` (default) · list · `{"include": [...]}` · `{"exclude": [...]}` |
| `attributes` | `{"read": ..., "write": ...}`, each `"*"` / list / include / exclude |
| `filters_whitelist`, `sorting_whitelist` | default: all root columns |
| `order_by` | default sort when the request sends none |
| `conditions` | fixed `where` added to every query |
| `keyword`, `keyword_param_name` | keyword search |
| `query_param_names`, `pagination` | renames and pagination toggles |
| `record_selection_field` | default `"id"`; also names the path param |
| `fields_for_uniqueness_validation`, `condition_type_for_uniqueness_validation` | uniqueness checks (`"or"` / `"and"`) |
| `required_roles`, `ownership` | access control |
| hooks | see [Hooks](#hooks) |
| `context` | per-request context builder |
| `additional_response` / `get_additional_response` | extra keys merged into `meta` |
| `response_handler`, `custom_implementation` | output shaping / full override |
| `enable_cache` | `True` or `{"ttl": int, "key": fn}` |
| `uploadable`, `upload`, `upload_defaults` | file uploads |
| `session`, `orm`, `validator` | per-section overrides |

## List APIs and pagination (quick reference)

- **Pagination:** `page` (default 1), `perPage` (default 30; alias `per_page`), `paginate=false|0|no` or
  `perPage=0` to return everything (when allowed)
- **Sorting:** `sort.<field>=asc|desc` (repeatable). Default: `created_at DESC`, then primary key
- **Filters:**
  - Equals: `field=value`
  - Like: `field.like=value` (case-insensitive)
  - Ranges: `field.min`, `field.max`, `field.gt`, `field.lt` (numbers or ISO dates)
  - Between: `field.between=start,end`
- **Keyword:** `keyword=acme`

Field names can be sent in camelCase or snake_case: `sort.createdAt` and `sort.created_at` both reach the
`created_at` column.

```text
GET /api/companies?page=2&perPage=20
GET /api/companies?sort.created_at=desc&sort.name=asc
GET /api/companies?name.like=air&created_at.between=2024-01-01,2024-12-31
GET /api/companies?keyword=acme&is_active=true
GET /api/companies?paginate=false
```

Rename any parameter per action:

```python
list=ListAction(query_param_names={"page": "p", "per_page": "pp", "sort_prefix": "order.", "keyword": "q"})
```

## Response format

```json
{
  "data": [ { "id": 1, "name": "Acme Air" } ],
  "errors": [],
  "success": true,
  "pagination": {
    "page": 2, "perPage": 25, "totalItemsCount": 137, "totalPagesCount": 6,
    "isHavingNextPage": true, "isHavingPreviousPage": true
  },
  "filters": [ { "field": "name", "op": "like", "value": "air", "param": "name.like" } ],
  "sorting": [ { "field": "created_at", "order": "DESC" } ]
}
```

Details, create, update and save return `{ "data": {...}, "errors": [], "success": true }`. Delete returns
`{ "data": { "message": "Successfully deleted" }, ... }`. Validation errors return HTTP 400:

```json
{ "data": null, "success": false, "errors": [ { "type": "unique", "field": "email", "message": "email must be unique" } ] }
```

A database constraint violation (duplicate value in a unique column, missing related record) returns HTTP
409 with `{"type": "conflict"}` and rolls back the request.

Override the format globally with `CrudmanOptions(response_formatter=fn)` or per action with
`response_handler=fn`.

## Hooks

All hooks are optional and may be `async`. The subject comes first and `ctx` last.

```python
async def only_my_company(ctx):                         # on_before_action: return False to stop
    if not ctx.identity.get("company_id"):
        return False

async def active_only(stmt, ctx):                       # on_before_query: receives a SQLAlchemy Select
    return stmt.where(Company.is_active.is_(True))

async def add_flag(data, ctx):                          # on_after_fetch
    return data

def final_rules(rules, ctx):                            # get_final_validation_rules
    return {**rules, "name": {"type": "string", "min": 3, "max": 100}}

async def after_validate(errors, ctx): ...              # on_after_validate: return False to stop

async def stamp(result, ctx):                           # on_after_action: return value replaces the response
    return {**result, "servedAt": datetime.utcnow().isoformat()}
```

Execution order:

- **list / details:** `on_before_action` → relations → cache lookup → `on_before_query` → fetch →
  `on_after_fetch` → format → `on_after_action` → cache store
- **create / update / save:** `on_before_action` → uploads → rules → `get_final_validation_rules` →
  `on_before_validate` → validate → uniqueness → `on_after_validate` → write (transaction) → format →
  `on_after_action` → cache invalidation
- **delete:** `on_before_action` → delete → format → `on_after_action` → cache invalidation

## Context (`ctx`)

Every hook receives `ctx`: `service`, `session`, `repository`, `section`, `action`, `model`, `request`,
`identity`, `params`, `query`, `body`, `files`, plus anything you add:

```python
Section(context={"services": {"mailer": Depends(get_mailer)}, "repositories": {"audit": AuditLog}})

async def build_ctx(ctx):
    return {"tenant_id": ctx.request.headers.get("x-tenant-id")}
Section(context=build_ctx)
```

## Custom routes

```python
from crudman import crud, CrudmanService, get_crud

crud.register(Company)                                  # section without auto routes

@router.get("/companies/list")
@crud.list("companies")
async def list_companies(): ...

@router.post("/countries/{country_id}/states")
async def create_state(country_id: int, body: dict, svc: CrudmanService = Depends(get_crud)):
    r = await svc.call_action("states", "save", body={**body, "country_id": country_id})
    return r.to_response()
```

## File uploads

```python
crud_router(Profile, config={"uploadable": {"avatar": "image-avatar"}, "upload_defaults": {"storage": "local"}})
```

Accepts multipart (`avatar=@me.png`) or JSON base64 (`{"avatar": "data:image/png;base64,..."}`).
Shorthand suffixes: `image[]` (array), `image:base64`, `binary:blob`. Storage modes: `filename`,
`filename_in_field`, `base64`, `blob`. Presets: `image`, `image-jpg|png|gif|webp|avif`, `image-avatar`,
`video`, `audio`, `pdf`, `doc`, `spreadsheet`, `csv`, `text`, `xml`, `html`, `json`, `archive`, `binary`,
`any`.

## Caching

```python
CrudmanOptions(cache=CacheOptions(enabled=True, ttl=60, invalidate_lists_on_write=True))
ListAction(enable_cache={"ttl": 30})
```

Writes invalidate only the written section's cache entries. For a shared cache, pass
`CacheOptions(enabled=True, backend=RedisCache(url="redis://..."))` (needs the `redis` extra; not yet tested
against a live server).

## Import / Export

- `x-content-type: csv` (or `Accept: text/csv`, or `?format=csv`) on list/details returns CSV; pagination
  goes into `X-Pagination-Total`, `X-Pagination-Page`, `X-Pagination-PerPage` headers.
- `x-content-type: excel` returns `.xlsx` (needs the `[excel]` extra).
- `POST /{section}/bulk/import` (JSON or CSV) and `POST /{section}/bulk/delete`, opt-in via `actions=`.

## Coming from crudman-nestjs

| crudman-nestjs | crudman-fastapi |
| --- | --- |
| `@UseCrud({ sections: { companies: { model: Company } } })` + `CrudControllerBase('companies')` | `crud_router(Company)` |
| `CrudmanModule.forRoot({...})` | `Crudman.init(app, CrudmanOptions(...))` |
| `@CrudList('companies')` | `@crud.list("companies")` |
| `filtersWhitelist`, `onBeforeAction`, … | `filters_whitelist`, `on_before_action`, … |
| `onBeforeQuery(findOptions, ...)` | `on_before_query(select_stmt, ctx)` |
| fastest-validator rules | Pydantic, or the same rule dicts in `get_final_validation_rules` |
| `UseCrud({ models: [Tag] })` (pluralised class name) | `crud_router([Tag])` (table name) |

## Example app

A runnable FastAPI + SQLAlchemy + SQLite app lives in
[`examples/fastapi_sqlalchemy_sqlite`](examples/fastapi_sqlalchemy_sqlite):

```bash
cd examples/fastapi_sqlalchemy_sqlite
pip install -r requirements.txt
python seed.py
uvicorn app.main:app --reload      # http://localhost:8000/docs
```

## Roadmap

| Phase | Scope | Status |
| --- | --- | --- |
| 1–6 | Query parsing, SQLAlchemy adapter, validation, routing + OpenAPI, hooks/context, access control | ✅ |
| 7 | Cache (memory; Redis adapter untested against a live server) | ✅ |
| 8 | Uploads (local disk; S3 adapter untested against S3) | ✅ |
| 9 | CSV/Excel export, bulk import/delete | ✅ |
| 10 | Example app, docs | ✅ |
| next | PyPI release; sync sessions; model specs without an ORM class | ⏳ |

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest            # unit + end-to-end tests (SQLite)
CRUDMAN_TEST_DATABASE_URL=postgresql+asyncpg://localhost/crudman_test pytest   # same suite on PostgreSQL
ruff check src tests
mypy src
cd website && npm install && npm start   # docs at http://localhost:3000
```

## License

MIT
