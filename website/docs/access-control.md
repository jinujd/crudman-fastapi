---
title: Access control
---

# Access control

:::info Planned (phase 6)
crudman-nestjs declares these options but never enforces them. crudman-fastapi will.
:::

```python
CrudmanOptions(
    identity_accessor=lambda request: getattr(request.state, "user", None) or {},
    role_checker=lambda identity, roles: not roles or identity.get("role") in roles,
)

Section(
    required_roles=["admin"],                 # every action
    list=ListAction(required_roles=[]),       # anyone can list
    ownership={"field": "user_id"},           # rows where user_id == identity["id"]
)
```

- **`required_roles`:** checked before `on_before_action`; failure returns 403.
- **`ownership`:** list and details only return owned rows; update and delete return 404 for rows you
  do not own; create sets the field from the identity.

FastAPI dependencies also work, because crud routers accept them:

```python
app.include_router(crud_router(Company), dependencies=[Depends(require_login)])
```
