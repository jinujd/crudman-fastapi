"""README feature tour: every documented feature wired into ONE app at the same time.

The other e2e modules test features in isolation. This one mounts all of them together, the way a real
app does: two sections on one model, roles + cache + hooks on the same section, several routers, custom
routes and ``call_action``, so interactions between features are covered too.

It uses its own ``tour_*`` tables (separate metadata) so it never collides with ``tests/models.py``.
"""

from __future__ import annotations

import base64
import io
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import AsyncClient
from sqlalchemy import JSON, ForeignKey, LargeBinary, Select, String, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from crudman import (
    ActionConfig,
    CacheOptions,
    CrudController,
    CrudmanConfigError,
    CrudmanService,
    DetailsAction,
    Keyword,
    ListAction,
    LocalStorage,
    Pagination,
    Section,
    WriteAction,
    crud,
    crud_router,
    get_crud,
)

from .conftest import DATABASE_URL, Env

# ── models ─────────────────────────────────────────────────────────────────────


class TourBase(DeclarativeBase):
    pass


class TCompany(TourBase):
    __tablename__ = "tour_companies"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    email: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True)
    employees: Mapped[int] = mapped_column(default=0)
    founded_on: Mapped[date | None]
    secret: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    contacts: Mapped[list[TContact]] = relationship(back_populates="company", cascade="all, delete-orphan")


class TContact(TourBase):
    __tablename__ = "tour_contacts"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255))
    company_id: Mapped[int] = mapped_column(ForeignKey("tour_companies.id"))
    company: Mapped[TCompany] = relationship(back_populates="contacts")


class TCountry(TourBase):
    __tablename__ = "tour_countries"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    states: Mapped[list[TState]] = relationship(back_populates="country")


class TState(TourBase):
    __tablename__ = "tour_states"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    country_id: Mapped[int] = mapped_column(ForeignKey("tour_countries.id"))
    country: Mapped[TCountry] = relationship(back_populates="states")


class TNote(TourBase):
    __tablename__ = "tour_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(100))
    owner_id: Mapped[int]


class TProduct(TourBase):
    __tablename__ = "tour_products"
    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    price: Mapped[float] = mapped_column(default=0)


class TProfile(TourBase):
    __tablename__ = "tour_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    avatar: Mapped[str | None] = mapped_column(String(255))
    photos: Mapped[list[Any] | None] = mapped_column(JSON)
    docBase64: Mapped[str | None]  # noqa: N815 - column name chosen by the ":base64" shorthand
    attachmentBlob: Mapped[bytes | None] = mapped_column(LargeBinary)  # noqa: N815
    attachmentMime: Mapped[str | None] = mapped_column(String(100))  # noqa: N815


class TTag(TourBase):
    __tablename__ = "tour_tags"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))


class TCategory(TourBase):
    __tablename__ = "tour_categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))


class TUserProfile(TourBase):
    __tablename__ = "tour_user_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    nickname: Mapped[str] = mapped_column(String(50))


class TItem(TourBase):
    __tablename__ = "tour_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(50))
    qty: Mapped[int] = mapped_column(default=0)


# ── hooks ──────────────────────────────────────────────────────────────────────

ADMIN = {"x-role": "admin"}


def identity_from_headers(request: Any) -> dict[str, Any]:
    uid = request.headers.get("x-user-id")
    return {"id": int(uid) if uid else None, "role": request.headers.get("x-role")}


async def add_flag(data: list[dict[str, Any]], ctx: Any) -> list[dict[str, Any]]:
    for row in data:
        row["fetchedBy"] = "hook"
    return data


def stamp(result: dict[str, Any], ctx: Any) -> dict[str, Any]:
    result["servedAt"] = datetime.now(UTC).isoformat()
    return result


def final_rules(rules: dict[str, Any], ctx: Any) -> dict[str, Any]:
    return {**rules, "name": {"type": "string", "min": 3, "max": 100}}


async def block_reserved(errors: list[dict[str, Any]], ctx: Any) -> bool | None:
    if ctx.body.get("name") == "RESERVED":
        errors.append({"type": "custom", "field": "name", "message": "name is reserved"})
        return False
    return None


def block_when_header(ctx: Any) -> bool | None:
    if ctx.request is not None and ctx.request.headers.get("x-block") == "1":
        return False
    return None


async def build_ctx(ctx: Any) -> dict[str, Any]:
    return {"tenant_id": ctx.request.headers.get("x-tenant-id") if ctx.request else None}


