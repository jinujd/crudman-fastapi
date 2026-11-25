---
title: Custom routes
---

# Custom routes

:::info Planned for 0.1.0
:::

## Register without auto routes

`crud.register` takes the same arguments as `crud_router` but mounts nothing:

```python
from crudman import crud

crud.register(Company)                       # section "companies"
crud.register(Company, "orgs", companies)    # with a name and settings
```

## Decorators on your own paths

```python
from fastapi import APIRouter

router = APIRouter(prefix="/api/custom")

@router.get("/companies/list")
@crud.list("companies")
async def list_companies(): ...              # the body is ignored; crudman handles the request

@router.get("/company/details/{id}")
@crud.details("companies")
async def company_details(): ...

@router.post("/company/save")
@crud.save("companies")
async def save_company(): ...
```

Available: `crud.list`, `crud.details`, `crud.create`, `crud.update`, `crud.delete`, `crud.save`,
`crud.bulk_import`, `crud.bulk_delete`.

## Calling the service

```python
from fastapi import Depends, Request
from crudman import CrudmanService, get_crud

@router.get("/companies/{id}/summary")
async def summary(id: int, request: Request, svc: CrudmanService = Depends(get_crud)):
    result = await svc.details("companies", request)       # CrudResult(status_code, body, headers)
    result.body["data"]["display"] = result.body["data"]["name"].upper()
    return result.to_response()
```

## `call_action` across sections

```python
@router.post("/countries/{country_id}/states")
async def create_state(country_id: int, body: dict, svc: CrudmanService = Depends(get_crud)):
    r = await svc.call_action("states", "save", body={"name": body["name"], "country_id": country_id})
    return r.to_response()
```

Inside a hook, `ctx.service.call_action(...)` runs in the same transaction as the current request:

```python
async def create_company_first(errors, ctx):
    if ctx.body.get("create_company"):
        r = await ctx.service.call_action("companies", "save", body=ctx.body["company"], ctx=ctx)
        if not r.body["success"]:
            raise CrudAbort(r)
        ctx.body["company_id"] = r.body["data"]["id"]
```
