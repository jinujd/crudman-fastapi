"""Basic CRUD, routing and naming against a real SQLite database."""

from __future__ import annotations

import pytest
from fastapi import APIRouter

from crudman import CrudController, CrudmanConfigError, crud_router

from .conftest import Env
from .models import Category, Company, Country, State, Tag, UserProfile


async def test_full_crud_cycle(env: Env) -> None:
    env.app_with(crud_router(Company))
    async with env.client() as c:
        r = await c.post("/companies", json={"name": "Acme Air", "email": "hi@acme.test"})
        assert r.status_code == 200
        created = r.json()
        assert created["success"] is True and created["errors"] == []
        cid = created["data"]["id"]
        assert created["data"]["name"] == "Acme Air"
        assert created["data"]["is_active"] is True  # DB default applied
        assert created["data"]["contacts"] == []  # relations included by default

        r = await c.get("/companies")
        body = r.json()
        assert r.status_code == 200
        assert [row["id"] for row in body["data"]] == [cid]
        assert body["pagination"]["totalItemsCount"] == 1

        r = await c.get(f"/companies/{cid}")
        assert r.json()["data"]["email"] == "hi@acme.test"

        r = await c.patch(f"/companies/{cid}", json={"is_active": False})
        assert r.status_code == 200
        assert r.json()["data"]["is_active"] is False
        assert r.json()["data"]["name"] == "Acme Air"  # partial update keeps other fields

        r = await c.delete(f"/companies/{cid}")
        assert r.json() == {"data": {"message": "Successfully deleted"}, "errors": [], "success": True}

        r = await c.get(f"/companies/{cid}")
        assert r.status_code == 404
        assert r.json()["success"] is False


async def test_missing_records_return_404(env: Env) -> None:
    env.app_with(crud_router(Company))
    async with env.client() as c:
        assert (await c.get("/companies/99")).status_code == 404
        assert (await c.patch("/companies/99", json={"name": "x"})).status_code == 404
        assert (await c.delete("/companies/99")).status_code == 404


async def test_section_name_defaults_to_table_name(env: Env) -> None:
    env.app_with(crud_router(Country), crud_router(UserProfile))
    paths = set(env.app.openapi()["paths"])  # type: ignore[union-attr]
    assert {"/countries", "/countries/{id}", "/user_profiles", "/user_profiles/{id}"} <= paths


async def test_explicit_section_name_path_and_prefix(env: Env) -> None:
    env.app_with((crud_router(Company, "orgs"), "/api"), crud_router(Country, path="/nations"),
                 (crud_router(Tag, path=""), "/labels"))
    async with env.client() as c:
        assert (await c.post("/api/orgs", json={"name": "A"})).status_code == 200
        assert (await c.get("/nations")).status_code == 200
        assert (await c.get("/labels")).status_code == 200


async def test_keyword_form_and_path_style(env: Env) -> None:
    env.app_with(crud_router(model=UserProfile, path_style="kebab"))
    async with env.client() as c:
        assert (await c.get("/user-profiles")).status_code == 200


async def test_route_prefix_option(env: Env) -> None:
    from crudman import Crudman, CrudmanOptions

    Crudman.init(None, CrudmanOptions(route_prefix="/v1"))
    router = crud_router(Tag)
    env.app_with(router, route_prefix="/v1")
    async with env.client() as c:
        assert (await c.get("/v1/tags")).status_code == 200


async def test_multi_model_router(env: Env) -> None:
    env.app_with((crud_router([Tag, Category, (Country, "nations"), (State, "regions", {"relations": []})]), "/api"))
    async with env.client() as c:
        for path in ("/api/tags", "/api/categories", "/api/nations", "/api/regions"):
            assert (await c.get(path)).status_code == 200, path


async def test_actions_filter_and_extras(env: Env) -> None:
    env.app_with(crud_router(Tag, actions=["list", "details"]), crud_router(Category, actions=["*", "save"]))
    async with env.client() as c:
        assert (await c.post("/tags", json={"name": "x"})).status_code == 405
        assert (await c.post("/categories/save", json={"name": "c"})).status_code == 200