def get_mailer() -> str:
    return "mailer-service"


def tenant_meta(body: Any, ctx: Any) -> dict[str, Any]:
    return {"tenant": ctx.tenant_id, "mailer": ctx.services.get("mailer")}


async def only_named(stmt: Select[Any], ctx: Any) -> Select[Any]:
    return stmt.where(TState.name != "HIDDEN")


def wrap_details(body: dict[str, Any], ctx: Any) -> dict[str, Any]:
    body["meta"] = {**(body.get("meta") or {}), "handled": True}
    return body


# ── the app ────────────────────────────────────────────────────────────────────


def build_app(env: Env) -> FastAPI:
    companies = Section(
        title="Company",
        attributes={"read": {"exclude": ["secret"]}},
        required_roles=["admin"],
        context={"services": {"mailer": Depends(get_mailer)}, "get_hook_context": build_ctx},
        get_additional_response=tenant_meta,
        on_before_action=block_when_header,
        list=ListAction(
            filters_whitelist=["name", "is_active", "employees", "founded_on", "created_at"],
            sorting_whitelist=["name", "employees", "created_at"],
            order_by=[("name", "ASC")],
            keyword=Keyword(searchable_fields=["name", "contacts.email"], min_length=2),
            pagination=Pagination(max_per_page=100),
            enable_cache={"ttl": 60},
            on_after_fetch=add_flag,
            on_after_action=stamp,
        ),
        details=DetailsAction(relations=["contacts"]),
        create=WriteAction(fields_for_uniqueness_validation=["name"],
                           get_final_validation_rules=final_rules, on_after_validate=block_reserved),
        update=WriteAction(fields_for_uniqueness_validation=["name"]),
    )

    class ItemsController(CrudController, model=TItem, section="items", config={"details": {
            "custom_implementation": lambda ctx: {"custom": True, "id": ctx.params["id"]}}}):
        pass

    custom = APIRouter(prefix="/custom")
    crud.register(TTag, "tags_custom")

    @custom.get("/tags")
    @crud.list("tags_custom")
    async def list_tags_custom() -> None:
        """Decorator-based list endpoint."""

    @custom.post("/countries/{country_id}/states")
    async def create_state(country_id: int, body: dict[str, Any],
                           svc: CrudmanService = Depends(get_crud)) -> Any:
        r = await svc.call_action("states", "save", body={**body, "country_id": country_id})
        return r.to_response()

    return env.app_with(
        crud_router(TCompany, "companies", companies),
        # same model, second section: renamed params, custom path, fixed conditions
        crud_router(TCompany, "orgs", {
            "conditions": {"is_active": True},
            "list": {"query_param_names": {"page": "p", "per_page": "pp", "sort_prefix": "order.", "keyword": "q"},
                     "keyword": {"searchable_fields": ["name"]}},
        }, path="/organisations", actions=["list", "details"]),
        crud_router([
            (TCountry, "countries"),
            (TState, "states", {"relations": ["country"], "on_before_query": only_named,
                                "details": {"response_handler": wrap_details}}),
            (TContact, "contacts"),
        ]),
        crud_router(TNote, "notes", {"ownership": {"field": "owner_id"}}),
        crud_router(TProduct, "products", actions=["*", "save", "bulk_import", "bulk_delete"]),
        crud_router(TProfile, "profiles", {
            "uploadable": {"avatar": "image-avatar", "photos": "image[]", "doc": "pdf:base64",
                           "attachment": "any:blob"},
            "attributes": {"read": {"exclude": ["attachmentBlob"]}},
        }),
        crud_router([(TTag, "tags"), (TCategory, "kinds")]),
        crud_router(TUserProfile, "user_profiles", path_style="kebab"),
        ItemsController.router,
        crud_router(TItem, "items_put", path="/items-put", update_method="put"),
        custom,
        identity_accessor=identity_from_headers,
        cache=CacheOptions(enabled=True, ttl=60, invalidate_lists_on_write=True),
        defaults=ActionConfig(additional_response={"api": "v1"}),
        file_storages={"local": LocalStorage(env.tmp_path / "uploads",
                                             public_base_url="http://localhost:8000/files")},
        default_file_storage="local",
    )


@pytest.fixture
async def tour(env: Env) -> Env:
    async with env.engine.begin() as conn:
        if DATABASE_URL:
            await conn.run_sync(TourBase.metadata.drop_all)
        await conn.run_sync(TourBase.metadata.create_all)
    build_app(env)
    return env


