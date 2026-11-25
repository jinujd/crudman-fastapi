"""Shared fixtures: a fresh SQLite database file per test and an app builder."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from crudman import Crudman, CrudmanOptions

from .models import Base


@pytest.fixture(autouse=True)
def _reset_crudman() -> None:
    Crudman.reset()


class Env:
    def __init__(self, tmp_path: Path) -> None:
        self.db_path = tmp_path / "test.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}")
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)
        self.tmp_path = tmp_path
        self.app: FastAPI | None = None

    async def get_session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessionmaker() as session:
            yield session

    def app_with(self, *routers: Any, **options: Any) -> FastAPI:
        app = FastAPI()
        Crudman.init(app, CrudmanOptions(session_dependency=self.get_session, **options))
        for router in routers:
            if isinstance(router, tuple):
                app.include_router(router[0], prefix=router[1])
            else:
                app.include_router(router)
        self.app = app
        return app

    def client(self, app: FastAPI | None = None) -> AsyncClient:
        return AsyncClient(transport=ASGITransport(app=app or self.app), base_url="http://test")

    async def add(self, *objs: Any) -> None:
        async with self.sessionmaker() as session:
            session.add_all(objs)
            await session.commit()

    async def scalar(self, stmt: Any) -> Any:
        async with self.sessionmaker() as session:
            return (await session.execute(stmt)).scalar()


@pytest.fixture
async def env(tmp_path: Path) -> AsyncIterator[Env]:
    e = Env(tmp_path)
    async with e.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield e
    await e.engine.dispose()


AppFactory = Callable[..., FastAPI]
