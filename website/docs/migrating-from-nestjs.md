---
title: Migrating from crudman-nestjs
---

# Migrating from crudman-nestjs

The HTTP contract is the same, so clients do not change. On the server:

| crudman-nestjs | crudman-fastapi |
| --- | --- |
| TypeORM entity | SQLAlchemy 2.0 model |
| `CrudmanModule.forRoot({...})` | `Crudman.init(app, CrudmanOptions(...))` |
| `@UseCrud({ sections: { companies: { model: Company } } })` + `CrudControllerBase('companies')` | `crud_router(Company)` |
| `@Controller('api/companies')` | `include_router(..., prefix="/api")` |
| `UseCrud({ models: [Tag, Category] })` + `CrudControllerBase(['tags','categories'])` | `crud_router([Tag, Category])` |
| section name from the pluralised class name | section name from the table name |
| `@CrudList('companies')` | `@crud.list("companies")` |
| `CrudmanService` injection | `Depends(get_crud)` |
| `callAction(section, action, req, res)` | `call_action(section, action, body=..., params=...)` |
| camelCase keys (`filtersWhitelist`, `onBeforeAction`) | snake_case keys (`filters_whitelist`, `on_before_action`) |
| `onBeforeQuery(findOptions, model, ctx, req, res)` | `on_before_query(stmt, ctx)` with a SQLAlchemy `Select` |
| hooks receive `(req, res, ctx, ...)` | hooks receive `(subject, ctx)`; the request is `ctx.request` |
| `additionalSettings.repo` | `session=` per section |
| fastest-validator rules | Pydantic, or the same rule dicts in `get_final_validation_rules` |
| NodeCache | TTL cache, or Redis |
| `setCrudmanDataSource` | not needed |

## Behaviour that differs on purpose

| crudman-nestjs | crudman-fastapi |
| --- | --- |
| Keyword search combined with filters using OR (a bug) | always AND |
| `.like` or range filters switch to a query path that drops keyword, `onBeforeQuery` and attributes | one query path |
| Range filters drop non-numeric values such as dates | dates work |
| Uploads and validation run before `onBeforeAction` | `on_before_action` runs first |
| `onAfterAction` return value ignored | return value replaces the response |
| Missing records on update/delete return success | 404 |
| Writes flush the whole cache | per-section invalidation |
| `requiredRoles`, `ownership`, `responseHandler`, `customImplementation`, `orderBy`, `conditions`, bulk endpoints: declared only | implemented |
