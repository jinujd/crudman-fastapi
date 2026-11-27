"""Access control (roles, ownership) and caching."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy import update

from crudman import CacheOptions, MemoryCache, crud_router

from .conftest import Env
from .models import Country, Note, Tag


def header_identity(request: Request) -> dict[str, Any]:
    uid = request.headers.get("x-user")
    return {"id": int(uid), "role": request.headers.get("x-role", "user")} if uid else {}


async def test_required_roles(env: Env) -> None:
    env.app_with(
        crud_router(Tag, config={"required_roles": ["admin"], "list": {"required_roles": []}}),
        identity_accessor=header_identity,
    )
    async with env.client() as c:
        assert (await c.get("/tags")).status_code == 200  # list is open
        assert (await c.post("/tags", json={"name": "x"}, headers={"x-user": "1"})).status_code == 403
        r = await c.post("/tags", json={"name": "x"}, headers={"x-user": "1", "x-role": "admin"})
        assert r.status_code == 200


async def test_custom_role_checker(env: Env) -> None:
    env.app_with(
        crud_router(Tag, config={"required_roles": ["editor"]}),
        identity_accessor=lambda req: {"roles": req.headers.get("x-roles", "").split(",")},
        role_checker=lambda identity, roles: bool(set(identity["roles"]) & set(roles)),
    )
    async with env.client() as c:
        assert (await c.get("/tags", headers={"x-roles": "viewer"})).status_code == 403
        assert (await c.get("/tags", headers={"x-roles": "viewer,editor"})).status_code == 200


async def test_ownership(env: Env) -> None:
    await env.add(Note(text="mine", owner_id=1), Note(text="theirs", owner_id=2))
    env.app_with(crud_router(Note, config={"ownership": {"field": "owner_id"}}), identity_accessor=header_identity)
    me = {"x-user": "1"}
    async with env.client() as c:
        assert (await c.get("/notes")).status_code == 403  # anonymous
        assert [n["text"] for n in (await c.get("/notes", headers=me)).json()["data"]] == ["mine"]
        assert (await c.get("/notes/2", headers=me)).status_code == 404
        assert (await c.patch("/notes/2", json={"text": "hacked"}, headers=me)).status_code == 404
        assert (await c.delete("/notes/2", headers=me)).status_code == 404
        created = (await c.post("/notes", json={"text": "new", "owner_id": 2}, headers=me)).json()["data"]
        assert created["owner_id"] == 1  # set from identity, not the body


async def test_identity_from_request_state(env: Env) -> None:
    env.app_with(crud_router(Note, config={"ownership": {"field": "owner_id"}}))

    @env.app.middleware("http")  # type: ignore[union-attr]
    async def auth(request: Request, call_next: Any) -> Any:
        request.state.user = {"id": 7}
        return await call_next(request)

    async with env.client() as c:
        assert (await c.post("/notes", json={"text": "x"})).json()["data"]["owner_id"] == 7


async def test_list_and_details_cache_with_invalidation(env: Env) -> None:
    await env.add(Country(name="India"))
    env.app_with(
        crud_router(Country, config={"list": {"enable_cache": {"ttl": 60}}, "details": {"enable_cache": True}}),
        crud_router(Tag, config={"list": {"enable_cache": True}}),
        cache=CacheOptions(enabled=True, ttl=60),
    )
    async with env.client() as c:
        assert (await c.get("/countries")).json()["data"][0]["name"] == "India"
        assert (await c.get("/countries/1")).json()["data"]["name"] == "India"
        await c.get("/tags")
        # change the row behind crudman's back: cached responses are still served
        async with env.sessionmaker() as s:
            await s.execute(update(Country).values(name="Bharat"))
            await s.commit()
        assert (await c.get("/countries")).json()["data"][0]["name"] == "India"
        assert (await c.get("/countries/1")).json()["data"]["name"] == "India"
        # a different query is a different key
        assert (await c.get("/countries?page=1")).json()["data"][0]["name"] == "Bharat"
        # a write to another section keeps this section's cache
        await c.post("/tags", json={"name": "t"})
        assert (await c.get("/countries")).json()["data"][0]["name"] == "India"
        # a write to this section invalidates it
        await c.post("/countries", json={"name": "Japan"})
        names = [r["name"] for r in (await c.get("/countries")).json()["data"]]
        assert sorted(names) == ["Bharat", "Japan"]


async def test_cache_disabled_without_global_option(env: Env) -> None:
    await env.add(Country(name="India"))
    env.app_with(crud_router(Country, config={"list": {"enable_cache": True}}))
    async with env.client() as c:
        await c.get("/countries")
        async with env.sessionmaker() as s:
            await s.execute(update(Country).values(name="Bharat"))
            await s.commit()
        assert (await c.get("/countries")).json()["data"][0]["name"] == "Bharat"


async def test_memory_cache_expiry_and_limits() -> None:
    cache = MemoryCache(ttl=60, max_keys=2)
    await cache.set("a:1", 1)
    await cache.set("a:2", 2)
    await cache.set("b:1", 3)
    assert await cache.get("a:1") is None  # evicted (oldest)
    assert await cache.get("b:1") == 3
    await cache.set("a:3", 4, ttl=-1)
    assert await cache.get("a:3") is None  # expired
    await cache.invalidate_section("b")
    assert await cache.get("b:1") is None
