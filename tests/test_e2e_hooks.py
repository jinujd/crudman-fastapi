"""Hooks, context, custom routes, call_action, formatters and error modes."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import Select, select

from crudman import (
    CrudAbort,
    CrudmanService,
    CrudResult,
    FormatInput,
    HookContext,
    crud,
    crud_router,
    get_crud,
)

from .conftest import Env
from .models import AuditLog, Company, Country, State


async def test_hook_order_for_list_and_create(env: Env) -> None:
    calls: list[str] = []

    def rec(name: str, ret: Any = None) -> Any:
        def hook(*args: Any) -> Any:
            calls.append(name)
            return args[0] if ret == "first" else None
        return hook

    env.app_with(crud_router(Country, config={
        "on_before_action": rec("before_action"),
        "on_before_query": rec("before_query", "first"),
        "on_after_fetch": rec("after_fetch", "first"),
        "get_final_validation_rules": rec("final_rules", "first"),
        "on_before_validate": rec("before_validate"),
        "on_after_validate": rec("after_validate"),
        "on_after_action": rec("after_action"),
    }))
    async with env.client() as c:
        await c.post("/countries", json={"name": "India"})
        assert calls == ["before_action", "final_rules", "before_validate", "after_validate", "after_action"]
        calls.clear()
        await c.get("/countries")
        assert calls == ["before_action", "before_query", "after_fetch", "after_action"]


async def test_before_action_can_block_or_respond(env: Env) -> None:
    def gate(ctx: HookContext) -> Any:
        mode = ctx.request.headers.get("x-mode")
        if mode == "block":
            return False
        if mode == "teapot":
            return PlainTextResponse("short and stout", status_code=418)
        if mode == "raise":
            raise HTTPException(401, "nope")
        return None

    env.app_with(crud_router(Country, config={"on_before_action": gate}))
    async with env.client() as c:
        assert (await c.get("/countries", headers={"x-mode": "block"})).status_code == 403
        r = await c.get("/countries", headers={"x-mode": "teapot"})
        assert (r.status_code, r.text) == (418, "short and stout")
        assert (await c.get("/countries", headers={"x-mode": "raise"})).status_code == 401
        assert (await c.post("/countries", json={"name": "X"}, headers={"x-mode": "block"})).status_code == 403
        assert (await c.get("/countries")).json()["data"] == []  # nothing was written


async def test_before_action_injects_filter(env: Env) -> None:
    await env.add(Country(name="India", code="IN"), Country(name="Japan", code="JP"))

    def only_in(ctx: HookContext) -> None:
        ctx.query["code"] = "IN"

    env.app_with(crud_router(Country, config={"list": {"on_before_action": only_in}}))
    async with env.client() as c:
        assert [r["name"] for r in (await c.get("/countries")).json()["data"]] == ["India"]


async def test_after_fetch_and_after_action_replace(env: Env) -> None:
    await env.add(Country(name="India"))
    env.app_with(crud_router(Country, config={
        "on_after_fetch": lambda data, ctx: [{**row, "tag": "X"} for row in data] if isinstance(data, list)
        else {**data, "tag": "Y"},
        "on_after_action": lambda result, ctx: {**result, "servedBy": ctx.section},
    }))
    async with env.client() as c:
        body = (await c.get("/countries")).json()
        assert body["data"][0]["tag"] == "X" and body["servedBy"] == "countries"
        assert (await c.get("/countries/1")).json()["data"]["tag"] == "Y"


async def test_additional_response_and_response_handler(env: Env) -> None:
    await env.add(Country(name="India"))
    env.app_with(
        crud_router(Country, config={"additional_response": {"version": 2},
                                     "get_additional_response": lambda body, ctx: {"count": len(body["data"])}}),
        crud_router(Country, "shaped", {"list": {"response_handler": lambda r, ctx: {"items": r["data"]}}}),
    )
    async with env.client() as c:
        assert (await c.get("/countries")).json()["meta"] == {"version": 2, "count": 1}
        assert (await c.get("/shaped")).json() == {"items": [{"id": 1, "name": "India", "code": None,
                                                              "states": []}]}


async def test_custom_implementation(env: Env) -> None:
    async def impl(ctx: HookContext) -> Any:
        if ctx.action == "list":
            return {"custom": True}
        return CrudResult(status_code=202, body={"queued": True})

    env.app_with(crud_router(Country, config={"custom_implementation": impl}))
    async with env.client() as c:
        assert (await c.get("/countries")).json() == {"custom": True}
        r = await c.post("/countries", json={})
        assert (r.status_code, r.json()) == (202, {"queued": True})


async def test_custom_response_formatter(env: Env) -> None:
    def fmt(f: FormatInput) -> dict[str, Any]:
        return {"ok": f.success, "result": f.payload, "pageInfo": f.pagination}

    await env.add(Country(name="India"))
    env.app_with(crud_router(Country, config={"relations": []}), response_formatter=fmt)
    async with env.client() as c:
        body = (await c.get("/countries")).json()
        assert body["ok"] is True and body["result"]["items"][0]["name"] == "India"
        assert body["pageInfo"]["totalItemsCount"] == 1
        assert (await c.get("/countries/9")).json() == {"ok": False, "result": None, "pageInfo": None}


async def test_throw_on_error(env: Env) -> None:
    env.app_with(crud_router(Country), throw_on_error=True)
    async with env.client() as c:
        r = await c.get("/countries/9")
    assert r.status_code == 404
    assert r.json()["detail"]["errors"][0]["type"] == "notFound"


class FlagService:
    def get(self) -> str:
        return "on"


def get_flags() -> FlagService:
    return FlagService()


async def test_context_forms(env: Env) -> None:
    seen: dict[str, Any] = {}

    async def build(ctx: HookContext) -> dict[str, Any]:
        return {"tenant_id": ctx.request.headers.get("x-tenant"), "service": "ignored", "section": "ignored"}

    async def after(result: dict[str, Any], ctx: HookContext) -> None:
        seen["flag"] = ctx.services["flags"].get()
        seen["tenant"] = ctx.tenant_id
        seen["reserved"] = (ctx.section, isinstance(ctx.service, CrudmanService))
        seen["from_action"] = ctx.get("from_action")
        await ctx.repositories["audit"].add(type="LIST", notes=ctx.tenant_id)
        seen["repo"] = ctx.repository.model is Country

    env.app_with(crud_router(Country, config={
        "context": {"services": {"flags": Depends(get_flags)}, "repositories": {"audit": AuditLog},
                    "get_hook_context": build},
        "list": {"context": lambda ctx: {"from_action": True}, "on_after_action": after},
    }))
    async with env.client() as c:
        assert (await c.get("/countries", headers={"x-tenant": "t1"})).status_code == 200
    assert seen == {"flag": "on", "tenant": "t1", "reserved": ("countries", True), "from_action": True,
                    "repo": True}
    assert await env.scalar(select(AuditLog.notes)) == "t1"  # hook writes are committed


async def test_call_action_inside_hook_shares_transaction(env: Env) -> None:
    async def create_country_first(ctx: HookContext) -> None:
        if "country" in ctx.body:
            r = await ctx.service.call_action("countries", "create", body=ctx.body.pop("country"), ctx=ctx)
            if not r.ok:
                raise CrudAbort(r)
            ctx.body["country_id"] = r.body["data"]["id"]

    states = crud_router(State, config={"create": {"on_before_action": create_country_first}})
    env.app_with(crud_router(Country), states)
    async with env.client() as c:
        r = await c.post("/states", json={"name": "Kerala", "country": {"name": "India"}})
        assert r.status_code == 200, r.json()
        assert r.json()["data"]["country"]["name"] == "India"
        # the nested create fails → the whole request is rolled back
        r = await c.post("/states", json={"name": "Goa", "country": {"name": ""}})
        assert r.status_code == 400 and r.json()["errors"][0]["field"] == "name"
        # the nested create succeeds but the outer create fails → the nested row is rolled back too
        r = await c.post("/states", json={"name": "", "country": {"name": "Japan"}})
        assert r.status_code == 400
        assert [row["name"] for row in (await c.get("/countries")).json()["data"]] == ["India"]


async def test_register_and_decorators_on_custom_paths(env: Env) -> None:
    crud.register(Country)
    router = APIRouter(prefix="/custom")

    @router.get("/countries/all")
    @crud.list("countries")
    async def list_countries() -> None: ...

    @router.post("/country/new")
    @crud.create("countries")
    async def new_country() -> None: ...

    @router.get("/country/{id}/view")
    @crud.details("countries")
    async def view_country() -> None: ...

    env.app_with(router)
    async with env.client() as c:
        cid = (await c.post("/custom/country/new", json={"name": "India"})).json()["data"]["id"]
        assert (await c.get("/custom/countries/all")).json()["data"][0]["name"] == "India"
        assert (await c.get(f"/custom/country/{cid}/view")).json()["data"]["id"] == cid


async def test_service_in_own_handler(env: Env) -> None:
    router = APIRouter()

    @router.post("/countries/{country_id}/states")
    async def add_state(country_id: int, body: dict[str, Any], svc: CrudmanService = Depends(get_crud)) -> Any:
        r = await svc.call_action("states", "create", body={"name": body["name"], "country_id": country_id})
        return r.to_response()

    @router.get("/countries/{id}/summary")
    async def summary(request: Request, svc: CrudmanService = Depends(get_crud)) -> Any:
        r = await svc.details("countries", request)
        r.body["data"]["display"] = r.body["data"]["name"].upper()
        return r.to_response()

    env.app_with(crud_router(Country), crud_router(State), router)
    async with env.client() as c:
        cid = (await c.post("/countries", json={"name": "India"})).json()["data"]["id"]
        r = await c.post(f"/countries/{cid}/states", json={"name": "Goa"})
        assert r.json()["data"]["country_id"] == cid
        assert (await c.get(f"/countries/{cid}/summary")).json()["data"]["display"] == "INDIA"


async def test_on_before_query_for_details(env: Env) -> None:
    await env.add(Company(name="A", is_active=False))

    def active(stmt: Select, ctx: HookContext) -> Select:
        return stmt.where(Company.is_active.is_(True))

    env.app_with(crud_router(Company, config={"on_before_query": active}))
    async with env.client() as c:
        assert (await c.get("/companies/1")).status_code == 404


async def test_hook_exception_rolls_back(env: Env) -> None:
    def boom(result: Any, ctx: HookContext) -> None:
        raise RuntimeError("boom")

    env.app_with(crud_router(Country, config={"create": {"on_after_action": boom}}))
    async with env.client() as c:
        with pytest.raises(RuntimeError):
            await c.post("/countries", json={"name": "India"})
    assert await env.scalar(select(Country.id)) is None