async def seed(c: AsyncClient) -> None:
    for payload in [
        {"name": "Acme Air", "email": "a@acme.io", "employees": 50, "founded_on": "2024-03-01", "secret": "s1"},
        {"name": "Boeing Air", "employees": 900, "founded_on": "2023-05-10"},
        {"name": "Contoso", "employees": 10, "founded_on": "2024-11-20", "is_active": False},
        {"name": "Globex", "employees": 300, "founded_on": "2022-01-15"},
        {"name": "Initech", "employees": 120, "founded_on": "2024-07-04"},
    ]:
        r = await c.post("/companies", json=payload, headers=ADMIN)
        assert r.status_code == 200, r.text
    await c.post("/contacts", json={"email": "ceo@acme.io", "company_id": 1})
    await c.post("/contacts", json={"email": "sales@globex.com", "company_id": 4})


def names(r: Any) -> list[str]:
    assert r.status_code == 200, r.text
    return [x["name"] for x in r.json()["data"]]


def png(w: int = 200, h: int = 200) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


# ── tests ──────────────────────────────────────────────────────────────────────


async def test_crud_endpoints_and_envelope(tour: Env) -> None:
    async with tour.client() as c:
        await seed(c)
        b = (await c.get("/companies", headers=ADMIN)).json()
        assert {"data", "errors", "success", "pagination", "filters", "sorting"} <= set(b)
        assert b["pagination"]["totalItemsCount"] == 5
        d = (await c.get("/companies/1", headers=ADMIN)).json()["data"]
        assert d["name"] == "Acme Air" and "secret" not in d
        assert [x["email"] for x in d["contacts"]] == ["ceo@acme.io"]
        r = await c.get("/companies/999", headers=ADMIN)
        assert r.status_code == 404 and r.json()["errors"][0]["type"] == "notFound"
        r = await c.patch("/companies/1", json={"email": "new@acme.io"}, headers=ADMIN)
        assert r.json()["data"]["email"] == "new@acme.io" and r.json()["data"]["name"] == "Acme Air"
        cid = (await c.post("/companies", json={"name": "Temp Co"}, headers=ADMIN)).json()["data"]["id"]
        r = await c.delete(f"/companies/{cid}", headers=ADMIN)
        assert r.json()["data"] == {"message": "Successfully deleted"}
        assert (await c.get(f"/companies/{cid}", headers=ADMIN)).status_code == 404


async def test_relations_and_query_hooks(tour: Env) -> None:
    async with tour.client() as c:
        cid = (await c.post("/countries", json={"name": "India"})).json()["data"]["id"]
        await c.post("/states", json={"name": "Kerala", "country_id": cid})
        await c.post("/states", json={"name": "HIDDEN", "country_id": cid})
        assert "states" in (await c.get(f"/countries/{cid}")).json()["data"]  # all relations by default
        rows = (await c.get("/states")).json()["data"]
        assert [s["name"] for s in rows] == ["Kerala"]  # on_before_query
        assert rows[0]["country"]["name"] == "India"
        assert (await c.get("/states/1")).json()["meta"]["handled"] is True  # response_handler


async def test_filters_sorting_keyword(tour: Env) -> None:
    async with tour.client() as c:
        await seed(c)

        async def q(qs: str) -> list[str]:
            return names(await c.get(f"/companies?{qs}", headers=ADMIN))

        assert await q("") == ["Acme Air", "Boeing Air", "Contoso", "Globex", "Initech"]  # order_by
        assert (await q("sort.employees=desc"))[0] == "Boeing Air"
        r = await c.get("/companies?sort.createdAt=desc", headers=ADMIN)
        assert r.json()["sorting"][0]["field"] == "created_at"
        r = await c.get("/companies?sort.email=desc", headers=ADMIN)  # not whitelisted
        assert all(s["field"] != "email" for s in r.json()["sorting"])
        assert await q("is_active=false") == ["Contoso"]
        assert await q("name.like=AIR") == ["Acme Air", "Boeing Air"]
        assert await q("employees.min=100&employees.max=300") == ["Globex", "Initech"]
        assert await q("employees.gt=50&employees.lt=900") == ["Globex", "Initech"]
        r = await c.get("/companies?founded_on.between=2024-01-01,2024-12-31", headers=ADMIN)
        assert names(r) == ["Acme Air", "Contoso", "Initech"]
        assert r.json()["filters"][0] == {"field": "founded_on", "op": "between",
                                          "value": ["2024-01-01", "2024-12-31"], "param": "founded_on.between"}
        assert len(await q("email=x")) == 5  # not whitelisted
        r = await c.get("/companies?employees.min=abc", headers=ADMIN)
        assert r.status_code == 400 and r.json()["errors"][0]["type"] == "filter"
        assert await q("keyword=glob") == ["Globex"]
        assert await q("keyword=ceo@") == ["Acme Air"]  # relation path
        assert len(await q("keyword=a")) == 5  # below min_length
        assert await q("keyword=air&is_active=true") == ["Acme Air", "Boeing Air"]


