---
title: Sections
---

# Sections

A **section** is a named CRUD resource: a model plus settings. You only need one when the defaults are
not enough.

## Three layers of settings

```text
CrudmanOptions.defaults  →  section top-level keys  →  section.<action> block
(all sections)              (every action)             (list / details / create / update / save / delete)
```

The later layer wins. A top-level key applies to every action; the same key inside an action block
overrides it for that action. `common` is accepted as an alias for top-level keys, for README examples
from the NestJS version.

## Typed or dict

```python title="app/crud/companies.py"
from crudman import Section, ListAction, DetailsAction, WriteAction, Keyword, Pagination

companies = Section(
    title="Company", description="Companies CRUD",
    attributes={"read": {"exclude": ["secret"]}},
    relations={"exclude": ["audit_logs"]},
    required_roles=["admin"],
    list=ListAction(
        filters_whitelist=["name", "is_active", "created_at"],
        sorting_whitelist=["name", "created_at"],
        order_by=[("created_at", "DESC")],
        keyword=Keyword(searchable_fields=["name", "contacts.email"], min_length=2, max_relation_depth=2),
        pagination=Pagination(max_per_page=100),
        enable_cache={"ttl": 60},
    ),
    details=DetailsAction(relations=["contacts"]),
    create=WriteAction(fields_for_uniqueness_validation=["name"]),
    update=WriteAction(fields_for_uniqueness_validation=["name"]),
)
```

The same as a dict:

```python
companies = {
    "list": {"filters_whitelist": ["name", "is_active"], "keyword": {"searchable_fields": ["name"]}},
    "create": {"fields_for_uniqueness_validation": ["name"]},
}
```

Both forms are validated at startup, so a typo such as `filter_whitelist` fails when the app boots.

The `model` key is optional when the model is passed to `crud_router(Company, config=companies)`. If you
set both and they differ, startup fails.

## All keys

| Key | Meaning |
| --- | --- |
| `model` | SQLAlchemy class (optional when passed to `crud_router`) |
| `title`, `description` | OpenAPI schema title and description |
| `relations` / `get_relations(ctx)` | `"*"` (default), a list, `{"include": [...]}` or `{"exclude": [...]}` |
| `attributes` | `{"read": ..., "write": ...}`, each `"*"`, a list, include or exclude |
| `filters_whitelist`, `sorting_whitelist` | default: all root columns |
| `order_by` | default sort when the request sends none |
| `conditions` | fixed where clause added to every query |
| `keyword`, `keyword_param_name` | keyword search |
| `query_param_names`, `pagination` | parameter renames and pagination toggles |
| `record_selection_field` | default `"id"`; also names the path parameter |
| `fields_for_uniqueness_validation` | fields that must be unique |
| `condition_type_for_uniqueness_validation` | `"or"` (default) or `"and"` |
| `required_roles`, `ownership` | [access control](./access-control.md) |
| `on_before_action`, `on_before_query`, `on_after_fetch`, `on_before_validate`, `get_final_validation_rules`, `on_after_validate`, `on_after_action` | [hooks](./hooks.md) |
| `context` | [per-request context](./context.md) |
| `additional_response` / `get_additional_response` | extra keys merged into `meta` |
| `response_handler` | per-action output shaping |
| `custom_implementation` | full override of an action |
| `enable_cache` | `True` or `{"ttl": int, "key": fn}` |
| `uploadable`, `upload`, `upload_defaults` | [file uploads](./uploads.md) |
| `session`, `orm`, `validator` | per-section overrides (multi-database, custom adapters) |
| `openapi` | `{"enabled": False}` hides the section from the docs; use `crud_router(..., tags=[...])` for tags |

## Relations

```python
relations="*"                                   # default: all relationships, eager-loaded
relations=["profile", "roles"]                  # only these
relations={"exclude": ["audit_logs"]}           # all except these
get_relations=lambda ctx: ["roles"] if ctx.query.get("withRoles") else []
```

## Attributes

```python
attributes={"read": "*", "write": {"exclude": ["id", "created_at", "updated_at"]}}
attributes={"read": {"include": ["id", "name", "avatar_url"]}}
```

`read` controls what is returned; `write` controls what clients may send.

## Uniqueness

```python
create=WriteAction(fields_for_uniqueness_validation=["email", "username"])            # either must be unique
create=WriteAction(fields_for_uniqueness_validation=["tenant_id", "slug"],
                   condition_type_for_uniqueness_validation="and")                     # the pair must be unique
```

On update, the current record is excluded and only fields present in the body are checked. A duplicate
returns HTTP 400 with `{"type": "unique", "field": "email", "message": "email must be unique"}`.
