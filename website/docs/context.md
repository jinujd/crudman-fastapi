---
title: Context
---

# Context (`ctx`)

Every hook receives `ctx`, built for each request.

## Reserved keys (always present)

| Key | Contents |
| --- | --- |
| `service` | the `CrudmanService` |
| `session` | the current `AsyncSession` |
| `repository` | helper bound to the section's model: `get`, `find`, `exists`, `add` |
| `section`, `action`, `model` | what is running |
| `request` | the FastAPI request |
| `identity` | from `identity_accessor` |
| `params`, `query`, `body`, `files` | parsed request parts |

Your context builders cannot overwrite these.

## Adding your own

Three forms, as in crudman-nestjs. Section-level context is merged first, then action-level.

```python
# 1. Dict. Values may be Depends(...) (resolved by FastAPI) or plain objects.
Section(context={
    "services": {"mailer": Depends(get_mailer)},
    "repositories": {"audit": AuditLog},          # ctx.repositories["audit"], same session
})

# 2. Function (may be async).
async def build_ctx(ctx):
    return {"services": {"flags": FlagService()}, "tenant_id": ctx.request.headers.get("x-tenant-id")}

Section(context=build_ctx)

# 3. Dict with callable parts plus get_hook_context.
Section(context={"services": lambda ctx: {"flags": FlagService()}, "get_hook_context": build_ctx})
```

```python
async def welcome(result, ctx):
    await ctx.services["mailer"].send_welcome(result["data"]["email"])
    await ctx.repositories["audit"].add(type="USER_CREATED")
    return result
```
