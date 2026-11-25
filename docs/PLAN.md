# crudman-fastapi — design and implementation plan

A port of `crudman-nestjs` (v1.4.1) to Python / FastAPI. Same idea: you declare **sections** (a named config that points at a model), and you get list, details, create, update, delete and save endpoints with filters, sorting, pagination, keyword search, relations, validation, hooks, cache, uploads and CSV/Excel export.

The target repo (`jinujd/crudman-fastapi`) currently has only a README, LICENSE and .gitignore, so this starts from scratch.

Revision 2 is based on reading the NestJS **source code**, not only the README: `crudman.service.ts`, `typeorm.adapter.ts`, `query-utils.ts`, the decorators, registry and types, the validator, the storage adapter and the example app. Section 7 lists what the code does, what the README promises without code behind it, and which NestJS bugs we should not copy.

---

## 1. How the NestJS concepts map to Python

| crudman-nestjs | crudman-fastapi | Notes |
| --- | --- | --- |
| TypeORM entity | **SQLAlchemy 2.0** mapped class (SQLModel works too, since it is SQLAlchemy underneath) | `sqlalchemy.inspect(Model)` gives columns, primary keys and relationships, replacing `repo.metadata`. |
| `TypeormAdapter` | `SqlAlchemyAdapter` (async first) | Builds a `select()` statement. `on_before_query` gets that `Select`. |
| `additionalSettings.repo` (an object or `(cfg, ctx) => repo`) | `session=` per section or action (a dependency, or a `(ctx) -> AsyncSession` callable) | For multi-database or tenant-specific sessions. |
| fastest-validator + `ValidationRules` | **Pydantic v2**, plus a small rule-dict layer for parity | Create and update models are generated from the model. `get_final_validation_rules` may return a Pydantic class **or** a fastest-validator-style dict. |
| `@UseCrud({ sections })` + `CrudControllerBase('x')` | `crud_router(Model, "x", config)` that returns an `APIRouter`; only `Model` is required, and the section name defaults to the table name. Optional class-based `CrudController` | |
| `CrudControllerBase(['tags','categories'])` / `UseCrud({ models })` | `crud_router([Tag, Category, (Company, "orgs", cfg)])` | Mounts `/{section}` routes for each model under one prefix. |
| `@CrudList('users')` and the other route decorators | `@crud.list("users")` decorators, or `await crud.list("users", request)` in your own route | |
| `CrudmanModule.forRoot({...})` | `Crudman.init(app, CrudmanOptions(...))` | |
| Global section registry (`__crudman_global_meta`, merged across controllers) | `crudman.registry`: one app-wide map of sections by name | `call_action("states", ...)` works from anywhere. Registering the same name twice with different settings is a startup error, not a silent merge. |
| `ModuleRef` / `DataSource` / `context` | FastAPI `Depends(...)` + a `context=` builder | See section 3.6. |
| `req`, `res` in hooks | a single `ctx: HookContext` (`ctx.request`, `ctx.query`, `ctx.body`, `ctx.params`, `ctx.session`, `ctx.identity`, …) | A hook aborts by returning `False`, returning a `Response`, or raising `HTTPException`. |
| NodeCache | `cachetools.TTLCache` (default), Redis adapter (optional extra) | |
| Multer `AnyFilesInterceptor` | `await request.form()` → `UploadFile` | |
| `@nestjs/swagger` + `enhanceCrudSwaggerDocument` + `generateOpenApiSchemaFromEntity` | Built into FastAPI, plus `crudman.openapi.schema_for(Model)` | The schemas come from the generated Pydantic models. No separate post-processing step is needed. |
| `exceljs` | `openpyxl` (optional extra) | CSV uses the stdlib `csv` module. |
| `image-size` (avatar dimension check) | `Pillow` (optional extra) | |

**Wire compatibility:** existing front-ends keep working. These stay the same:

- **Query params:** `page`, `perPage`/`per_page`, `paginate`, `sort.<field>`, `.like/.min/.max/.gt/.lt/.between`, `keyword`, `?format=csv`
- **Headers:** `x-content-type`, `x-file-url`, `X-Pagination-*`
- **Envelope keys:** `data`, `errors`, `success`, `meta`, `pagination.totalItemsCount`, `isHavingNextPage`, `filters[].param`, …
- **Status codes**

Python-side config uses snake_case (`filters_whitelist`, `on_before_action`).

---

## 2. Package layout

```
crudman-fastapi/
├─ pyproject.toml              # build: hatchling; tooling: uv, ruff, mypy, pytest
├─ src/crudman/
│  ├─ __init__.py              # public API re-exports
│  ├─ options.py               # CrudmanOptions, Section, ListAction, DetailsAction, WriteAction, DeleteAction …
│  ├─ registry.py              # global options + section registry (deep-merge on re-register)
│  ├─ service.py               # CrudmanService — framework-agnostic core
│  ├─ routing.py               # crud_router(), CrudController, @crud.<action> decorators
│  ├─ context.py               # HookContext, CrudRequest, CrudResult, context builder
│  ├─ query.py                 # port of query-utils.ts
│  ├─ response.py              # default_response_formatter + envelope models
│  ├─ negotiation.py           # json / csv / excel output, x-file-url
│  ├─ schemas.py               # model → Pydantic create/update/read models; rule-dict → Pydantic
│  ├─ openapi.py               # schema_for(Model), request-body / param docs
│  ├─ adapters/orm/{base,sqlalchemy}.py
│  ├─ adapters/validation/{base,pydantic}.py
│  ├─ cache/{base,memory,redis}.py
│  ├─ uploads/{presets,shorthand,processor}.py, uploads/storage/{local,s3}.py
│  ├─ export/{csv,excel}.py
│  └─ bulk.py
├─ tests/                      # unit tests (ported from the vitest suite) + e2e tests (ported from the example's e2e suite)
└─ examples/fastapi_sqlalchemy_sqlite/   # mirror of examples/nest-typeorm-sqlite
```

