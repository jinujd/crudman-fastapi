---
title: Controllers (decorators)
---

# Controllers (decorators)

Controllers define routes with decorators, like crudman-nestjs. They are an alternative to
[`crud_router(...)`](./defining-cruds.md): both use the same engine and the same section settings.

```python
from fastapi import Request
from crudman import Controller, Crud, CrudDelete, CrudDetails, CrudList, CrudResult, Get, Private, Public, Roles
from app.models import Company
from app.crud.companies import companies         # optional Section(...) settings

@Controller("/api/companies", tags=["companies"])
@Private()                                       # every route needs a signed-in user...
@Crud(Company, config=companies)                 # list, details, create, update, delete
class CompaniesController:

    @Public()                                    # ...except this one
    @CrudList()                                  # GET /api/companies
    async def list(self): ...                    # empty body: crudman handles the request

    @Roles("admin")                              # signed in and role "admin"
    @CrudDelete()                                # DELETE /api/companies/{id}
    async def remove(self): ...

    @CrudDetails("/{id}/full")                   # new path for a generated route
    async def details(self, result: CrudResult) -> CrudResult:
        result.body["data"]["display"] = result.body["data"]["name"].upper()
        return result

    @Get("/{id}/summary")                        # your own route
    async def summary(self, id: int, request: Request):
        r = await self.crud.details("companies", request)
        return {"name": r.body["data"]["name"]}


app.include_router(CompaniesController.router)
```

Routes produced:

| Method | Path | Handler | Auth |
| --- | --- | --- | --- |
| GET | `/api/companies` | `list` (decorated) | public |
| GET | `/api/companies/{id}/full` | `details` (decorated, new path) | signed in |
| POST | `/api/companies` | generated create | signed in |
| PATCH | `/api/companies/{id}` | generated update | signed in |
| DELETE | `/api/companies/{id}` | `remove` (decorated) | signed in + `admin` |
| GET | `/api/companies/{id}/summary` | `summary` | signed in |

Auth decorators are explained on the [Authentication](./authentication.md) page. Without them, every route is public.

## Registering controllers

```python
app.include_router(CompaniesController.router)

# or several at once
Crudman.init(app, CrudmanOptions(session_dependency=get_session, controllers=[CompaniesController, UsersController]))
include_controllers(app, [TagsController])        # same thing, any time
```

`.router` is built the first time it is read, so class decorators can be stacked in any order and options from
`Crudman.init` (auth, path style, update method) apply even if the class was defined first.

## Class decorators

| Decorator | Meaning |
| --- | --- |
| `@Controller(prefix="", tags=None, dependencies=None)` | URL prefix, OpenAPI tags (default: class name without `Controller`) and FastAPI dependencies for every route |
| `@Crud(Model, section=None, config=None, path=None, actions=None)` | Register a section (name defaults to the table name) and generate its routes |
| `@Private()`, `@Public()`, `@Roles(...)` | Default auth for every route in the class |

`@Crud` options:

- `config`: a `Section(...)` or dict, exactly as for `crud_router`.
- `actions`: `None` generates list, details, create, update and delete. `["*", "save"]` adds save. `[]` generates
  nothing, so only routes declared with method decorators are mounted.
- `path`: where the section's routes go, relative to the controller prefix. Defaults to `""` for a single `@Crud`,
  and `/{section}` when a controller has several.

## Method decorators

| Decorator | Default path (relative to the section) | Method |
| --- | --- | --- |
| `@CrudList(path=None, section=None)` | `""` | GET |
| `@CrudDetails(...)` | `/{id}` | GET |
| `@CrudCreate(...)` | `""` | POST |
| `@CrudUpdate(...)` | `/{id}` | PATCH (or PUT with `update_method="put"`) |
| `@CrudDelete(...)` | `/{id}` | DELETE |
| `@CrudSave(...)` | `/save` | POST |
| `@CrudBulkImport(...)`, `@CrudBulkDelete(...)` | `/bulk/import`, `/bulk/delete` | POST |
| `@Get(path)`, `@Post`, `@Put`, `@Patch`, `@Delete` | as given | as named |

`/{id}` follows `record_selection_field` (for example `/{slug}`). A custom details, update or delete path must contain
a path parameter.

### Crud method bodies

- **Empty body (`...`):** crudman handles the request; the decorator just places the route and its auth.
- **`result: CrudResult` parameter:** the method receives crudman's result after the action runs. It can modify
  `result.body` and return it, return a new body (dict), or return any FastAPI `Response`.

### Custom routes

`@Get`, `@Post`, `@Put`, `@Patch` and `@Delete` take normal FastAPI parameters (path, query, body models, `Request`,
`Depends`). Extra keyword arguments such as `status_code`, `response_model` or `summary` go to FastAPI. Inside the
method, `self.crud` is a `CrudmanService` bound to the request's session:

```python
@Post("/{id}/states", status_code=201)
async def add_state(self, id: int, body: StateIn):
    return await self.crud.call_action("states", "create", body={"name": body.name, "country_id": id})
```

Returning a `CrudResult` sends it as the response. A successful result uses the route's `status_code` (201 above); an error keeps crudman's status (400, 404, 409, …).

## Constructor injection

`__init__` parameters with `Depends(...)` are resolved per request, like NestJS constructor injection:

```python
@Controller("/api/users")
@Crud(User)
class UsersController:
    def __init__(self, mailer: Mailer = Depends(get_mailer)):
        self.mailer = mailer

    @Post("/{id}/welcome")
    async def welcome(self, id: int):
        await self.mailer.send_welcome(id)
        return {"sent": True}
```

## Several sections in one controller

```python
@Controller("/api")
@Crud(Tag)                                   # /api/tags
@Crud(Category, path="/cats", actions=["list"])
class CatalogController:
    @CrudSave(section="tags")                # name the section when there are several
    async def save_tag(self): ...
```

## Startup errors

crudman checks controllers when `.router` is built and raises `CrudmanConfigError` for:

- a `@CrudList()`-style method without `@Crud` on the class
- an ambiguous or unknown `section=`
- the same action defined twice
- two routes with the same method and path
- two route decorators on one method
- a details, update or delete path without a path parameter
- conflicting auth decorators on one route (for example `@Public()` with `@Roles(...)`)

## Lowercase names

Every decorator also has a lowercase alias: `controller`, `crud_resource`, `crud_list`, `crud_details`, `crud_create`,
`crud_update`, `crud_delete`, `crud_save`, `crud_bulk_import`, `crud_bulk_delete`, `get`, `post`, `put`, `patch`,
`delete`, `private`, `public`, `roles`. If `Post` clashes with a model named `Post`, use `import crudman as cm` and
`@cm.Post(...)`.
