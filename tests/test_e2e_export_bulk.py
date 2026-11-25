"""CSV / Excel export, bulk import and bulk delete."""

from __future__ import annotations

import csv
import io
import json
from urllib.parse import unquote

from openpyxl import load_workbook
from sqlalchemy import func, select

from crudman import crud_router

from .conftest import Env
from .models import Country, State, User

BULK = ["*", "bulk_import", "bulk_delete"]


async def seed(env: Env) -> None:
    await env.add(Country(name="India", code="IN", states=[State(name="Kerala")]), Country(name="Japan", code="JP"))


async def test_csv_export_list(env: Env) -> None:
    await seed(env)
    env.app_with(crud_router(Country))
    async with env.client() as c:
        r = await c.get("/countries?sort.name=asc&page=1&perPage=10", headers={"x-content-type": "csv"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert [row["name"] for row in rows] == ["India", "Japan"]
    assert json.loads(rows[0]["states"])[0]["name"] == "Kerala"  # lists become JSON
    assert r.headers["x-pagination-total"] == "2" and r.headers["x-pagination-perpage"] == "10"
    assert json.loads(unquote(r.headers["x-sorting"])) == [{"field": "name", "order": "ASC"}]


async def test_csv_via_query_and_accept_and_details(env: Env) -> None:
    await seed(env)
    env.app_with(crud_router(State))
    async with env.client() as c:
        r = await c.get("/states?format=csv")
        assert "country.name" in r.text.splitlines()[0]  # nested object flattened
        r = await c.get("/states/1", headers={"accept": "text/csv"})
        assert r.text.splitlines()[1].startswith("1,Kerala")


async def test_excel_export(env: Env) -> None:
    await seed(env)
    env.app_with(crud_router(Country, config={"relations": []}))
    async with env.client() as c:
        r = await c.get("/countries?sort.name=asc", headers={"x-content-type": "excel"})
    assert r.headers["content-disposition"] == 'attachment; filename="countries.xlsx"'
    ws = load_workbook(io.BytesIO(r.content)).active
    assert [cell.value for cell in ws[1]] == ["id", "name", "code"]
    assert ws["B2"].value == "India"


async def test_export_types_can_be_limited(env: Env) -> None:
    env.app_with(crud_router(Country), export_content_types=["json"])
    async with env.client() as c:
        r = await c.get("/countries", headers={"x-content-type": "csv"})
    assert r.headers["content-type"].startswith("application/json")


async def count(env: Env, model: type) -> int:
    return int(await env.scalar(select(func.count()).select_from(model)))


async def test_bulk_import_upsert_json(env: Env) -> None:
    await seed(env)
    env.app_with(crud_router(Country, actions=BULK))
    async with env.client() as c:
        r = await c.post("/countries/bulk/import", json=[
            {"id": 1, "name": "Bharat"}, {"name": "Nepal"}, {"name": ""}])
    body = r.json()
    assert body["data"]["updated"] == 1 and body["data"]["inserted"] == 1 and body["data"]["errorsCount"] == 1
    assert body["data"]["rowErrors"][0]["row"] == 3 and body["success"] is False
    assert await count(env, Country) == 3


async def test_bulk_import_policies(env: Env) -> None:
    await seed(env)
    env.app_with(crud_router(Country, actions=BULK))
    async with env.client() as c:
        r = await c.post("/countries/bulk/import?policy=insert_only", json=[{"id": 1, "name": "X"}, {"name": "Y"}])
        assert r.json()["data"]["inserted"] == 1 and r.json()["data"]["rowErrors"][0]["errors"][0]["type"] == "exists"
        r = await c.post("/countries/bulk/import?policy=update_only", json=[{"id": 99, "name": "Z"}])
        assert r.json()["data"]["rowErrors"][0]["errors"][0]["type"] == "notFound"
        r = await c.post("/countries/bulk/import?policy=ignore_on_conflict", json=[{"id": 2, "name": "Q"}])
        assert r.json()["data"]["skipped"] == 1
        r = await c.post("/countries/bulk/import?policy=replace", json=[{"name": "Only"}])
        assert r.json()["data"]["deleted"] == 3 and r.json()["data"]["inserted"] == 1
    assert await count(env, Country) == 1


async def test_bulk_import_dry_run_and_stop_on_error(env: Env) -> None:
    env.app_with(crud_router(Country, actions=BULK))
    async with env.client() as c:
        r = await c.post("/countries/bulk/import", json={"items": [{"name": "A"}], "dry_run": True})
        assert r.json()["data"]["inserted"] == 1 and r.json()["data"]["dryRun"] is True
        r = await c.post("/countries/bulk/import?stop_on_error=true", json=[{"name": ""}, {"name": "B"}])
        assert r.json()["data"]["inserted"] == 0
    assert await count(env, Country) == 0


async def test_bulk_import_csv_with_selection_field(env: Env) -> None:
    await env.add(User(name="A", email="a@x.io"))
    env.app_with(crud_router(User, actions=BULK))
    text = "email,name,phone\na@x.io,Alice,\nb@x.io,Bob,555\n"
    async with env.client() as c:
        r = await c.post("/users/bulk/import?record_selection_field=email", content=text,
                         headers={"content-type": "text/csv"})
    assert r.json()["data"] == {"inserted": 1, "updated": 1, "deleted": 0, "skipped": 0, "errorsCount": 0,
                                "dryRun": False, "policy": "upsert", "rowErrors": []}
    async with env.client() as c:
        names = sorted(u["name"] for u in (await c.get("/users")).json()["data"])
    assert names == ["Alice", "Bob"]


async def test_bulk_delete_json_and_csv(env: Env) -> None:
    await env.add(*[Country(name=f"C{i}") for i in range(5)])
    env.app_with(crud_router(Country, actions=BULK))
    async with env.client() as c:
        r = await c.post("/countries/bulk/delete", json={"ids": [1, 2, 99]})
        assert r.json()["data"] == {"deleted": 2, "notFound": [99]}
        r = await c.post("/countries/bulk/delete", content="id\n3\n4\n", headers={"content-type": "text/csv"})
        assert r.json()["data"]["deleted"] == 2
    assert await count(env, Country) == 1


async def test_bulk_routes_are_documented(env: Env) -> None:
    env.app_with(crud_router(Country, actions=BULK))
    paths = env.app.openapi()["paths"]  # type: ignore[union-attr]
    assert "/countries/bulk/import" in paths and "/countries/bulk/delete" in paths
    assert "text/csv" in paths["/countries/bulk/import"]["post"]["requestBody"]["content"]
