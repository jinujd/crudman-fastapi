---
title: Hooks
---

# Hooks

All hooks are optional and may be plain functions or `async def`. The subject comes first and
[`ctx`](./context.md) last. A hook at section level applies to every action; a hook inside an action
block replaces it for that action.

| Hook | Signature | Use |
| --- | --- | --- |
| `on_before_action` | `(ctx)` | Allow or block early. Return `False` (403), return a `Response`, or raise `HTTPException`. |
| `on_before_query` | `(stmt, ctx) -> Select` | Change the SQLAlchemy `Select` before it runs. |
| `on_after_fetch` | `(data, ctx) -> data` | Transform rows (list) or the record (details). |
| `get_final_validation_rules` | `(rules, ctx) -> rules or model` | Replace or extend generated rules. |
| `on_before_validate` | `(rules, ctx)` | Return `False` to stop. |
| `on_after_validate` | `(errors, ctx)` | Append errors, or return `False` to stop. |
| `on_after_action` | `(result, ctx) -> result` | Last change to the response. The return value replaces it. |

## Examples

```python
from sqlalchemy import Select
from crudman import HookContext

async def only_my_company(ctx: HookContext):
    company_id = ctx.identity.get("company_id")
    if not company_id:
        return False
    ctx.query["company_id"] = str(company_id)      # must be in filters_whitelist

async def active_only(stmt: Select, ctx: HookContext) -> Select:
    return stmt.where(Company.is_active.is_(True))

async def tenant_scope(stmt: Select, ctx: HookContext) -> Select:
    return stmt.where(Company.tenant_id == ctx.identity["tenant_id"])

async def add_tag(data, ctx: HookContext):
    return [{**row, "tag": "USER"} for row in data] if isinstance(data, list) else data

async def stamp(result: dict, ctx: HookContext) -> dict:
    return {**result, "servedAt": datetime.utcnow().isoformat()}

users = Section(
    on_after_action=stamp,                              # every action
    list=ListAction(on_before_action=only_my_company, on_before_query=active_only, on_after_fetch=add_tag),
)
```

## Execution order

**list / details**

1. `on_before_action`
2. resolve relations
3. cache lookup (if enabled)
4. `on_before_query`
5. fetch
6. `on_after_fetch`
7. format
8. `additional_response`
9. `on_after_action`
10. cache store
11. negotiate JSON / CSV / Excel

**create / update / save**

1. `on_before_action`
2. process uploads
3. generate rules
4. `get_final_validation_rules`
5. `on_before_validate`
6. validate
7. uniqueness check
8. `on_after_validate`
9. write, inside a transaction
10. format
11. `additional_response`
12. `on_after_action`
13. cache invalidation

**delete**

1. `on_before_action`
2. delete (404 when missing)
3. format
4. `on_after_action`
5. cache invalidation

:::note Difference from crudman-nestjs
The NestJS code runs uploads and validation before `onBeforeAction` on writes, so files are saved even
when the hook blocks the request. crudman-fastapi runs `on_before_action` first, as the NestJS README
documents.
:::
