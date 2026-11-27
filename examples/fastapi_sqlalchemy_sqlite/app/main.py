"""Example app: run with `uvicorn app.main:app --reload`, then open http://localhost:8000/docs."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, FastAPI
from fastapi.staticfiles import StaticFiles

from crudman import (
    AuthOptions,
    CacheOptions,
    Crudman,
    CrudmanOptions,
    CrudmanService,
    LocalStorage,
    crud,
    crud_router,
    get_crud,
)

from .auth import current_user
from .controllers import CompaniesController
from .crud.users import users
from .db import engine, get_session
from .models import Base, Category, Country, Profile, State, Tag, User

UPLOADS = Path("uploads")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title="crudman-fastapi example", lifespan=lifespan)

Crudman.init(app, CrudmanOptions(
    session_dependency=get_session,
    cache=CacheOptions(enabled=True, ttl=30),
    default_file_storage="local",
    file_storages={"local": LocalStorage(dest=UPLOADS, public_base_url="http://localhost:8000/uploads")},
    auth=AuthOptions(dependency=current_user),            # routes stay public unless marked @Private
    controllers=[CompaniesController],                    # decorator-style routes
))

# One line per resource. Paths come from the table names.
app.include_router(crud_router(Country, actions=["*", "save", "bulk_import", "bulk_delete"]), prefix="/api")
app.include_router(crud_router(State, config={"list": {"enable_cache": True}}), prefix="/api")
app.include_router(crud_router(User, config=users, private=["create", "update", "delete"]), prefix="/api")
app.include_router(crud_router(Profile, config={"uploadable": {"avatar": "image"}}), prefix="/api")
app.include_router(crud_router([Tag, Category]), prefix="/api/shorthand")

# Custom routes reusing the "companies" section.
custom = APIRouter(prefix="/api/custom", tags=["custom"])


@custom.get("/companies/list")
@crud.list("companies")
async def list_companies() -> None:
    """Same as GET /api/companies, on a custom path."""


@custom.post("/countries/{country_id}/states")
async def create_state(country_id: int, body: dict[str, Any], svc: CrudmanService = Depends(get_crud)) -> Any:
    result = await svc.call_action("states", "create", body={"name": body.get("name"), "country_id": country_id})
    return result.to_response()


app.include_router(custom)

UPLOADS.mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOADS), name="uploads")