Dependencies: `fastapi>=0.115`, `sqlalchemy>=2.0`, `pydantic>=2.7`, `cachetools`.
Optional extras: `[uploads]` (python-multipart), `[images]` (Pillow), `[excel]` (openpyxl), `[s3]` (aioboto3), `[redis]` (redis).

---

## 3. How you define a CRUD

Defining a CRUD always takes the same four steps:

1. **Model.** A plain SQLAlchemy class.
2. **Global setup.** `Crudman.init(...)`, done once.
3. **Section.** A config object that says *what* the CRUD does for a model.
4. **Mount.** Decide *where* the routes live: auto router, class, decorators or your own handlers.

### 3.1 Step 1: the model

```python
# app/models.py
from datetime import datetime
from sqlalchemy import ForeignKey, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase): ...

class Country(Base):
    __tablename__ = "countries"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    states: Mapped[list["State"]] = relationship(back_populates="country")

class State(Base):
    __tablename__ = "states"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    country_id: Mapped[int] = mapped_column(ForeignKey("countries.id"))
    country: Mapped[Country] = relationship(back_populates="states")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
```

Crudman derives the following from the model, so you rarely configure them:

- **Validation:** `String(100)` becomes `max_length=100`. A non-nullable column with no default becomes required on create. Primary keys, server defaults and `created_at`/`updated_at`/`deleted_at` are excluded from writes.
- **Filter and sort whitelist:** all root columns.
- **Relations:** all relationships, eager-loaded.
- **Default sort:** `created_at DESC, id DESC` if a `created_at` column exists, otherwise `id DESC`. This matches the NestJS adapter.
- **OpenAPI schemas.**

### 3.2 Step 2: global setup (once, in `main.py`)

```python
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from crudman import Crudman, CrudmanOptions, CacheOptions, LocalStorage

engine = create_async_engine("sqlite+aiosqlite:///./app.db")
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def get_session():
    async with SessionLocal() as session:
        yield session

app = FastAPI()

Crudman.init(app, CrudmanOptions(
    session_dependency=get_session,                 # required
    update_method="patch",                          # "patch" (default) | "put"
    throw_on_error=False,                           # False → always return the envelope
    cache=CacheOptions(enabled=True, ttl=60, invalidate_lists_on_write=True),
    defaults={"attributes": {"write": {"exclude": ["id", "created_at", "updated_at"]}}},
    identity_accessor=lambda request: getattr(request.state, "user", None) or {},
    role_checker=lambda identity, roles: not roles or identity.get("role") in roles,
    export_content_types=["json", "csv", "excel"],
    default_file_storage="local",
    file_storages={"local": LocalStorage(dest="uploads", public_base_url="http://localhost:8000/uploads")},
    upload_response={"file_field_mode": "filename_in_field", "include_base_urls_on": ["list", "details"]},
    openapi={"request_body_content_types": ["json", "form", "multipart"], "include_relations_in_write_body": False},
))
```

### 3.3 Step 3: the section (what the CRUD does)

A section is a model plus optional settings. **Settings resolve in three layers, and the later layer wins:**

```
CrudmanOptions.defaults   →   section top-level keys   →   section.<action> block
(all sections)                (every action of it)          (list / details / create / update / save / delete)
```

This matches the NestJS runtime, where `actionCfg = {...section, ...section[action]}`. Note that the NestJS README shows a `common:` key, but the NestJS code never reads it. We accept `common` as an alias for top-level keys, so README examples still work.

Sections can be written as a **plain dict**, which is closest to NestJS, or as **typed objects**, which give IDE autocompletion. Both are validated into the same `Section` model at startup, so a typo such as `filter_whitelist` fails at boot, not at request time.

```python
# app/crud/companies.py — one file per section, like crud/users.section.ts in the NestJS example
from crudman import Section, ListAction, DetailsAction, WriteAction, Keyword, Pagination

companies = Section(                                          # model comes from crud_router(Company, config=companies)
    title="Company", description="Companies CRUD",           # OpenAPI schema title and description
    # ── top-level: applies to every action ──
    attributes={"read": {"exclude": ["secret"]}},
    relations={"exclude": ["audit_logs"]},
    record_selection_field="id",                              # e.g. "slug" → routes become /{slug}
    required_roles=["admin"],
    # ── per action ──
    list=ListAction(
        filters_whitelist=["name", "is_active", "created_at"],
        sorting_whitelist=["name", "created_at"],
        order_by=[("created_at", "DESC")],
        keyword=Keyword(searchable_fields=["name", "contacts.email"], min_length=2, max_relation_depth=2),
        pagination=Pagination(max_per_page=100, is_disable_allowed=True, is_default_enabled=True),
        query_param_names={"page": "p", "per_page": "pp", "keyword": "q"},   # optional renames
        enable_cache={"ttl": 60},
    ),
    details=DetailsAction(relations=["contacts"], enable_cache=True),
    create=WriteAction(fields_for_uniqueness_validation=["name"]),
    update=WriteAction(fields_for_uniqueness_validation=["name"]),
)

# The same section as a plain dict (also valid):
companies_dict = {
    "list": {"filters_whitelist": ["name", "is_active"], "keyword": {"searchable_fields": ["name"]}},
    "create": {"fields_for_uniqueness_validation": ["name"]},
}
```

