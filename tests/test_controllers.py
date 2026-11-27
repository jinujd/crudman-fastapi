"""NestJS-style controllers: routes and auth defined with decorators."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

import crudman as cm
from crudman import (
    AuthOptions,
    Controller,
    Crud,
    CrudCreate,
    CrudDelete,
    CrudDetails,
    CrudList,
    CrudmanConfigError,
    CrudResult,
    CrudSave,
    Get,
    Post,
    Private,
    Public,
    Roles,
    include_controllers,
)

from .conftest import Env
from .models import Category, Company, Country, State, Tag
from .models import Post as PostModel


def current_user(request: Request) -> dict[str, Any]:
    token = request.headers.get("authorization", "")
    if not token:
        raise HTTPException(401, "Not signed in")
    role, _, uid = token.removeprefix("Bearer ").partition(":")
    return {"id": int(uid or 1), "role": role}


USER = {"authorization": "Bearer user:1"}
ADMIN = {"authorization": "Bearer admin:2"}


def paths(env: Env) -> set[tuple[str, str]]:
    spec = env.app.openapi()  # type: ignore[union-attr]
    return {(method.upper(), path) for path, ops in spec["paths"].items() for method in ops}


async def test_generated_routes_under_prefix(env: Env) -> None:
    @Controller("/api/countries", tags=["geo"])
    @Crud(Country)
    class CountriesController:
        pass

    env.app_with(CountriesController.router)
    assert paths(env) == {("GET", "/api/countries"), ("POST", "/api/countries"), ("GET", "/api/countries/{id}"),
                          ("PATCH", "/api/countries/{id}"), ("DELETE", "/api/countries/{id}")}
    assert env.app.openapi()["paths"]["/api/countries"]["get"]["tags"] == ["geo"]  # type: ignore[union-attr]
    async with env.client() as c:
        cid = (await c.post("/api/countries", json={"name": "India"})).json()["data"]["id"]
        assert (await c.get(f"/api/countries/{cid}")).json()["data"]["name"] == "India"
        assert (await c.patch(f"/api/countries/{cid}", json={"code": "IN"})).json()["data"]["code"] == "IN"
        assert (await c.delete(f"/api/countries/{cid}")).status_code == 200


async def test_decorator_order_does_not_matter(env: Env) -> None:
    @Crud(Tag)
    @Controller("/t")
    class TagsController:
        pass

    env.app_with(TagsController.router)
    async with env.client() as c:
        assert (await c.get("/t")).status_code == 200


async def test_method_overrides_path_and_post_processes(env: Env) -> None:
    @Controller("/api/countries")
    @Crud(Country)
    class CountriesController:
        @CrudDetails("/{id}/full")
        async def details(self, result: CrudResult) -> CrudResult:
            result.body["data"]["display"] = result.body["data"]["name"].upper()
            return result

        @CrudList()
        async def list(self, result: CrudResult) -> dict[str, Any]:
            return {"names": [row["name"] for row in result.body["data"]]}  # replaces the body

        @CrudDelete()
        async def remove(self, result: CrudResult) -> Any:
            return PlainTextResponse("gone", status_code=200)

        @CrudCreate()
        async def create(self) -> None: ...  # empty body: crudman's response as-is

    env.app_with(CountriesController.router)
    assert ("GET", "/api/countries/{id}") not in paths(env)
    async with env.client() as c:
        cid = (await c.post("/api/countries", json={"name": "India"})).json()["data"]["id"]
        assert (await c.get(f"/api/countries/{cid}/full")).json()["data"]["display"] == "INDIA"
        assert (await c.get("/api/countries")).json() == {"names": ["India"]}
        assert (await c.delete(f"/api/countries/{cid}")).text == "gone"


class Greeter:
    def hello(self, name: str) -> str:
        return f"hello {name}"


class StateIn(BaseModel):
    name: str


async def test_custom_routes_with_injection(env: Env) -> None:
    # Greeter and StateIn are module-level types referenced through string annotations
    # (from __future__ import annotations), which crudman resolves in this module.
    @Controller("/api/countries")
    @Crud(Country)
    class CountriesController:
        def __init__(self, greeter: Greeter = Depends(Greeter)) -> None:
            self.greeter = greeter

        @Get("/{id}/greeting")
        async def greeting(self, id: int, request: Request) -> dict[str, str]:
            r = await self.crud.details("countries", request)
            return {"msg": self.greeter.hello(r.body["data"]["name"])}

        @Post("/{id}/states", status_code=201)
        async def add_state(self, id: int, body: StateIn) -> CrudResult:
            return await self.crud.call_action("states", "create", body={"name": body.name, "country_id": id})

    env.app_with(CountriesController.router, cm.crud_router(State))
    async with env.client() as c:
        cid = (await c.post("/api/countries", json={"name": "India"})).json()["data"]["id"]
        assert (await c.get(f"/api/countries/{cid}/greeting")).json() == {"msg": "hello India"}
        r = await c.post(f"/api/countries/{cid}/states", json={"name": "Goa"})
        assert r.json()["data"]["country_id"] == cid
    op = env.app.openapi()["paths"]["/api/countries/{id}/states"]["post"]  # type: ignore[union-attr]
    assert op["operationId"] == "CountriesController_add_state"
    assert "requestBody" in op


async def test_auth_decorators_on_controller(env: Env) -> None:
    @Controller("/api/companies")
    @Private()
    @Crud(Company)
    class CompaniesController:
        @Public()
        @CrudList()
        async def list(self): ...

        @Roles("admin")
        @CrudDelete()
        async def remove(self): ...

        @Get("/whoami")
        async def whoami(self, request: Request) -> dict[str, Any]:
            return {"role": request.state.identity["role"]}

        @Public()
        @Get("/ping")
        async def ping(self) -> str:
            return "pong"

    env.app_with(CompaniesController.router, auth=AuthOptions(dependency=current_user))
    async with env.client() as c:
        assert (await c.get("/api/companies")).status_code == 200
        assert (await c.post("/api/companies", json={"name": "A"})).status_code == 401
        cid = (await c.post("/api/companies", json={"name": "A"}, headers=USER)).json()["data"]["id"]
        assert (await c.get(f"/api/companies/{cid}")).status_code == 401
        assert (await c.delete(f"/api/companies/{cid}", headers=USER)).status_code == 403
        assert (await c.delete(f"/api/companies/{cid}", headers=ADMIN)).status_code == 200
        assert (await c.get("/api/companies/whoami")).status_code == 401
        assert (await c.get("/api/companies/whoami", headers=ADMIN)).json() == {"role": "admin"}
        assert (await c.get("/api/companies/ping")).json() == "pong"


async def test_controller_routes_are_public_by_default(env: Env) -> None:
    @Controller("/tags")
    @Crud(Tag)
    class TagsController:
        @Private()
        @CrudCreate()
        async def create(self): ...

    env.app_with(TagsController.router, auth=AuthOptions(dependency=current_user))
    async with env.client() as c:
        assert (await c.get("/tags")).status_code == 200
        assert (await c.post("/tags", json={"name": "x"})).status_code == 401


async def test_several_sections_in_one_controller(env: Env) -> None:
    @Controller("/api")
    @Crud(Tag)
    @Crud(Category, path="/cats", actions=["list"])
    class CatalogController:
        @CrudSave(section="tags")
        async def save_tag(self): ...

        @Get("/stats")
        async def stats(self) -> dict[str, int]:
            return {"ok": 1}

    env.app_with(CatalogController.router)
    got = paths(env)
    assert {("GET", "/api/tags"), ("POST", "/api/tags/save"), ("GET", "/api/cats"), ("GET", "/api/stats")} <= got
    assert ("POST", "/api/cats") not in got


async def test_actions_empty_mounts_only_declared_routes(env: Env) -> None:
    @Controller("/countries")
    @Crud(Country, actions=[])
    class CountriesController:
        @CrudList("/all")
        async def all(self): ...

    env.app_with(CountriesController.router)
    assert paths(env) == {("GET", "/countries/all")}


async def test_slug_selection_field_and_custom_path(env: Env) -> None:
    @Controller("/posts")
    @Crud(PostModel, config={"record_selection_field": "slug"})
    class PostsController:
        @CrudDetails("/by-slug/{slug}")
        async def details(self): ...

    env.app_with(PostsController.router)
    async with env.client() as c:
        await c.post("/posts", json={"slug": "hello", "title": "Hi"})
        assert (await c.get("/posts/by-slug/hello")).json()["data"]["title"] == "Hi"
        assert (await c.patch("/posts/hello", json={"title": "Yo"})).json()["data"]["title"] == "Yo"


async def test_include_via_init_and_helper(env: Env) -> None:
    @Controller("/a")
    @Crud(Tag)
    class A:
        pass

    @Controller("/b")
    @Crud(Category)
    class B:
        pass

    app = env.app_with(controllers=[A])
    include_controllers(app, [B])
    async with env.client() as c:
        assert (await c.get("/a")).status_code == 200
        assert (await c.get("/b")).status_code == 200


async def test_lowercase_aliases(env: Env) -> None:
    @cm.controller("/x")
    @cm.crud_resource(Tag)
    @cm.private()
    class X:
        @cm.public()
        @cm.crud_list()
        async def list(self): ...

        @cm.get("/hello")
        async def hello(self) -> str:
            return "hi"

    env.app_with(X.router, auth=AuthOptions(dependency=current_user))
    async with env.client() as c:
        assert (await c.get("/x")).status_code == 200
        assert (await c.get("/x/hello")).status_code == 401


# ── startup errors ────────────────────────────────────────────────────────────


def test_crud_method_without_crud_class() -> None:
    @Controller("/x")
    class X:
        @CrudList()
        async def list(self): ...

    with pytest.raises(CrudmanConfigError, match="add @Crud"):
        _ = X.router


def test_ambiguous_section() -> None:
    @Controller("/x")
    @Crud(Tag)
    @Crud(Category)
    class X:
        @CrudList()
        async def list(self): ...

    with pytest.raises(CrudmanConfigError, match="pass section="):
        _ = X.router


def test_unknown_section() -> None:
    @Controller("/x")
    @Crud(Tag)
    class X:
        @CrudList(section="nope")
        async def list(self): ...

    with pytest.raises(CrudmanConfigError, match="not declared"):
        _ = X.router


def test_duplicate_routes() -> None:
    @Controller("/x")
    @Crud(Tag)
    class X:
        @Get("")
        async def clash(self) -> None: ...

    with pytest.raises(CrudmanConfigError, match="defined by both"):
        _ = X.router


def test_two_route_decorators_on_one_method() -> None:
    with pytest.raises(CrudmanConfigError, match="more than one route"):
        @Get("/a")
        @Post("/a")
        async def handler() -> None: ...


def test_details_route_needs_path_param() -> None:
    @Controller("/x")
    @Crud(Tag)
    class X:
        @CrudDetails("/one")
        async def details(self): ...

    with pytest.raises(CrudmanConfigError, match="needs a path parameter"):
        _ = X.router