async def test_pagination(tour: Env) -> None:
    async with tour.client() as c:
        await seed(c)
        p = (await c.get("/companies?page=2&perPage=2", headers=ADMIN)).json()
        assert [x["name"] for x in p["data"]] == ["Contoso", "Globex"]
        assert p["pagination"] == {"page": 2, "perPage": 2, "totalItemsCount": 5, "totalPagesCount": 3,
                                   "isHavingNextPage": True, "isHavingPreviousPage": True}
        assert (await c.get("/companies?per_page=3", headers=ADMIN)).json()["pagination"]["perPage"] == 3
        for qs in ("paginate=false", "paginate=0", "paginate=no", "perPage=0"):
            assert len((await c.get(f"/companies?{qs}", headers=ADMIN)).json()["data"]) == 5, qs
        assert (await c.get("/companies?perPage=500", headers=ADMIN)).json()["pagination"]["perPage"] == 100


async def test_second_section_on_same_model(tour: Env) -> None:
    async with tour.client() as c:
        await seed(c)
        r = await c.get("/organisations?pp=2&p=1&order.name=desc")
        assert names(r) == ["Initech", "Globex"]
        assert r.json()["pagination"]["totalItemsCount"] == 4  # conditions: inactive Contoso excluded
        assert names(await c.get("/organisations?q=boe")) == ["Boeing Air"]
        assert (await c.get("/organisations/3")).status_code == 404  # conditions apply to details


async def test_validation(tour: Env) -> None:
    async with tour.client() as c:
        await seed(c)
        r = await c.post("/companies", json={"email": "x@y.z"}, headers=ADMIN)
        assert r.status_code == 400 and any(e["field"] == "name" for e in r.json()["errors"])
        r = await c.post("/companies", json={"name": "Typed", "employees": "lots"}, headers=ADMIN)
        assert r.status_code == 400 and r.json()["errors"][0]["field"] == "employees"
        r = await c.post("/companies", json={"name": "AB"}, headers=ADMIN)  # get_final_validation_rules
        assert r.status_code == 400 and r.json()["errors"][0]["field"] == "name"
        r = await c.post("/companies", json={"name": "Globex"}, headers=ADMIN)
        assert r.status_code == 400
        assert r.json() == {"data": None, "success": False,
                            "errors": [{"type": "unique", "field": "name", "message": "name must be unique"}]}
        assert (await c.patch("/companies/4", json={"name": "Globex"}, headers=ADMIN)).status_code == 200
        assert (await c.patch("/companies/4", json={"name": "Initech"}, headers=ADMIN)).status_code == 400
        r = await c.post("/companies", json={"name": "RESERVED"}, headers=ADMIN)
        assert r.status_code == 400 and r.json()["errors"][0]["message"] == "name is reserved"
        assert (await c.post("/products", json={"sku": "P1", "name": "Pen"})).status_code == 200
        r = await c.post("/products", json={"sku": "P1", "name": "Dup"})
        assert r.status_code == 409 and r.json()["errors"][0]["type"] == "conflict"
        assert (await c.get("/products")).json()["pagination"]["totalItemsCount"] == 1


async def test_hooks_context_and_defaults(tour: Env) -> None:
    async with tour.client() as c:
        await seed(c)
        b = (await c.get("/companies?perPage=1", headers=ADMIN)).json()
        assert b["data"][0]["fetchedBy"] == "hook" and "servedAt" in b
        assert b["meta"]["api"] == "v1"  # CrudmanOptions.defaults layer
        assert (await c.get("/companies", headers={**ADMIN, "x-block": "1"})).status_code == 403
        meta = (await c.get("/companies/1", headers={**ADMIN, "x-tenant-id": "t-42"})).json()["meta"]
        assert meta["tenant"] == "t-42" and meta["mailer"] == "mailer-service"
        await c.post("/items", json={"label": "box", "qty": 1})
        assert (await c.get("/items/1")).json() == {"custom": True, "id": "1"}  # custom_implementation


