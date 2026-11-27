"""Regression tests for the issues fixed in 0.1.1 (each one was exploitable in 0.1.0)."""

from __future__ import annotations

import base64
import io
from typing import Any

import pytest
from fastapi import Request
from openpyxl import load_workbook
from PIL import Image

from crudman import CacheOptions, LocalStorage, crud_router
from crudman.export import escape_formula
from crudman.uploads import UnsafeFileKey, safe_key, sniff_image

from .conftest import Env
from .models import Company, Contact, Country, Post, Profile, User


def png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), "red").save(buf, format="PNG")
    return buf.getvalue()


def storage(env: Env) -> dict[str, Any]:
    return {"default_file_storage": "local", "file_storages": {"local": LocalStorage(env.tmp_path / "uploads")}}


# ── 1. path traversal / arbitrary file deletion ───────────────────────────────


@pytest.mark.parametrize("key", ["../x", "a/../../x", "/etc/passwd", "a\\..\\x", "", ".", "a//b", "C:/x", "a\x00b"])
def test_safe_key_rejects_escapes(key: str) -> None:
    with pytest.raises(UnsafeFileKey):
        safe_key(key)


def test_safe_key_accepts_normal_keys() -> None:
    assert safe_key("abc.png") == "abc.png"
    assert safe_key("users/1/avatar.jpg") == "users/1/avatar.jpg"


async def test_local_storage_never_leaves_its_folder(env: Env) -> None:
    victim = env.tmp_path / "victim.txt"
    victim.write_text("keep me")
    store = LocalStorage(env.tmp_path / "uploads")
    await store.delete("../victim.txt")
    assert victim.exists()
    with pytest.raises(UnsafeFileKey):
        await store.save(b"x", filename=None, mime=None, key="../evil.txt")
    assert not (env.tmp_path / "evil.txt").exists()


async def test_client_cannot_set_file_keys(env: Env) -> None:
    victim = env.tmp_path / "victim.txt"
    victim.write_text("keep me")
    env.app_with(crud_router(Profile, config={"uploadable": {"avatar": "image"},
                                              "upload_defaults": {"delete_on_replace": True}}), **storage(env))
    async with env.client() as c:
        created = (await c.post("/profiles", files={"avatar": ("a.png", png(), "image/png")},
                                data={"name": "A"})).json()["data"]
        r = await c.patch(f"/profiles/{created['id']}", json={"avatar": "../victim.txt"})
        assert r.status_code == 400 and r.json()["errors"][0]["type"] == "fileKey"
        # sending back the current value, or null, is fine
        assert (await c.patch(f"/profiles/{created['id']}", json={"avatar": created["avatar"]})).status_code == 200
        await c.patch(f"/profiles/{created['id']}", files={"avatar": ("b.png", png(), "image/png")})
    assert victim.exists()


async def test_key_url_columns_cannot_be_set_directly(env: Env) -> None:
    env.app_with(crud_router(Profile, config={"uploadable": {"avatar": "image"}}),
                 upload_response={"file_field_mode": "key_url_fields"}, **storage(env))
    async with env.client() as c:
        r = await c.post("/profiles", json={"name": "A", "avatar": "data:image/png;base64,"
                                            + base64.b64encode(png()).decode(), "avatarKey": "../../etc/passwd"})
        assert r.status_code == 200
        assert r.json()["data"]["avatarKey"] != "../../etc/passwd"


async def test_key_pattern_cannot_escape(env: Env) -> None:
    from crudman import UploadMap

    bad = UploadMap(source_field="avatar", type_hint="image", key_pattern=lambda **kw: f"../{kw['original_name']}")
    env.app_with(crud_router(Profile, config={"upload": {"map": [bad]}}), **storage(env))
    async with env.client() as c:
        r = await c.post("/profiles", files={"avatar": ("a.png", png(), "image/png")}, data={"name": "A"})
    assert r.status_code == 400 and r.json()["errors"][0]["type"] == "fileKey"


# ── 2. hidden columns as a search oracle ──────────────────────────────────────


async def test_hidden_columns_cannot_be_filtered_sorted_or_searched(env: Env) -> None:
    await env.add(Company(name="Acme", secret="s3cretVALUE"), Company(name="Beta", secret="zzz"))
    env.app_with(crud_router(Company, config={"relations": [], "attributes": {"read": {"exclude": ["secret"]}}}))
    async with env.client() as c:
        assert len((await c.get("/companies?secret.like=s3cret")).json()["data"]) == 2  # filter ignored
        assert len((await c.get("/companies?secret=zzz")).json()["data"]) == 2
        assert len((await c.get("/companies?keyword=s3cretVALUE")).json()["data"]) == 0
        body = (await c.get("/companies?sort.secret=asc")).json()
        assert body["sorting"][0]["field"] != "secret"


async def test_explicit_whitelist_can_still_include_hidden_columns(env: Env) -> None:
    await env.add(Company(name="Acme", secret="s1"), Company(name="Beta", secret="s2"))
    env.app_with(crud_router(Company, config={"relations": [], "attributes": {"read": {"exclude": ["secret"]}},
                                              "list": {"filters_whitelist": ["name", "secret"]}}))
    async with env.client() as c:
        assert len((await c.get("/companies?secret=s1")).json()["data"]) == 1


# ── 3. related records expose hidden fields ───────────────────────────────────


