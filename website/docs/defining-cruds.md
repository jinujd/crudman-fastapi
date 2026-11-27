---
sidebar_position: 3
title: Defining CRUDs
---

# Defining CRUDs

Defining a CRUD always takes four steps:

1. **Model:** a plain SQLAlchemy class.
2. **Global setup:** `Crudman.init(...)`, once.
3. **Section:** what the CRUD does (optional; defaults cover most cases).
4. **Mount:** where the routes live.

Steps 1 and 2 are covered in [Getting started](./getting-started.md). This page covers mounting with
`crud_router(...)`. To define routes with decorators instead (`@Controller`, `@Crud`, `@CrudList`, `@Get`, …),
like crudman-nestjs, see [Controllers](./controllers.md). Both styles share the same engine and settings.

| Style | Looks like | Good for |
| --- | --- | --- |
| `crud_router(Model)` | one function call per resource | resources that only need the standard routes |
| [`@Controller` + `@Crud`](./controllers.md) | a class with decorated methods | per-route auth, custom paths, extra endpoints next to the CRUD |

## `crud_router`

```python
crud_router(
    model,              # required: SQLAlchemy model (or a list of models)
    section=None,       # optional: defaults to the model's table name
    config=None,        # optional: Section(...) or dict with settings
    *,
    path=None,          # default "/{section}"; "" for no segment
    actions=None,       # default ["list", "details", "create", "update", "delete"]
    tags=None,          # default [section]
) -> APIRouter
```

The model comes first and is the only required argument.

```python
app.include_router(crud_router(Company))                      # section "companies" → /companies
app.include_router(crud_router(Company, "orgs"))              # section "orgs"      → /orgs
app.include_router(crud_router(Company, config=companies))    # with settings
app.include_router(crud_router(model=Company, section="orgs"))
```

:::warning Python syntax
`crud_router(model=Company, "orgs")` is a `SyntaxError`, because a positional argument cannot follow a
keyword argument. Use `crud_router(Company, "orgs")` or `crud_router(model=Company, section="orgs")`.
:::

## Section name and URL

When you do not pass a section name, crudman uses the model's **table name**. It works with
`__tablename__`, `__table__` and imperative mappings. There is no pluralisation guessing: your table name
is the section name and the URL.

| Model | Section name | Default path |
| --- | --- | --- |
| `__tablename__ = "companies"` | `companies` | `/companies` |
| `__tablename__ = "user_profiles"` | `user_profiles` | `/user_profiles`, or `/user-profiles` with `path_style="kebab"` |
| SQLModel `class Company(SQLModel, table=True)` | `company` | `/company` |

The section name is what you use in `@crud.list("companies")`, `call_action("companies", ...)`, cache keys
and OpenAPI operation ids. `path_style` (`as_is`, `kebab`, `snake`, `camel`, `pascal`) changes only the URL.

If two routers end up with the same section name (for example the same model mounted twice), startup fails
and asks you to pass an explicit name.

## Prefixes are optional

| You write | Routes |
| --- | --- |
| `crud_router(Company)` | `/companies`, `/companies/{id}` |
| `include_router(crud_router(Company), prefix="/api")` | `/api/companies`, ... |
| `crud_router(Company, path="/orgs")` | `/orgs`, ... |
| `crud_router(Company, path="")` | `/`, `/{id}` (you give the full path in `prefix`) |
| `CrudmanOptions(route_prefix="/api")` | `/api` in front of every crud router |

## Routes produced

| Method | Path | Action | Status |
| --- | --- | --- | --- |
| GET | `/companies` | list | 200 |
| GET | `/companies/{id}` | details | 200 |
| POST | `/companies` | create | 200 (201 with `strict_status=True`) |
| PATCH (or PUT) | `/companies/{id}` | update | 200 |
| DELETE | `/companies/{id}` | delete | 200 |

The path parameter is named after `record_selection_field` (default `id`). Extra endpoints are opt-in:

```python
crud_router(Company, actions=["*", "save", "bulk_import", "bulk_delete"])
# adds POST /companies/save, /companies/bulk/import, /companies/bulk/delete
crud_router(Company, actions=["list", "details"])   # read-only
```

## Several models in one router

Pass a list. Each entry is `Model`, `(Model, "name")`, `(Model, config)` or `(Model, "name", config)`:

```python
app.include_router(
    crud_router([
        Tag,
        Category,
        (Company, {"attributes": {"read": {"exclude": ["secret"]}}}),
        (State, "regions", {"relations": {"include": ["country"]}}),
    ], path_style="kebab"),
    prefix="/api",
)
# → /api/tags, /api/categories, /api/companies, /api/regions
```

## Class-based controllers

Decorator controllers are described on the [Controllers](./controllers.md) page:

```python
@Controller("/api/companies")
@Crud(Company)
class CompaniesController:
    pass
```

The older subclass form still works: `class CompaniesController(CrudController, model=Company): pass`.

## Auth

Routes are public by default. `crud_router(Company, auth="private")`, `private=[...]`, `public=[...]` and
`roles={...}` protect them; see [Authentication](./authentication.md).

## Organising sections in files

```text
app/
  models.py
  crud/
    companies.py     # companies = Section(...)
    users.py
  main.py            # app.include_router(crud_router(Company, config=companies))
```

See [Sections](./sections.md) for everything a section can configure, and
[Custom routes](./custom-routes.md) for decorators and your own handlers.