async def test_access_control(tour: Env) -> None:
    async with tour.client() as c:
        assert (await c.get("/companies")).status_code == 403
        assert (await c.get("/companies", headers={"x-role": "user"})).status_code == 403
        u1, u2 = {"x-user-id": "1"}, {"x-user-id": "2"}
        assert (await c.post("/notes", json={"title": "mine", "owner_id": 999}, headers=u1)).status_code == 200
        await c.post("/notes", json={"title": "theirs"}, headers=u2)
        mine = (await c.get("/notes", headers=u1)).json()["data"]
        assert [n["title"] for n in mine] == ["mine"] and mine[0]["owner_id"] == 1
        assert (await c.get("/notes/2", headers=u1)).status_code == 404
        assert (await c.delete("/notes/2", headers=u1)).status_code == 404
        assert (await c.get("/notes")).status_code == 403


async def test_cache_hit_and_invalidation(tour: Env) -> None:
    async with tour.client() as c:
        await seed(c)
        url = "/companies?perPage=50&sort.name=asc"
        first = names(await c.get(url, headers=ADMIN))
        async with tour.engine.begin() as conn:  # change the row behind crudman's back
            await conn.execute(text("UPDATE tour_companies SET name='Sneaky' WHERE id=2"))
        assert names(await c.get(url, headers=ADMIN)) == first  # cache hit
        await c.patch("/companies/1", json={"email": "bust@acme.io"}, headers=ADMIN)  # write invalidates
        assert "Sneaky" in names(await c.get(url, headers=ADMIN))


async def test_save_and_bulk(tour: Env) -> None:
    async with tour.client() as c:
        await c.post("/products", json={"sku": "P1", "name": "Pen"})
        r = await c.post("/products/save", json={"sku": "P2", "name": "Pencil"})
        pid = r.json()["data"]["id"]
        r = await c.post("/products/save", json={"id": pid, "name": "Pencil HB"})
        assert r.json()["data"] == {"id": pid, "sku": "P2", "name": "Pencil HB", "price": 0.0}

        rows = [{"sku": "B1", "name": "Bag"}, {"id": 1, "name": "Pen X"}, {"name": "no sku"}]
        d = (await c.post("/products/bulk/import", json=rows)).json()["data"]
        assert (d["inserted"], d["updated"], d["errorsCount"]) == (1, 1, 1), d

        d = (await c.post("/products/bulk/import?dry_run=true", json=[{"sku": "DRY", "name": "Dry"}])).json()["data"]
        assert d["inserted"] == 1 and d["dryRun"] is True
        assert (await c.get("/products")).json()["pagination"]["totalItemsCount"] == 3

        r = await c.post("/products/bulk/import?policy=insert_only",
                         content="id,sku,name\n1,P1,Again\n,C1,Cup\n", headers={"content-type": "text/csv"})
        assert (r.json()["data"]["inserted"], r.json()["data"]["errorsCount"]) == (1, 1)
        r = await c.post("/products/bulk/import?policy=update_only", json=[{"id": 9999, "name": "ghost"}])
        assert r.json()["data"]["errorsCount"] == 1
        r = await c.post("/products/bulk/import?policy=ignore_on_conflict", json=[{"id": 1, "name": "ignored"}])
        assert r.json()["data"]["skipped"] == 1

        ids = [p["id"] for p in (await c.get("/products?paginate=false")).json()["data"]]
        r = await c.post("/products/bulk/delete", json={"ids": ids[:2] + [9999]})
        assert r.json()["data"] == {"deleted": 2, "notFound": [9999]}
        r = await c.post("/products/bulk/delete", content=f"id\n{ids[2]}\n", headers={"content-type": "text/csv"})
        assert r.json()["data"]["deleted"] == 1


async def test_export(tour: Env) -> None:
    from openpyxl import load_workbook

    async with tour.client() as c:
        await seed(c)
        await c.post("/tags", json={"name": "t1"})
        r = await c.get("/companies?perPage=2", headers={**ADMIN, "x-content-type": "csv"})
        assert r.headers["content-type"].startswith("text/csv")
        lines = r.text.strip().splitlines()
        assert lines[0].startswith("id,") and len(lines) == 3
        assert (r.headers["x-pagination-total"], r.headers["x-pagination-page"],
                r.headers["x-pagination-perpage"]) == ("5", "1", "2")
        assert (await c.get("/tags", headers={"accept": "text/csv"})).headers["content-type"].startswith("text/csv")
        assert (await c.get("/companies/1?format=csv", headers=ADMIN)).text.startswith("id,")
        r = await c.get("/companies", headers={**ADMIN, "x-content-type": "excel"})
        assert "spreadsheetml" in r.headers["content-type"]
        assert load_workbook(io.BytesIO(r.content)).active.max_row == 6


