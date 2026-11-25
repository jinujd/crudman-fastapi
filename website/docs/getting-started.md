---
sidebar_position: 2
title: Getting started
---

# Getting started

## Install

```bash
pip install crudman-fastapi
```

Optional extras:

| Extra | Adds |
| --- | --- |
| `uploads` | `python-multipart`, for multipart file uploads |
| `images` | `Pillow`, for avatar dimension checks |
| `excel` | `openpyxl`, for Excel export |
| `s3` | `aioboto3`, for S3 storage |
| `redis` | `redis`, for the Redis cache |

```bash
pip install "crudman-fastapi[uploads,excel]"
```

Requires Python 3.10+, FastAPI 0.115+, SQLAlchemy 2.0+ and Pydantic 2.7+.

## 1. Define a model

A plain SQLAlchemy 2.0 model. crudman reads its columns, relationships and table name.

```python title="app/models.py"
from datetime import datetime
from sqlalchemy import String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase): ...

class Company(Base):
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    email: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
```

## 2. Register crudman once

```python title="app/main.py"
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from crudman import Crudman, CrudmanOptions, crud_router
from app.models import Company

engine = create_async_engine("sqlite+aiosqlite:///./app.db")
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def get_session():
    async with SessionLocal() as session:
        yield session

app = FastAPI()
Crudman.init(app, CrudmanOptions(session_dependency=get_session))
```

## 3. Mount the CRUD

```python
app.include_router(crud_router(Company))
```

Run the app and open `/docs`:

```bash
uvicorn app.main:app --reload
```

## Try it

```bash
curl -X POST localhost:8000/companies -H 'content-type: application/json' -d '{"name": "Acme Air"}'
curl 'localhost:8000/companies?name.like=acme&sort.created_at=desc'
curl -X PATCH localhost:8000/companies/1 -H 'content-type: application/json' -d '{"is_active": false}'
curl -H 'x-content-type: csv' localhost:8000/companies
```

## Defaults you get without configuration

- Every column can be filtered and sorted.
- Default sort is `created_at DESC`, then the primary key.
- 30 items per page; `?paginate=false` returns everything.
- Keyword search over all columns (minimum 2 characters).
- All relations are loaded and returned.
- Validation comes from the model: on create `name` is required with at most 150 characters; on
  update every field is optional. Unknown fields are rejected on create and dropped on update.
- Uniqueness checks, cache, roles, uploads and hooks are off until you configure them.
