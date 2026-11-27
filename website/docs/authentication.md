---
title: Authentication
---

# Authentication

**Routes are public by default.** Mark the ones that need a signed-in user with `@Private()`.

## 1. Tell crudman how to authenticate

Pass any FastAPI dependency that returns the current user, or raises `HTTPException(401)`:

```python
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from crudman import AuthOptions, Crudman, CrudmanOptions

bearer = HTTPBearer(auto_error=False)

async def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    user = decode_jwt(creds.credentials) if creds else None      # your code
    if user is None:
        raise HTTPException(401, "Not signed in")
    return {"id": user.id, "role": user.role}

Crudman.init(app, CrudmanOptions(
    session_dependency=get_session,
    auth=AuthOptions(dependency=current_user),   # default="public"
))
```

- The dependency may return a dict or an object with `id` / `role` / `roles` attributes. It becomes
  `ctx.identity` (and `request.state.identity`), which `ownership`, `required_roles` and hooks use. Returning `None`
  on a private route gives 401.
- Because it is a normal FastAPI dependency, Swagger shows a lock and an **Authorize** button on private routes. For
  that, call `Crudman.init` before building routers with `crud_router` (controllers build lazily, so they are always
  fine).

## 2. Mark routes

| Decorator | Meaning |
| --- | --- |
| `@Private()` | A signed-in user is required (401 otherwise) |
| `@Roles("admin", "editor")` | Signed in **and** one of the roles (403 otherwise); implies `@Private()` |
| `@Private(roles=["admin"])` | Same as `@Roles("admin")` |
| `@Public()` | No auth: use it inside a `@Private` controller to open a single route |

They work on controller classes, controller methods and plain FastAPI routes:

```python
@Controller("/api/companies")
@Private()                       # the whole controller...
@Crud(Company)
class CompaniesController:
    @Public()                    # ...except the list
    @CrudList()
    async def list(self): ...

    @Roles("admin")
    @CrudDelete()
    async def remove(self): ...


router = APIRouter()

@router.get("/me")
@Private()
async def me(request: Request):
    return request.state.identity
```

Put the auth decorator **below** `@router.get(...)` on plain routes, as shown. For Swagger's lock icon on plain routes,
call `Crudman.init` before the module that defines them is imported (the route works either way).

## 3. Or use options instead of decorators

```python
crud_router(Company, auth="private")                           # every route
crud_router(Company, private=["create", "update", "delete"])  # some actions
crud_router(Company, auth="private", public=["list", "details"], roles={"delete": ["admin"]})
crud_router(Company, roles=["admin"])                           # every route, admins only

Section(auth="private", list={"auth": "public"})                # in section config
```

## Which setting wins

The nearest one decides:

1. Decorator on the method or route.
2. Decorator on the controller class.
3. `crud_router(public=..., private=..., roles={...})` for that action, then `crud_router(auth=..., roles=[...])`.
4. Section config `auth` (per action, then section level).
5. `AuthOptions.default`: `"public"` unless you set `default="private"`.

With `AuthOptions(dependency=..., default="private")` everything is protected except routes marked `@Public()` or
`public=[...]`.

## Roles

By default a role check passes when `identity["role"]` is one of the roles, or when `identity["roles"]` (a list)
shares one with them. Pass `CrudmanOptions(role_checker=fn)` for anything else:

```python
CrudmanOptions(role_checker=lambda identity, roles: bool(set(identity["permissions"]) & set(roles)))
```

## Responses

| Case | Status | Body |
| --- | --- | --- |
| Not signed in | 401 | `{"detail": {"errors": [{"type": "unauthorized", ...}], "success": false}}`, or whatever your dependency raises |
| Signed in, wrong role | 403 | `{"detail": {"errors": [{"type": "forbidden", ...}], "success": false}}` |

[Ownership and section-level `required_roles`](./access-control.md) still apply on top of this.