async def test_uploads(tour: Env) -> None:
    uploads = tour.tmp_path / "uploads"
    async with tour.client() as c:
        r = await c.post("/profiles", data={"name": "Ann"}, files={"avatar": ("me.png", png(), "image/png")})
        assert r.status_code == 200, r.text
        assert (uploads / r.json()["data"]["avatar"]).exists()

        data_url = "data:image/png;base64," + base64.b64encode(png()).decode()
        r = await c.post("/profiles", json={"name": "Bob", "avatar": data_url})
        assert r.status_code == 200 and (uploads / r.json()["data"]["avatar"]).exists()

        r = await c.post("/profiles", data={"name": "Tiny"}, files={"avatar": ("t.png", png(10, 10), "image/png")})
        assert r.status_code == 400 and r.json()["errors"][0]["type"] == "imageDimensions"
        r = await c.post("/profiles", data={"name": "Txt"}, files={"avatar": ("a.txt", b"hello", "text/plain")})
        assert r.status_code == 400
        r = await c.post("/profiles", json={"name": "NoPic"})
        assert r.status_code == 400 and r.json()["errors"][0]["type"] == "required"

        pdf = b"%PDF-1.4 test"
        files = [("avatar", ("a.png", png(), "image/png")),
                 ("photos", ("p1.png", png(), "image/png")), ("photos", ("p2.png", png(), "image/png")),
                 ("doc", ("d.pdf", pdf, "application/pdf")),
                 ("attachment", ("x.bin", b"\x00\x01\x02", "application/octet-stream"))]
        r = await c.post("/profiles", data={"name": "Multi"}, files=files)
        assert r.status_code == 200, r.text
        d = r.json()["data"]
        assert len(d["photos"]) == 2 and base64.b64decode(d["docBase64"]) == pdf
        assert d["attachmentMime"] == "application/octet-stream" and "attachmentBlob" not in d
        assert (await c.get("/profiles")).json()["meta"]["baseUrls"]["avatar"] == "http://localhost:8000/files/"


async def test_routing_variants(tour: Env) -> None:
    async with tour.client() as c:
        assert (await c.post("/tags", json={"name": "t1"})).status_code == 200
        assert (await c.post("/kinds", json={"name": "k1"})).status_code == 200
        assert (await c.post("/user-profiles", json={"nickname": "jj"})).status_code == 200  # kebab
        await c.post("/items", json={"label": "box"})
        assert (await c.get("/items")).json()["data"][0]["label"] == "box"  # CrudController
        assert (await c.put("/items-put/1", json={"label": "crate", "qty": 2})).status_code == 200
        assert (await c.patch("/items-put/1", json={"qty": 3})).status_code == 405
        b = (await c.get("/custom/tags")).json()  # @crud.list decorator
        assert b["success"] and b["data"][0]["name"] == "t1"
        await c.post("/countries", json={"name": "India"})
        r = await c.post("/custom/countries/1/states", json={"name": "Goa"})  # call_action
        assert r.status_code == 200, r.text
        assert r.json()["data"]["country"]["name"] == "India"


async def test_openapi(tour: Env) -> None:
    async with tour.client() as c:
        paths = (await c.get("/openapi.json")).json()["paths"]
    for p in ["/companies", "/companies/{id}", "/products/save", "/products/bulk/import",
              "/products/bulk/delete", "/user-profiles", "/organisations", "/kinds"]:
        assert p in paths, p
    assert {"application/json", "multipart/form-data"} <= set(paths["/companies"]["post"]["requestBody"]["content"])
    assert "multipart/form-data" in paths["/profiles"]["post"]["requestBody"]["content"]
    assert {"p", "pp", "q"} <= {x["name"] for x in paths["/organisations"]["get"]["parameters"]}


def test_config_typos_fail_at_startup() -> None:
    with pytest.raises(CrudmanConfigError):
        crud_router(TTag, "bad_tags", {"filters_whitelist": ["nope"]})
    with pytest.raises(CrudmanConfigError):
        crud_router(TTag, "bad_tags2", {"filtersWhitelst": ["name"]})
