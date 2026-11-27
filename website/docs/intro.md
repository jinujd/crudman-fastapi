---
sidebar_position: 1
slug: /intro
title: Introduction
---

# crudman-fastapi

crudman-fastapi is a minimal, adapter-driven CRUD layer for **FastAPI** and **SQLAlchemy 2.0**. It is the
Python port of [crudman-nestjs](https://github.com/jinujd/crudman-nestjs).

```python
from crudman import Crudman, CrudmanOptions, crud_router
from app.models import Company

Crudman.init(app, CrudmanOptions(session_dependency=get_session))
app.include_router(crud_router(Company))
```

That single call gives you:

- `GET /companies`: filters, sorting, pagination, keyword search
- `GET /companies/{id}`: includes relations by default
- `POST /companies`
- `PATCH /companies/{id}`
- `DELETE /companies/{id}`

Plus OpenAPI docs, validation generated from your model, and CSV / Excel export.

:::note Version 0.1
Everything in these docs is implemented and covered by end-to-end tests on SQLite and PostgreSQL, except the Redis cache
and S3 storage adapters, which are built but not yet tested against live services. See the
[feature list](./features.md).
:::

## Why crudman

- **Fast start.** One line per resource, sensible defaults for everything.
- **Override anything.** Settings per section and per action, seven hooks, or your own handler.
- **Safe querying.** Filter and sort whitelists default to your model's columns.
- **Same contract as the NestJS version.** Query parameters, response envelope and headers are
  identical, so one front-end works with either backend.

## Next steps

- [Getting started](./getting-started.md)
- [Defining CRUDs](./defining-cruds.md) or [Controllers](./controllers.md) (decorators)
- [Authentication](./authentication.md)
- [Feature list](./features.md)
