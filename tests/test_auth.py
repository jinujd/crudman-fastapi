"""Per-route auth: public by default, @Private / @Roles / @Public, crud_router options and section config."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from crudman import AuthOptions, CrudmanConfigError, Private, Public, Roles, crud_router

from .conftest import Env
from .models import Company, Note, Tag

bearer = HTTPBearer(auto_error=False)


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict[str, Any]:
    """Test tokens: "Bearer <role>:<id>"."""
    if creds is None:
        raise HTTPException(401, "Not signed in")
    role, _, uid = creds.credentials.partition(":")
    return {"id": int(uid or 1), "role": role}


USER = {"authorization": "Bearer user:1"}
ADMIN = {"authorization": "Bearer admin:2"}
AUTH = {"auth": AuthOptions(dependency=current_user)}


async def test_routes_are_public_by_default(env: Env) -> None:
    env.app_with(crud_router(Tag), **AUTH)
    async with env.client() as c:
        assert (await c.post("/tags", json={"name": "a"})).status_code == 200
        assert (await c.get("/tags")).status_code == 200


async def test_crud_router_private(env: Env) -> None:
    env.app_with(crud_router(Tag, auth="private"), **AUTH)
    async with env.client() as c:
        assert (await c.get("/tags")).status_code == 401
        assert (await c.get("/tags", headers=USER)).status_code == 200


async def test_crud_router_per_action_options(env: Env) -> None:
    env.app_with(crud_router(Tag, auth="private", public=["list"], roles={"delete": ["admin"]}), **AUTH)
    async with env.client() as c:
        assert (await c.get("/tags")).status_code == 200
        assert (await c.post("/tags", json={"name": "a"})).status_code == 401
        tid = (await c.post("/tags", json={"name": "a"}, headers=USER)).json()["data"]["id"]
        r = await c.delete(f"/tags/{tid}", headers=USER)
        assert r.status_code == 403 and r.json()["detail"]["errors"][0]["type"] == "forbidden"
        assert (await c.delete(f"/tags/{tid}", headers=ADMIN)).status_code == 200


async def test_crud_router_private_actions_list(env: Env) -> None:
    env.app_with(crud_router(Tag, private=["create"]), **AUTH)
    async with env.client() as c:
        assert (await c.get("/tags")).status_code == 200
        assert (await c.post("/tags", json={"name": "a"})).status_code == 401


async def test_section_config_auth(env: Env) -> None:
    env.app_with(crud_router(Tag, config={"auth": "private", "list": {"auth": "public"}}), **AUTH)
    async with env.client() as c:
        assert (await c.get("/tags")).status_code == 200
        assert (await c.post("/tags", json={"name": "a"})).status_code == 401


async def test_default_private_option(env: Env) -> None:
    env.app_with(crud_router(Tag, public=["list"]), auth=AuthOptions(dependency=current_user, default="private"))
    async with env.client() as c:
        assert (await c.get("/tags")).status_code == 200
        assert (await c.post("/tags", json={"name": "a"})).status_code == 401


async def test_identity_feeds_ownership(env: Env) -> None:
    env.app_with(crud_router(Note, auth="private", config={"ownership": {"field": "owner_id"}}), **AUTH)
    async with env.client() as c:
        created = (await c.post("/notes", json={"text": "x"}, headers={"authorization": "Bearer user:7"})).json()
        assert created["data"]["owner_id"] == 7


async def test_dependency_returning_object(env: Env) -> None:
    class User:
        id = 5
        role = "admin"

    env.app_with(crud_router(Tag, roles=["admin"]), auth=AuthOptions(dependency=lambda: User()))
    async with env.client() as c:
        assert (await c.get("/tags")).status_code == 200


async def test_dependency_returning_none_is_401(env: Env) -> None:
    env.app_with(crud_router(Tag, auth="private"), auth=AuthOptions(dependency=lambda: None))
    async with env.client() as c:
        r = await c.get("/tags")
    assert r.status_code == 401 and r.json()["detail"]["errors"][0]["type"] == "unauthorized"


async def test_roles_with_custom_role_checker(env: Env) -> None:
    auth = AuthOptions(dependency=lambda: {"id": 1, "perms": ["editor"]})
    env.app_with(crud_router(Tag, roles=["editor"]), auth=auth,
                 role_checker=lambda identity, roles: bool(set(identity["perms"]) & set(roles)))
    async with env.client() as c:
        assert (await c.get("/tags")).status_code == 200


async def test_roles_list_on_identity(env: Env) -> None:
    env.app_with(crud_router(Tag, roles=["b"]), auth=AuthOptions(dependency=lambda: {"id": 1, "roles": ["a", "b"]}))
    async with env.client() as c:
        assert (await c.get("/tags")).status_code == 200


async def test_openapi_shows_security_only_on_private_routes(env: Env) -> None:
    from crudman import Crudman, CrudmanOptions

    Crudman.init(None, CrudmanOptions(**AUTH))  # init before building routers → Swagger shows the lock
    env.app_with(crud_router(Tag, private=["create"]), **AUTH)
    paths = env.app.openapi()["paths"]  # type: ignore[union-attr]
    assert paths["/tags"]["post"]["security"] == [{"HTTPBearer": []}]
    assert "security" not in paths["/tags"]["get"]


async def test_private_without_auth_options_is_a_clear_error(env: Env) -> None:
    env.app_with(crud_router(Tag, auth="private"))
    async with env.client() as c:
        with pytest.raises(RuntimeError, match="no authentication is configured"):
            await c.get("/tags")


async def test_routers_built_before_init_still_work(env: Env) -> None:
    router = crud_router(Tag, auth="private")  # options not set yet → placeholder dependency
    env.app_with(router, **AUTH)  # Crudman.init points the placeholder at current_user
    async with env.client() as c:
        assert (await c.get("/tags")).status_code == 401
        assert (await c.get("/tags", headers=USER)).status_code == 200


# ── decorators on plain FastAPI routes ────────────────────────────────────────


async def test_decorators_on_plain_routes(env: Env) -> None:
    from crudman import Crudman, CrudmanOptions

    Crudman.init(None, CrudmanOptions(**AUTH))  # so the decorators see the real dependency
    router = APIRouter()

    @router.get("/open")
    @Public()
    async def open_route() -> dict[str, str]:
        return {"ok": "yes"}

    @router.get("/me")
    @Private()
    async def me(request: Request) -> dict[str, Any]:
        return {"id": request.state.identity["id"]}

    @router.get("/admin/{item}")
    @Roles("admin")
    async def admin_only(item: str) -> dict[str, str]:
        return {"item": item}

    env.app_with(router, **AUTH)
    async with env.client() as c:
        assert (await c.get("/open")).json() == {"ok": "yes"}
        assert (await c.get("/me")).status_code == 401
        assert (await c.get("/me", headers={"authorization": "Bearer user:9"})).json() == {"id": 9}
        assert (await c.get("/admin/x", headers=USER)).status_code == 403
        assert (await c.get("/admin/x", headers=ADMIN)).json() == {"item": "x"}
    assert env.app.openapi()["paths"]["/me"]["get"]["security"] == [{"HTTPBearer": []}]  # type: ignore[union-attr]


def test_conflicting_decorators_fail() -> None:
    with pytest.raises(CrudmanConfigError, match="conflicting"):
        @Public()
        @Roles("admin")
        async def handler() -> None: ...


def test_roles_needs_a_role() -> None:
    with pytest.raises(CrudmanConfigError):
        Roles()


def test_unknown_action_in_crud_router_auth_options() -> None:
    with pytest.raises(CrudmanConfigError, match="unknown action"):
        crud_router(Company, public=["lists"])


async def test_default_private_set_after_routers_were_built(env: Env) -> None:
    router = crud_router(Tag, public=["list"])  # built before auth is configured
    env.app_with(router, auth=AuthOptions(dependency=current_user, default="private"))
    async with env.client() as c:
        assert (await c.get("/tags")).status_code == 200
        assert (await c.post("/tags", json={"name": "a"})).status_code == 401
        assert (await c.post("/tags", json={"name": "a"}, headers=USER)).status_code == 200


async def test_default_public_set_after_routers_were_built(env: Env) -> None:
    router = crud_router(Tag)
    env.app_with(router, **AUTH)
    async with env.client() as c:
        assert (await c.post("/tags", json={"name": "a"})).status_code == 200


class NoteIn(BaseModel):
    text: str


async def test_private_plain_route_with_body_model(env: Env) -> None:
    router = APIRouter()

    @router.post("/echo")
    @Private()
    async def echo(body: NoteIn, request: Request) -> dict[str, Any]:
        return {"text": body.text, "by": request.state.identity["id"]}

    env.app_with(router, **AUTH)
    async with env.client() as c:
        assert (await c.post("/echo", json={"text": "hi"})).status_code == 401
        r = await c.post("/echo", json={"text": "hi"}, headers={"authorization": "Bearer user:3"})
        assert r.json() == {"text": "hi", "by": 3}