async def test_related_records_follow_their_sections_attributes(env: Env) -> None:
    await env.add(Company(name="Acme", secret="s3cret", contacts=[Contact(email="a@acme.test")]))
    env.app_with(crud_router(Company, config={"attributes": {"read": {"exclude": ["secret"]}}}),
                 crud_router(Contact))
    async with env.client() as c:
        contact = (await c.get("/contacts/1")).json()["data"]
    assert contact["company"]["name"] == "Acme"
    assert "secret" not in contact["company"]


async def test_related_records_use_global_defaults(env: Env) -> None:
    await env.add(Company(name="Acme", secret="s3cret", contacts=[Contact(email="a@acme.test")]))
    env.app_with(crud_router(Contact), defaults={"attributes": {"read": {"exclude": ["secret"]}}})
    async with env.client() as c:
        assert "secret" not in (await c.get("/contacts/1")).json()["data"]["company"]


# ── 4. cache leaking between callers ──────────────────────────────────────────


async def test_cache_is_per_identity(env: Env) -> None:
    await env.add(Post(slug="a", title="tenant one", tenant_id=1), Post(slug="b", title="tenant two", tenant_id=2))

    def identity(request: Request) -> dict[str, Any]:
        return {"tenant": int(request.headers.get("x-tenant", 0))}

    env.app_with(crud_router(Post, config={"conditions": lambda ctx: [Post.tenant_id == ctx.identity["tenant"]],
                                           "list": {"enable_cache": True}}),
                 cache=CacheOptions(enabled=True), identity_accessor=identity)
    async with env.client() as c:
        one = (await c.get("/posts", headers={"x-tenant": "1"})).json()["data"]
        two = (await c.get("/posts", headers={"x-tenant": "2"})).json()["data"]
    assert [p["title"] for p in one] == ["tenant one"]
    assert [p["title"] for p in two] == ["tenant two"]


# ── 6. spreadsheet formula injection ──────────────────────────────────────────


@pytest.mark.parametrize("value", ["=1+1", "+1", "-1", "@SUM(A1)", "\tx", "\rx"])
def test_escape_formula(value: str) -> None:
    assert escape_formula(value) == "'" + value
    assert escape_formula("plain") == "plain" and escape_formula(-1) == -1


async def test_exports_do_not_contain_live_formulas(env: Env) -> None:
    await env.add(User(name='=HYPERLINK("http://evil.test","x")', email="e@x.io"))
    env.app_with(crud_router(User))
    async with env.client() as c:
        csv_text = (await c.get("/users?format=csv")).text
        xlsx = (await c.get("/users", headers={"x-content-type": "excel"})).content
    assert "'=HYPERLINK" in csv_text
    cell = load_workbook(io.BytesIO(xlsx)).active["B2"]
    assert cell.data_type == "s" and cell.value.startswith("=HYPERLINK")  # stored as text, not a formula


# ── 8 / 9. size limits ────────────────────────────────────────────────────────


async def test_page_size_is_capped_and_full_dumps_are_off(env: Env) -> None:
    await env.add(*[Country(name=f"C{i}") for i in range(120)])
    env.app_with(crud_router(Country, config={"relations": []}))
    async with env.client() as c:
        assert len((await c.get("/countries?perPage=1000000")).json()["data"]) == 100
        assert len((await c.get("/countries?paginate=false")).json()["data"]) == 30


async def test_body_and_file_limits(env: Env) -> None:
    env.app_with(crud_router(Profile, config={"uploadable": {"avatar": "any"}}), max_body_mb=0.01, max_file_mb=0.01,
                 **storage(env))
    async with env.client() as c:
        r = await c.post("/profiles", json={"name": "x" * 20_000})
        assert r.status_code == 413
        r = await c.post("/profiles", data={"name": "A"}, files={"avatar": ("a.bin", b"0" * 20_000, "x/y")})
        assert r.status_code == 413


async def test_bulk_row_limit(env: Env) -> None:
    env.app_with(crud_router(Country, actions=["*", "bulk_import", "bulk_delete"]), max_bulk_rows=2)
    async with env.client() as c:
        assert (await c.post("/countries/bulk/import", json=[{"name": "a"}, {"name": "b"}, {"name": "c"}])
                ).status_code == 413
        assert (await c.post("/countries/bulk/delete", json={"ids": [1, 2, 3]})).status_code == 413


# ── 10. upload content and dangerous extensions ───────────────────────────────


def test_sniff_image() -> None:
    assert sniff_image(png()) == "image/png"
    assert sniff_image(b"<script>") is None


async def test_fake_image_is_rejected(env: Env) -> None:
    env.app_with(crud_router(Profile, config={"uploadable": {"avatar": "image"}}), **storage(env))
    async with env.client() as c:
        r = await c.post("/profiles", data={"name": "A"},
                         files={"avatar": ("x.png", b"<script>alert(1)</script>", "image/png")})
    assert r.status_code == 400 and r.json()["errors"][0]["type"] == "fileContent"


@pytest.mark.parametrize(("filename", "mime"), [("x.html", "text/html"), ("x.svg", "image/svg+xml"),
                                                 ("x.php", "application/octet-stream")])
async def test_dangerous_extensions_are_rejected(env: Env, filename: str, mime: str) -> None:
    env.app_with(crud_router(Profile, config={"uploadable": {"avatar": "any"}}), **storage(env))
    async with env.client() as c:
        r = await c.post("/profiles", data={"name": "A"}, files={"avatar": (filename, b"<b>x</b>", mime)})
        assert r.status_code == 400 and r.json()["errors"][0]["type"] == "fileExtension"
        data_url = "data:text/html;base64," + base64.b64encode(b"<b>x</b>").decode()
        r = await c.post("/profiles", json={"name": "A", "avatar": data_url})
        assert r.status_code == 400