When a section is mounted with `crud_router(Company, config=companies)`, the `model` key is optional, because the model comes from the first argument. If you set both and they differ, startup fails.

**Section keys** (any of these can also go inside an action block, except `model`):

| Key | Meaning |
| --- | --- |
| `model` | SQLAlchemy class. Optional when passed as the first argument of `crud_router` / `crud.register` |
| `title`, `description` | OpenAPI schema title and description |
| `relations` / `get_relations(ctx)` | `"*"` (default) · `["a","b"]` · `{"include": [...]}` · `{"exclude": [...]}` |
| `attributes` | `{"read": ..., "write": ...}`, each `"*"` / list / include / exclude |
| `filters_whitelist`, `sorting_whitelist` | default: all root columns |
| `order_by` | default sort when the request sends none |
| `conditions` | fixed `where` applied to every query, e.g. `Company.is_active.is_(True)` or `{"is_active": True}` |
| `keyword`, `keyword_param_name` | keyword search config |
| `query_param_names`, `pagination` | renames and pagination toggles |
| `record_selection_field` | default `"id"`; also names the path param |
| `fields_for_uniqueness_validation`, `condition_type_for_uniqueness_validation` | `"or"` (default) / `"and"` |
| `required_roles`, `ownership={"field": "user_id"}` | access control (see 7.2) |
| `on_before_action`, `on_before_query`, `on_after_fetch`, `on_before_validate`, `get_final_validation_rules`, `on_after_validate`, `on_after_action` | hooks |
| `context` | per-request context builder (3.6) |
| `additional_response` / `get_additional_response` | extra keys merged into `meta` |
| `response_handler`, `custom_implementation` | per-action output shaping or full override |
| `enable_cache` | `True` or `{"ttl": int, "key": fn}` |
| `uploadable`, `upload`, `upload_defaults` | file uploads (3.8) |
| `session`, `orm`, `validator` | per-section overrides (multi-DB, custom adapters) |
| `openapi={"enabled": False, "tags": [...]}` | per-section docs control |

### 3.4 Step 4: mount it (where the routes live)

#### The `crud_router` signature

```python
def crud_router(
    model: type | list,                    # 1st, required: the SQLAlchemy model (or a list, see C)
    section: str | None = None,            # 2nd, optional: defaults to the model's table name
    config: Section | dict | None = None,  # 3rd, optional: the section settings from 3.3
    *,
    path: str | None = None,               # default "/" + section (after path_style)
    actions: list[str] | None = None,      # default: list, details, create, update, delete
    tags: list[str] | None = None,         # default: [section]
) -> APIRouter: ...
```

The **model comes first, and it is the only required argument**. The section name is optional. When you leave it out, crudman uses the model's **table name**, read with `sqlalchemy.inspect(Model).local_table.name`, which works for both `__tablename__` and `__table__`. There is no pluralisation guessing as in NestJS: your table name *is* the section name and the URL.

```python
app.include_router(crud_router(Company))                 # section "companies" (from __tablename__) → /companies
app.include_router(crud_router(Company, "orgs"))         # section "orgs" → /orgs
app.include_router(crud_router(model=Company))           # keyword form, same as the first line
app.include_router(crud_router(model=Company, section="orgs"))
```

> Python note: `crud_router(model=Company, "companies")` is a **SyntaxError**, because a positional argument cannot follow a keyword argument. Use `crud_router(Company, "companies")` or `crud_router(model=Company, section="companies")`.

Settings go in the third argument. When the model comes from the first argument, the `model` key inside `Section` is not needed:

```python
app.include_router(crud_router(Company, config=companies))            # companies = Section(list=..., create=...)
app.include_router(crud_router(Company, "companies", companies))      # same, fully positional
app.include_router(crud_router(Company, config={"create": {"fields_for_uniqueness_validation": ["name"]}}))
```

#### Section name and URL path

