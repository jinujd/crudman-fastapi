"""Database constraint errors become clean 409 responses, on every database."""

from __future__ import annotations

import pytest

from crudman import HookContext, crud_router

from .conftest import DATABASE_URL, Env
from .models import Country, State


async def test_unique_constraint_is_409(env: Env) -> None:
    env.app_with(crud_router(Country))  # no uniqueness check configured; the DB column is unique
    async with env.client() as c:
        assert (await c.post("/countries", json={"name": "India"})).status_code == 200
        r = await c.post("/countries", json={"name": "India"})
        assert r.status_code == 409
        assert r.json()["success"] is False and r.json()["errors"][0]["type"] == "conflict"
        # the session is usable again afterwards
        assert (await c.post("/countries", json={"name": "Japan"})).status_code == 200


async def test_unique_constraint_on_update_is_409(env: Env) -> None:
    await env.add(Country(name="India"), Country(name="Japan"))
    env.app_with(crud_router(Country))
    async with env.client() as c:
        assert (await c.patch("/countries/2", json={"name": "India"})).status_code == 409


async def test_bulk_import_constraint_error_rolls_back(env: Env) -> None:
    env.app_with(crud_router(Country, actions=["*", "bulk_import"]))
    async with env.client() as c:
        r = await c.post("/countries/bulk/import", json=[{"name": "A"}, {"name": "A"}])
        assert r.status_code == 409
        assert (await c.get("/countries")).json()["data"] == []


async def test_nested_call_action_constraint_error(env: Env) -> None:
    await env.add(Country(name="India"))

    async def create_country(ctx: HookContext) -> None:
        # violates the unique name: the nested error must fail the outer request too
        await ctx.service.call_action("countries", "create", body={"name": "India"}, ctx=ctx)

    env.app_with(crud_router(Country), crud_router(State, config={"create": {"on_before_action": create_country}}))
    async with env.client() as c:
        r = await c.post("/states", json={"name": "Goa", "country_id": 1})
        assert r.status_code == 409
        assert len((await c.get("/states")).json()["data"]) == 0


@pytest.mark.skipif(not DATABASE_URL, reason="SQLite does not enforce foreign keys by default")
async def test_foreign_key_violation_is_409(env: Env) -> None:
    env.app_with(crud_router(State))
    async with env.client() as c:
        r = await c.post("/states", json={"name": "Nowhere", "country_id": 999})
    assert r.status_code == 409
