"""File uploads: multipart and base64, storage modes, presets and errors."""

from __future__ import annotations

import base64
import io
from pathlib import Path

from PIL import Image

from crudman import LocalStorage, UploadMap, crud_router

from .conftest import Env
from .models import Profile


def png(width: int = 200, height: int = 200) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "purple").save(buf, format="PNG")
    return buf.getvalue()


def data_url(data: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64," + base64.b64encode(data).decode()


def storage_opts(env: Env) -> dict[str, object]:
    return {"default_file_storage": "local",
            "file_storages": {"local": LocalStorage(env.tmp_path / "uploads", "http://cdn.test/uploads")}}


async def test_multipart_upload_filename_in_field(env: Env) -> None:
    env.app_with(crud_router(Profile, config={"uploadable": {"avatar": "image"}}), **storage_opts(env))
    async with env.client() as c:
        r = await c.post("/profiles", data={"name": "Ann"}, files={"avatar": ("me.png", png(), "image/png")})
        assert r.status_code == 200, r.json()
        key = r.json()["data"]["avatar"]
        assert key.endswith(".png")
        assert (env.tmp_path / "uploads" / key).read_bytes() == png()
        body = (await c.get("/profiles")).json()
        assert body["meta"]["baseUrls"] == {"avatar": "http://cdn.test/uploads/"}


async def test_base64_upload(env: Env) -> None:
    env.app_with(crud_router(Profile, config={"uploadable": {"avatar": "image"}}), **storage_opts(env))
    async with env.client() as c:
        r = await c.post("/profiles", json={"name": "Ann", "avatar": data_url(png())})
        assert r.status_code == 200, r.json()
        assert Path(env.tmp_path / "uploads" / r.json()["data"]["avatar"]).exists()


async def test_required_on_create_and_kept_on_update(env: Env) -> None:
    env.app_with(crud_router(Profile, config={"uploadable": {"avatar": "image"}}), **storage_opts(env))
    async with env.client() as c:
        r = await c.post("/profiles", json={"name": "Ann"})
        assert r.status_code == 400 and r.json()["errors"][0] == {
            "type": "required", "field": "avatar", "message": "The avatar field is required."}
        pid = (await c.post("/profiles", json={"name": "Ann", "avatar": data_url(png())})).json()["data"]["id"]
        r = await c.patch(f"/profiles/{pid}", json={"name": "Anna"})
        assert r.status_code == 200 and r.json()["data"]["avatar"]


async def test_validation_errors(env: Env) -> None:
    env.app_with(crud_router(Profile, config={"uploadable": {"avatar": "image-jpg"},
                                              "upload_defaults": {"validators": {"maxSizeMB": 0.0001}}}),
                 **storage_opts(env))
    async with env.client() as c:
        r = await c.post("/profiles", data={"name": "A"}, files={"avatar": ("me.png", png(), "image/png")})
    types = {e["type"] for e in r.json()["errors"]}
    assert types == {"fileSize", "fileExtension", "fileMime"}
    assert not (env.tmp_path / "uploads").exists()  # nothing stored


async def test_avatar_dimensions(env: Env) -> None:
    env.app_with(crud_router(Profile, config={"uploadable": {"avatar": "image-avatar"}}), **storage_opts(env))
    async with env.client() as c:
        r = await c.post("/profiles", data={"name": "A"}, files={"avatar": ("a.png", png(64, 300), "image/png")})
        assert {e["type"] for e in r.json()["errors"]} == {"imageDimensions", "imageAspect"}
        r = await c.post("/profiles", data={"name": "A"}, files={"avatar": ("a.png", png(256, 256), "image/png")})
        assert r.status_code == 200


async def test_key_url_mode_and_replace(env: Env) -> None:
    env.app_with(
        crud_router(Profile, config={"uploadable": {"avatar": "image"},
                                     "upload_defaults": {"delete_on_replace": True}}),
        upload_response={"file_field_mode": "key_url_fields"}, **storage_opts(env),
    )
    async with env.client() as c:
        first = (await c.post("/profiles", json={"name": "A", "avatar": data_url(png())})).json()["data"]
        assert first["avatarUrl"] == f"http://cdn.test/uploads/{first['avatarKey']}"
        assert first["avatar"] is None
        second = (await c.patch(f"/profiles/{first['id']}", json={"avatar": data_url(png(300, 300))})).json()["data"]
    assert second["avatarKey"] != first["avatarKey"]
    assert not (env.tmp_path / "uploads" / first["avatarKey"]).exists()  # old file deleted
    assert (env.tmp_path / "uploads" / second["avatarKey"]).exists()


async def test_base64_blob_and_array_modes(env: Env) -> None:
    env.app_with(crud_router(Profile, config={
        "uploadable": {"thumb": "image:base64", "raw": "binary:blob"},
        "upload": {"map": [UploadMap(source_field="photos", target_field="photos", is_array=True,
                                     type_hint="image", mode="append")]},
    }), **storage_opts(env))
    async with env.client() as c:
        r = await c.post("/profiles", data={"name": "A"}, files=[
            ("thumb", ("t.png", png(), "image/png")),
            ("raw", ("r.bin", b"\x00\x01", "application/octet-stream")),
            ("photos", ("1.png", png(), "image/png")),
            ("photos", ("2.png", png(), "image/png")),
        ])
        assert r.status_code == 200, r.json()
        data = r.json()["data"]
        assert base64.b64decode(data["thumbBase64"]) == png()
        assert base64.b64decode(data["rawBlob"]) == b"\x00\x01" and data["rawMime"] == "application/octet-stream"
        assert len(data["photos"]) == 2
        r = await c.patch(f"/profiles/{data['id']}", files={"photos": ("3.png", png(), "image/png")},
                          data={"name": "A"})
        assert len(r.json()["data"]["photos"]) == 3  # append mode


async def test_missing_storage_is_a_clear_error(env: Env) -> None:
    import pytest

    env.app_with(crud_router(Profile, config={"uploadable": {"avatar": "image"}}))
    async with env.client() as c:
        with pytest.raises(RuntimeError, match="file storage"):
            await c.post("/profiles", json={"name": "A", "avatar": data_url(png())})