| Model | Section name (default) | Path (default) |
| --- | --- | --- |
| `__tablename__ = "companies"` | `companies` | `/companies` |
| `__tablename__ = "user_profiles"` | `user_profiles` | `/user_profiles`; `/user-profiles` with `path_style="kebab"` |
| SQLModel `class Company(SQLModel, table=True)` | `company` (SQLModel's default table name) | `/company` |

- **Where the section name is used:** in `@crud.list("companies")`, `call_action("companies", ...)`, cache keys and the OpenAPI operation ids (`companies_list`).
- **Path:** `path_style` (`"kebab"`, `"snake"`, `"camel"`, `"pascal"`; set per call or in `CrudmanOptions`) changes only the URL path, not the section name. To set a path directly, pass `path="/organisations"`.
- **Duplicate section names:** if two routers end up with the same section name, for example the same model mounted twice, startup fails with an error asking you to pass an explicit section name. Silently merging configs, as NestJS does, would mix two different setups together.

#### A prefix is optional

| You write | Routes |
| --- | --- |
| `app.include_router(crud_router(Company))` | `/companies`, `/companies/{id}` |
| `app.include_router(crud_router(Company), prefix="/api")` | `/api/companies`, … |
| `crud_router(Company, path="/orgs")` | `/orgs`, … |
| `crud_router(Company, path="")` | `/`, `/{id}`: you supply the full path in `prefix` (NestJS style) |
| `CrudmanOptions(route_prefix="/api")` | `/api` in front of every crud router |

#### A. The simplest CRUD (all defaults)

```python
Crudman.init(app, CrudmanOptions(session_dependency=get_session))
app.include_router(crud_router(Company))
```

Routes produced (the path param name follows `record_selection_field`):

| Method | Path | Action | Default status |
| --- | --- | --- | --- |
| GET | `/companies` | list | 200 |
| GET | `/companies/{id}` | details | 200 |
| POST | `/companies` | create | 200 (NestJS parity; `strict_status=True` → 201) |
| PATCH (or PUT) | `/companies/{id}` | update | 200 |
| DELETE | `/companies/{id}` | delete | 200 |

Opt-in extras: `crud_router(Company, actions=["*", "save", "bulk_import", "bulk_delete"])` adds `POST /companies/save`, `/companies/bulk/import` and `/companies/bulk/delete`. To expose only some actions: `actions=["list", "details"]`.

#### B. With settings

```python
from app.crud.companies import companies                   # Section(...) from 3.3, no model key needed

app.include_router(crud_router(Company, config=companies), prefix="/api")
```

#### C. Several models in one router

This equals `CrudControllerBase(['tags','categories'])` / `UseCrud({ models })`. Pass a list as the first argument. Each entry is either a model or a tuple in the same order as the single-model call: `(Model)`, `(Model, "section")`, `(Model, "section", config)`, or `(Model, config)`.

```python
app.include_router(
    crud_router([
        Tag,                                                         # → /tags        (table "tags")
        Category,                                                    # → /categories
        (Company, {"attributes": {"read": {"exclude": ["secret"]}}}),# → /companies, with settings
        (State, "regions", {"relations": {"include": ["country"]}}), # → /regions,  renamed section
    ], path_style="kebab"),
    prefix="/api",
)
```

#### D. Class-based, for people coming from the NestJS version

```python
from crudman import CrudController

class CompaniesController(CrudController, model=Company):                     # section = table name
    pass

class OrgsController(CrudController, model=Company, section="orgs", config=companies):
    pass

app.include_router(CompaniesController.router, prefix="/api")
```

#### E. Custom paths with decorators

This equals `@CrudList('companies')` on a custom path. The section must be registered first. `crud.register` has the same argument order as `crud_router` but mounts no routes:

```python
from fastapi import APIRouter
from crudman import crud

crud.register(Company)                           # section "companies", no auto routes
crud.register(Company, "orgs", companies)        # or with a name and settings

router = APIRouter(prefix="/api/custom")

@router.get("/companies/list")
@crud.list("companies")
async def list_companies(): ...                 # the body is ignored; crudman handles the request

@router.patch("/company/update/{id}")
@crud.update("companies")
async def update_company(): ...
```

#### F. Your own handler that calls the service

This equals injecting `CrudmanService`.

```python
from fastapi import Depends, Request
from crudman import CrudmanService, get_crud

@router.get("/companies/{id}/summary")
async def company_summary(id: int, request: Request, svc: CrudmanService = Depends(get_crud)):
    result = await svc.details("companies", request)        # CrudResult(status_code, body, headers)
    result.body["data"]["display"] = result.body["data"]["name"].upper()
    return result.to_response()

@router.post("/countries/{country_id}/states")
async def create_state(country_id: int, body: dict, svc: CrudmanService = Depends(get_crud)):
    r = await svc.call_action("states", "save", body={"name": body["name"], "country_id": country_id})
    return r.to_response()
```

### 3.5 Hooks

Every hook is a plain function or an `async def`. The subject comes first and `ctx` comes last. A hook defined at section level applies to every action; a hook in an action block replaces it for that action.

```python
from sqlalchemy import Select
from crudman import HookContext

async def only_my_company(ctx: HookContext):                       # on_before_action
    cid = ctx.identity.get("company_id")
    if not cid:
        return False                                  # stop → 403 envelope (or raise HTTPException)
    ctx.query["companyId"] = str(cid)

async def active_only(stmt: Select, ctx: HookContext) -> Select:  # on_before_query
    return stmt.where(Company.is_active.is_(True))

async def tag_rows(data, ctx: HookContext):                       # on_after_fetch (list → list, details → object)
    return [{**r, "tag": "USER"} for r in data] if isinstance(data, list) else data

def final_rules(rules, ctx: HookContext):                         # get_final_validation_rules
    # Either return a Pydantic model class, or edit the generated rule dict (fastest-validator style):
    return {**rules, "name": {"type": "string", "min": 3, "max": 100}, "revenue": {"type": "number", "min": 0, "optional": True}}

async def before_validate(rules, ctx: HookContext): ...           # on_before_validate → False stops
async def after_validate(errors: list, ctx: HookContext): ...     # on_after_validate → append errors / return False

async def stamp(result: dict, ctx: HookContext) -> dict:          # on_after_action → return value replaces the response
    return {**result, "servedAt": datetime.utcnow().isoformat()}
```

**Execution order.** We follow the order the NestJS README documents. For writes, this is safer than what the NestJS code does (see 7.3).

- **list / details:** `on_before_action` → resolve relations → cache lookup → `on_before_query` → fetch → `on_after_fetch` → format → `additional_response` → `on_after_action` → cache store → negotiate (json / csv / excel)
- **create / update / save:** `on_before_action` → process uploads → generate rules → `get_final_validation_rules` → `on_before_validate` → validate → uniqueness check → `on_after_validate` → write (in a transaction) → format → `additional_response` → `on_after_action` → cache invalidation
- **delete:** `on_before_action` → delete (404 if missing) → format → `on_after_action` → cache invalidation

### 3.6 Context (`ctx`)

`ctx` is built for each request.

**Reserved keys, filled automatically.** Your `context` builder cannot overwrite them:

| Key | Contents |
| --- | --- |
| `service` | the `CrudmanService` |
| `session` | the current `AsyncSession` |
| `repository` | a small helper bound to the section's model: `get`, `find`, `exists`, `add` |
| `section`, `action`, `model` | what is running |
| `request` | the incoming request |
| `identity` | from `identity_accessor` |
| `params`, `query`, `body`, `files` | parsed request parts |

**Keys you add:** `services`, `repositories`, and any custom keys. NestJS supports three forms, and all three carry over. Section-level context is merged first, then action-level, as in NestJS.

```python
# 1) Dict form. Values may be Depends(...) (resolved by FastAPI) or plain objects.
context={"services": {"mailer": Depends(get_mailer)}, "repositories": {"audit": AuditLog}}

# 2) Function form. Async is allowed; it receives ctx and returns extras.
async def build_ctx(ctx):
    return {"services": {"flags": FlagService()}, "tenant_id": ctx.request.headers.get("x-tenant-id")}
context=build_ctx

# 3) Dict with callable parts plus a get_hook_context function.
context={"services": lambda ctx: {...}, "get_hook_context": build_ctx}
```

`repositories={"audit": AuditLog}` gives you `ctx.repositories["audit"]`, a repository helper bound to the same session and transaction.

### 3.7 Response format

The default envelope is identical to NestJS:

```jsonc
// list
{ "data": [...], "errors": [], "success": true,
  "pagination": { "page": 1, "perPage": 30, "totalItemsCount": 0, "totalPagesCount": 0, "isHavingNextPage": false, "isHavingPreviousPage": false },
  "filters": [{ "field": "name", "op": "like", "value": "air", "param": "name.like" }],
  "sorting": [{ "field": "createdAt", "order": "DESC" }],
  "meta": { ... } }
// details / create / update / save
{ "data": {...} | null, "errors": [], "success": true, "meta": {...} }
// delete
{ "data": { "message": "Successfully deleted" }, "errors": [], "success": true }
// validation failure → HTTP 400
{ "data": null, "success": false, "errors": [{ "type": "unique", "field": "email", "message": "email must be unique" }] }
```

You can override the format globally with `CrudmanOptions(response_formatter=fn)` or per action with `response_handler=fn`.

### 3.8 Uploads (same shorthand as NestJS)

```python
profiles = Section(model=Profile, uploadable={"avatar": "image-avatar"}, upload_defaults={"storage": "local"})
gallery  = Section(model=Post, uploadable={"photos": "image-jpg[]", "thumb": "image:base64", "raw": "binary:blob"})
docs     = Section(model=Doc, upload={"map": [
    UploadMap(source_field="file", storage_mode="filename", storage="s3",
              target_field={"key": "file_key", "url": "file_url"}, type_hint="pdf",
              validators={"max_size_mb": 10}),
]})
```

These all behave as in NestJS:

- **Shorthand suffixes:** `[]` means an array, `:base64` and `:blob` pick the storage mode, and the default mode is filename.
- **Storage modes:** `filename`, `filename_in_field`, `base64`, `blob` (a `{blob, mime}` pair of columns).
- **`file_field_mode`:** `filename_in_field` writes the filename into the field itself; `key_url_fields` writes `<field>Key` and `<field>Url`.
- **Required file:** a single filename-mode upload is required on create.
- **Validator precedence:** type preset < global `upload_limits` < section `upload_defaults.validators` < the rule's own `validators`.
- **Presets:** the full list, i.e. image(-jpg/png/gif/webp/avif), the `-avatar` variants (128–4096 px, about 1:1 ±20%), video(-mp4/webm/ogg/short), audio, pdf, doc, spreadsheet(-csv/xls/xlsx), text, csv, xml, html, json, archive, binary, any.
- **Error types:** `required`, `fileSize`, `fileExtension`, `fileMime`, `imageDimensions`, `imageAspect`.
- **Base URLs:** `meta.baseUrls` is added on the actions listed in `include_base_urls_on`.
- **`x-file-url: full|key_only`:** echoed back as `meta.fileUrlMode`.

---

## 4. Key design decisions

1. **The core service is framework-agnostic.** It takes a `CrudRequest` and returns a `CrudResult(status_code, body, headers)`. FastAPI is only an outer layer. This makes `call_action` easy, without the fake `res` capture object NestJS uses, and makes the core testable without HTTP.
2. **Body validation is done by crudman, not FastAPI.** Hooks can change the rules per request, and errors keep the `{type, field, message}` shape with HTTP 400. OpenAPI still documents the body through `openapi_extra`.
3. **Response models are for docs only.** Routes use `responses={200: {"model": ListEnvelope[CompanyRead]}}` and return a `JSONResponse`, so formatters and `on_after_action` are never filtered by FastAPI.
4. **Relations are eager-loaded explicitly** with `selectinload`. In async SQLAlchemy, a lazy load raises `MissingGreenlet`.
5. **Generated endpoints get real FastAPI dependencies.** Their signatures include `session = Depends(...)` plus the `context` dependencies, so auth guards and `dependency_overrides` work.
6. **One query path.** The list query is built as a single `Select` with filters, keyword, conditions, attributes and sort, and `on_before_query` sees that final statement. NestJS has two code paths that disagree with each other (see 7.3).
7. **Writes are transactional.** Each write action runs in `session.begin()`, or in a savepoint if a transaction is already open, so `call_action` inside a hook takes part in the same transaction.
8. **Fail at startup, not at request time.** Section configs are validated when `crud_router` or `Crudman.init` runs: unknown keys, whitelist fields missing from the model, bad relation names.

---

## 5. Implementation phases

| # | Phase | What gets built | Done when |
| --- | --- | --- | --- |
| 0 | Scaffolding | pyproject (hatchling), uv, ruff, mypy, pytest, GitHub Actions CI (3.10–3.13) | CI is green |
| 1 | Core types + query parser | `options.py` (all keys in 3.3, with `common` alias and 3-layer merge), `registry.py` (deep-merge), `context.py`, `query.py` (port of `query-utils.ts`: camel/snake normalisation, `query_param_names`, sort defaults to desc, `per_page=0`/`paginate=false`, `max_per_page`, `is_default_enabled`), `response.py` | `query-utils.test.ts` + `response-formatter.test.ts` ported and passing |
| 2 | SQLAlchemy adapter | list / details / create / update / delete / save; default sort; `order_by`; `conditions`; relations + `selectinload`; read attributes; keyword with dot paths (depth ≤ 3, `DISTINCT` on joins); uniqueness (or/and, excludes current record, only for fields present in the body); 404 for missing records | `typeorm-adapter.test.ts` ported and passing on aiosqlite |
| 3 | Validation | model → Pydantic create/update models (types, nullable, length, defaults; PK, server defaults and `created_at`/`updated_at`/`deleted_at` excluded); create rejects unknown fields, update drops them; non-null strings need min length 1 on create; rule-dict → Pydantic converter; write include/exclude | `validator-adapter.test.ts` ported |
| 4 | Routing + OpenAPI | `crud_router(model, section=None, config=None)` (section defaults to the table name; a list for multi-model), `crud.register`, duplicate-name check, `CrudController`, `@crud.<action>`, `actions=` filter, `update_method`, path param named from `record_selection_field`, typed signatures, `openapi_extra` (json/form/multipart bodies, query params, `x-content-type` header), envelope docs, `title`/`description`/tags | e2e `companies` + `shorthand` tests ported |
| 5 | Hooks, context, errors | all 7 hooks in the documented order, `on_after_action` return value replaces the response, 3 context forms + reserved keys, `additional_response`, `response_handler`, `custom_implementation`, `call_action`, `throw_on_error`, `strict_status` | e2e `ctx-demo` test ported |
| 6 | Access control | `identity_accessor`, `role_checker`, `required_roles`, `ownership` (filters reads, checks writes) | new tests. NestJS declares this but never enforces it |
| **MVP → release 0.1.0 on PyPI** | | | |
| 7 | Cache | protocol, TTLCache default, per-action `enable_cache`, custom key, **per-section** invalidation (tag keys by section instead of flushing everything), Redis extra | cache tests |
| 8 | Uploads | everything in 3.8; Local + S3 storage; `delete_on_replace`, `key_pattern`, `mode="append"` (declared but unused in NestJS) | e2e `uploads` + `profiles-upload` tests ported |
| 9 | Export + bulk | negotiation via `x-content-type` header, `Accept`, `?format=` or `?x-content-type=`; CSV/Excel for list and details; `X-Pagination-*`/`X-Filters`/`X-Sorting` headers; JSON error if openpyxl is missing; bulk import/delete with policies, `batch_size`, `dry_run`, `stop_on_error` (bulk is decorator-only in NestJS) | export/bulk tests |
| 10 | Shorthand + docs | `path_style`, map form, `section` rename, migration guide NestJS → FastAPI, example app + seed | example runs |
| 11 | Later | sync `Session` support, model specs without an ORM class, Tortoise/Beanie adapters | |

Phases 1–3 can be built mostly in parallel once phase 0 is in.

---

## 6. Gotchas to design for up front

- **Async lazy loading:** only serialize attributes that are actually loaded. Check `inspect(obj).unloaded`.
- **Field naming:** Python models use `created_at`, but existing NestJS front-ends send `sort.createdAt` and expect `createdAt` in responses. Add `field_alias="camel"`: it accepts camelCase query fields, camel-cases output keys, and accepts camelCase input bodies.
- **Count with joins:** use `select(func.count()).select_from(stmt.order_by(None).subquery())`, plus `DISTINCT` when keyword search joins one-to-many relations.
- **Case-insensitive search:** `ilike` on Postgres; `lower(col).like(lower(:kw))` elsewhere.
- **OpenAPI:** give every route a unique `operation_id` (`{section}_{action}`). Build schema components once per section.
- **ID casting:** the path param is converted to the PK column's Python type. NestJS uses `Number(v)`, which breaks on UUID and string keys.

---

## 7. Gap analysis against the NestJS source

### 7.1 Present in NestJS code and missing from revision 1 of this plan (now added)

| Feature (NestJS location) | Where it is now in this plan |
| --- | --- |
| Section `title` / `description` used for Swagger schemas (`CrudSectionConfig`) | 3.3 |
| Per-section `validator` / `orm` override; `additionalSettings.repo` as object or `(cfg, ctx)` function | `session` / `orm` / `validator` keys, 3.3 |
| Context: function form, `services`/`repositories` as functions, `getHookContext`, custom top-level keys, reserved keys protected, section → action merge | 3.6 |
| Settings layering `{...section, ...section[action]}`; the README's `common:` key is not read by the code | 3.3 (`common` accepted as an alias) |
| Default sort `createdAt DESC, pk DESC`; default `perPage` 30; empty sort value means desc | 3.1, phase 1–2 |
| `filters[].param` in responses; `is_default_enabled` pagination flag; `keywordParamName` | 3.7, phase 1 |
| Validator rules: exclude PK / generated / `created_at` / `modified_at` / `deleted_at`; create rejects unknown fields, update drops them; non-null string min length 1; rule entries default to type string | phase 3 |
| `getFinalValidationRules` returning a fastest-validator-style dict | rule-dict converter, 3.5 |
| Upload shorthand `[]` / `:base64` / `:blob`; `fileFieldMode`; `includeBaseUrlsOn`; `x-file-url`; required file on create; validator precedence; full preset list; avatar dimension rules; error type names | 3.8 |
| Content negotiation via `Accept`, `?format=`, `?x-content-type=`, aliases `xlsx`/`sheet`; details export; `X-Filters` / `X-Sorting` headers; JSON error when Excel is missing | phase 9 |
| `throwOnError` (defaults to **true** in code: `v !== false`) | `throw_on_error`, phase 5 |
| Status codes: create/save return 200 (`HttpCode(200)`); delete returns `{message: "Successfully deleted"}` | 3.4, 3.7 |
| `additionalResponse` + `getAdditionalResponse` merged into `meta` | 3.3 |
| `CrudControllerBase([...])` / `'*'` multi-section mounting; shorthand map form; section rename | 3.4 C. Pluralisation is replaced by the table name |
| Global section registry merged across controllers (deep-merge fix from 1.4.1) | registry, section 1 |
| Swagger options `requestBodyContentTypes`, `requestBodySchemaMode`, `includeRelationsInWriteBody`, `swaggerMeta`, per-section `swagger.enabled` | `openapi=` options, 3.2 / 3.3 |
| `call_action` with a plain request-like object (the custom controller example uses `{params, body}`) | 3.4 F |

### 7.2 Documented in the NestJS README but not implemented in its code

We implement each of these properly, because the README already promises them to users.

| Feature | Status in NestJS | Plan |
| --- | --- | --- |
| `requiredRoles`, `ownership`, `identityAccessor`, `roleChecker` | types and registry getters only, never enforced | phase 6 |
| `responseHandler` (per action) | type only | phase 5 |
| `customImplementation` | type only | phase 5 |
| `orderBy` | type only; the adapter ignores it | phase 2 |
| `conditions` | type only | phase 2 |
| Bulk import / bulk delete | route decorators exist, no service method | phase 9 |
| `pathStyle` in shorthand defaults | not read | phase 10 |
| Model specs without an entity (`{name, fields}`) | only the name is used | phase 11 |
| S3 storage | interface only, no adapter | phase 8 |
| `uploadDefaults.dir` / `keyPrefix` / `deleteOnReplace`, `keyPattern`, `mode: 'append'`, per-rule `sources`, `allowRequestOverride` | declared, unused | phase 8 |
| `video-short` checks | stub | later (needs ffprobe) |
| Sequelize / Joi / Zod adapters | "preview" in docs | not applicable; adapter protocols leave room for others |
| `onAfterAction` returning a new object replaces the response | the return value is ignored; only mutation works | phase 5 |

### 7.3 NestJS behaviour we will deliberately **not** copy

| NestJS behaviour | Why it's a problem | crudman-fastapi |
| --- | --- | --- |
| Writes run uploads + validation **before** `onBeforeAction` | Files are saved to disk even when the hook then blocks the request; contradicts the documented order | `on_before_action` runs first |
| Keyword search is combined with filters as `{AND: [...]}`, then converted to an array | TypeORM reads an array as **OR**, so `?keyword=x&isActive=true` ignores `isActive` | Filters and keyword are always ANDed |
| Any `.like` or range filter switches to a second QueryBuilder path | That path drops keyword search, `onBeforeQuery` changes and `attributes` | One `Select` path |
| Uniqueness check on PATCH builds `where {email: undefined}` when the field is not in the body | Can raise a false "must be unique" error; errors in the check are silently swallowed | Check only fields present in the body; let errors surface |
| Uniqueness "exclude current record" reads `this.metadata`, i.e. the adapter, not the repo | Always assumes the PK is `id` | Use the model's real PK |
| update/delete on a missing id returns `success: true` (`data: null`); details returns HTTP 200 with `success: false` | Clients can't tell "not found" from success | 404 with a `success: false` envelope. Keep the old behaviour behind `strict_status=False` if needed for compatibility |
| Cache hit path skips `additionalResponse` / `baseUrls`; writes flush the **entire** cache | Inconsistent responses; one write evicts every section | Same pipeline on cache hits; invalidate per section |
| `save` decides create vs update with `params.id \|\| body.id`, ignoring `recordSelectionField` | Breaks slug-keyed sections | Use `record_selection_field` |
| `castId` uses `Number(v)` | Breaks UUID and string keys | Cast to the PK column type |
| Leftover `console.log` in `buildUniquenessWhere` | Noise in production logs | Use the standard `logging` module |

---

## 8. Final feature list (crudman-fastapi 1.0)

Status key: ✅ built and unit-tested in the repo today · 🔜 planned (phase number in brackets).

### Defining CRUDs
- 🔜 `crud_router(Model)`: the model is the only required argument; the section name defaults to the table name [4]
- 🔜 `crud_router(Model, "name", config)`: optional section name and settings, positional or keyword [4]
- 🔜 Multi-model routers: `crud_router([Tag, Category, (Company, "orgs", cfg)])` [4]
- 🔜 Class-based `CrudController` for people coming from NestJS [4]
- 🔜 `crud.register(...)` + `@crud.list/details/create/update/delete/save("name")` on custom paths [4]
- 🔜 `CrudmanService` for your own handlers; `call_action(section, action, ...)` across sections [5]
- 🔜 Settings as a typed `Section(...)` or a plain dict, validated at startup [1]
- 🔜 Three settings layers: global defaults → section → action; `common` accepted as an alias [1]
- ✅ Section naming from the table name; `path_style` kebab / snake / camel / pascal; default path `/{section}`
- 🔜 Optional prefix; `route_prefix` global option; `path=` override; `actions=` filter [4]
- 🔜 PATCH (partial update, default) or PUT [4]

### Endpoints
- 🔜 list, details, create, update, delete [2, 4]
- 🔜 save (upsert by `record_selection_field`), opt-in [2]
- 🔜 bulk import (JSON/CSV; policies `upsert`, `insert_only`, `update_only`, `ignore_on_conflict`, `replace`; `batch_size`, `dry_run`, `stop_on_error`) and bulk delete [9]
- 🔜 `record_selection_field` (e.g. slug) also names the path param [2]

### Querying (list)
- ✅ Pagination: `page`, `perPage`/`per_page`, `paginate=false`, `perPage=0`, `max_per_page`, `is_default_enabled`, `is_pagination_enabled`, `is_disable_allowed`
- ✅ Sorting: `sort.<field>=asc|desc`, multi-sort, whitelist, empty value means desc
- ✅ Filters: equals, `.like`, `.min`, `.max`, `.gt`, `.lt`, `.between`; whitelist; `filters[]` echoed with `param`
- ✅ Renameable query params (`query_param_names`); camelCase and snake_case keys both accepted
- 🔜 Keyword search across columns and relation dot paths (depth ≤ 3), case-insensitive by default, `min_length` [2]
- 🔜 Default sort `created_at DESC, pk DESC`; `order_by`; fixed `conditions` [2]
- 🔜 Filters and keyword always ANDed, in a single query path (fixes the NestJS OR bug) [2]

### Data shaping
- 🔜 Relations: `"*"` (default), list, include / exclude, `get_relations(ctx)`; eager-loaded [2]
- 🔜 Attributes: separate read and write include / exclude [2, 3]
- ✅ Standard response envelope (`data`, `errors`, `success`, `pagination`, `filters`, `sorting`, `meta`), identical to NestJS
- 🔜 Global `response_formatter`, per-action `response_handler`, `additional_response` / `get_additional_response` into `meta` [5]
- 🔜 `field_alias="camel"` for front-ends written against the NestJS version [2]

### Validation
- 🔜 Pydantic models generated from the SQLAlchemy model (types, nullability, length, defaults) [3]
- 🔜 Create rejects unknown fields; update drops them; PK and timestamp columns skipped [3]
- 🔜 `get_final_validation_rules` returning a Pydantic class or a fastest-validator-style dict [3]
- 🔜 Uniqueness checks (`or` / `and`), excluding the current record and checking only fields sent [2]
- 🔜 Errors as `{type, field, message}` with HTTP 400 [3]

### Hooks and context
- 🔜 `on_before_action`, `on_before_query` (receives a SQLAlchemy `Select`), `on_after_fetch`, `on_before_validate`, `get_final_validation_rules`, `on_after_validate`, `on_after_action` (its return value replaces the response) [5]
- 🔜 `ctx` with service, session, repository helper, section, action, model, request, identity, params, query, body, files [5]
- 🔜 Context builders: dict (with `Depends`), function, `get_hook_context`; reserved keys protected [5]
- 🔜 `custom_implementation` to fully override an action [5]

### Access control
- 🔜 `identity_accessor`, `role_checker`, `required_roles`, `ownership` (enforced, unlike in NestJS) [6]

### Uploads
- 🔜 Multipart and base64; shorthand `uploadable={"avatar": "image"}` with `[]`, `:base64`, `:blob` [8]
- 🔜 Storage modes `filename`, `filename_in_field`, `base64`, `blob`; Local and S3 storage [8]
- 🔜 About 30 presets (image, avatar, video, audio, pdf, doc, spreadsheet, text, csv, xml, html, json, archive, binary, any) [8]
- 🔜 Size / MIME / extension / avatar dimension checks; `delete_on_replace`, `key_pattern`, append mode [8]
- 🔜 `meta.baseUrls`, `x-file-url: full|key_only` [8]

### Output, cache, docs
- 🔜 CSV and Excel export via `x-content-type`, `Accept` or `?format=`; `X-Pagination-*` headers [9]
- 🔜 TTL cache per action with custom keys; per-section invalidation on writes; Redis adapter [7]
- 🔜 OpenAPI: typed request bodies (json/form/multipart), query params, envelope schemas, tags, operation ids [4]
- 🔜 Error mode `throw_on_error`; `strict_status` (201 on create, 404 on missing) [5]
- 🔜 Transactions around writes, so `call_action` inside hooks shares the transaction [5]
- 🔜 Pluggable adapters: `OrmAdapter`, `ValidatorAdapter`, `CacheAdapter`, `FileStorageAdapter` [1]

### Project
- ✅ README in the crudman-nestjs style
- ✅ Docusaurus documentation site (`website/`)
- ✅ Unit test suite (pytest) for the modules built so far; it grows with each phase