async def test_put_update_method(env: Env) -> None:
    env.app_with(crud_router(Tag, update_method="put"))
    async with env.client() as c:
        tid = (await c.post("/tags", json={"name": "a"})).json()["data"]["id"]
        assert (await c.patch(f"/tags/{tid}", json={"name": "b"})).status_code == 405
        assert (await c.put(f"/tags/{tid}", json={"name": "b"})).json()["data"]["name"] == "b"


async def test_strict_status(env: Env) -> None:
    env.app_with(crud_router(Tag), strict_status=True)
    async with env.client() as c:
        assert (await c.post("/tags", json={"name": "a"})).status_code == 201


async def test_class_based_controller(env: Env) -> None:
    class TagsController(CrudController, model=Tag, prefix="/api"):
        pass

    env.app_with(TagsController.router)
    assert TagsController.section == "tags"
    async with env.client() as c:
        assert (await c.post("/api/tags", json={"name": "t"})).status_code == 200


async def test_save_upsert(env: Env) -> None:
    env.app_with(crud_router(Tag, actions=["*", "save"]))
    async with env.client() as c:
        first = (await c.post("/tags/save", json={"name": "one"})).json()["data"]
        updated = (await c.post("/tags/save", json={"id": first["id"], "name": "uno"})).json()["data"]
        assert updated == {"id": first["id"], "name": "uno"}
        listed = (await c.get("/tags")).json()["data"]
        assert len(listed) == 1


async def test_record_selection_field_slug(env: Env) -> None:
    from .models import Post

    env.app_with(crud_router(Post, config={"record_selection_field": "slug"}))
    assert "/posts/{slug}" in env.app.openapi()["paths"]  # type: ignore[union-attr]
    async with env.client() as c:
        await c.post("/posts", json={"slug": "hello-world", "title": "Hello"})
        r = await c.get("/posts/hello-world")
        assert r.json()["data"]["title"] == "Hello"
        r = await c.patch("/posts/hello-world", json={"title": "Hi"})
        assert r.json()["data"]["title"] == "Hi"
        assert (await c.delete("/posts/hello-world")).status_code == 200


def test_duplicate_section_names_fail() -> None:
    crud_router(Tag)
    with pytest.raises(CrudmanConfigError, match="already registered"):
        crud_router(Tag, config={"relations": []})


def test_same_router_twice_is_fine() -> None:
    crud_router(Tag)
    crud_router(Tag)


def test_misconfigured_section_fails_at_startup() -> None:
    with pytest.raises(CrudmanConfigError) as info:
        crud_router(Company, config={"list": {"filters_whitelist": ["nope"]}, "relations": ["ghost"]})
    message = str(info.value)
    assert "'nope' is not a column" in message and "'ghost' is not a relationship" in message


def test_unknown_config_key_fails() -> None:
    with pytest.raises(CrudmanConfigError, match="filter_whitelist"):
        crud_router(Company, config={"filter_whitelist": ["name"]})


def test_list_of_models_rejects_extra_arguments() -> None:
    with pytest.raises(CrudmanConfigError):
        crud_router([Tag], "x")


def test_router_is_apirouter() -> None:
    assert isinstance(crud_router(Tag), APIRouter)


async def test_session_missing_gives_clear_error(env: Env) -> None:
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(crud_router(Tag))
    async with env.client(app) as c:
        with pytest.raises(RuntimeError, match="Crudman.init"):
            await c.get("/tags")


async def test_openapi_documents_bodies_and_params(env: Env) -> None:
    env.app_with(crud_router(Company, config={"uploadable": {"avatar": "image"}, "upload_defaults": {}}))
    spec = env.app.openapi()  # type: ignore[union-attr]
    create = spec["paths"]["/companies"]["post"]
    schema = create["requestBody"]["content"]["application/json"]["schema"]
    assert "name" in schema["properties"] and "name" in schema["required"]
    assert "id" not in schema["properties"] and "created_at" not in schema["properties"]
    multipart = create["requestBody"]["content"]["multipart/form-data"]["schema"]
    assert multipart["properties"]["avatar"] == {"type": "string", "format": "binary"}
    list_op = spec["paths"]["/companies"]["get"]
    assert {p["name"] for p in list_op["parameters"]} >= {"page", "perPage", "keyword", "x-content-type"}
    assert list_op["operationId"] == "companies_list"
    item = list_op["responses"]["200"]["content"]["application/json"]["schema"]["properties"]["data"]["items"]
    assert "contacts" in item["properties"]
