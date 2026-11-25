"""File uploads: presets, shorthand expansion, validation and storage.

Ported from crudman-nestjs ``processUploads``. Files arrive as multipart parts or as base64 strings in
the JSON body; each upload rule validates them and writes the result into the body before validation.
"""

from __future__ import annotations

import base64
import binascii
import io
import mimetypes
import os
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .context import UploadedFile
from .options import ActionConfig, UploadConfig, UploadMap, UploadResponseOptions

_IMAGES = ["image/jpeg", "image/png", "image/gif", "image/webp", "image/avif"]
_IMAGE_EXT = [".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif"]

PRESETS: dict[str, dict[str, Any]] = {
    "image": {"allowed_mime_types": _IMAGES, "allowed_extensions": _IMAGE_EXT, "max_size_mb": 5},
    "image-jpg": {"allowed_mime_types": ["image/jpeg"], "allowed_extensions": [".jpg", ".jpeg"], "max_size_mb": 5},
    "image-png": {"allowed_mime_types": ["image/png"], "allowed_extensions": [".png"], "max_size_mb": 5},
    "image-gif": {"allowed_mime_types": ["image/gif"], "allowed_extensions": [".gif"], "max_size_mb": 5},
    "image-webp": {"allowed_mime_types": ["image/webp"], "allowed_extensions": [".webp"], "max_size_mb": 5},
    "image-avif": {"allowed_mime_types": ["image/avif"], "allowed_extensions": [".avif"], "max_size_mb": 5},
    "image-avatar": {"allowed_mime_types": _IMAGES, "allowed_extensions": _IMAGE_EXT, "max_size_mb": 2, "avatar": True},
    "image-jpg-avatar": {"allowed_mime_types": ["image/jpeg"], "allowed_extensions": [".jpg", ".jpeg"],
                         "max_size_mb": 2, "avatar": True},
    "image-png-avatar": {"allowed_mime_types": ["image/png"], "allowed_extensions": [".png"], "max_size_mb": 2,
                         "avatar": True},
    "image-webp-avatar": {"allowed_mime_types": ["image/webp"], "allowed_extensions": [".webp"], "max_size_mb": 2,
                          "avatar": True},
    "image-avif-avatar": {"allowed_mime_types": ["image/avif"], "allowed_extensions": [".avif"], "max_size_mb": 2,
                          "avatar": True},
    "video": {"allowed_mime_types": ["video/mp4", "video/webm", "video/ogg"],
              "allowed_extensions": [".mp4", ".webm", ".ogg"], "max_size_mb": 100},
    "video-mp4": {"allowed_mime_types": ["video/mp4"], "allowed_extensions": [".mp4"], "max_size_mb": 100},
    "video-webm": {"allowed_mime_types": ["video/webm"], "allowed_extensions": [".webm"], "max_size_mb": 100},
    "video-ogg": {"allowed_mime_types": ["video/ogg"], "allowed_extensions": [".ogg"], "max_size_mb": 100},
    "video-short": {"allowed_mime_types": ["video/mp4", "video/webm"], "allowed_extensions": [".mp4", ".webm"],
                    "max_size_mb": 25},
    "audio": {"allowed_mime_types": ["audio/mpeg", "audio/mp4", "audio/aac", "audio/ogg", "audio/wav"],
              "allowed_extensions": [".mp3", ".m4a", ".aac", ".ogg", ".wav"], "max_size_mb": 20},
    "pdf": {"allowed_extensions": [".pdf"], "max_size_mb": 10},
    "doc": {"allowed_extensions": [".pdf", ".doc", ".docx", ".odt"], "max_size_mb": 10},
    "spreadsheet": {"allowed_extensions": [".xls", ".xlsx", ".csv"], "max_size_mb": 10},
    "spreadsheet-csv": {"allowed_mime_types": ["text/csv"], "allowed_extensions": [".csv"], "max_size_mb": 5},
    "spreadsheet-xls": {"allowed_mime_types": ["application/vnd.ms-excel"], "allowed_extensions": [".xls"],
                        "max_size_mb": 10},
    "spreadsheet-xlsx": {
        "allowed_mime_types": ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
        "allowed_extensions": [".xlsx"], "max_size_mb": 10,
    },
    "text": {"allowed_mime_types": ["text/plain", "text/markdown"], "allowed_extensions": [".txt", ".md"],
             "max_size_mb": 2},
    "csv": {"allowed_mime_types": ["text/csv"], "allowed_extensions": [".csv"], "max_size_mb": 5},
    "xml": {"allowed_mime_types": ["application/xml", "text/xml"], "allowed_extensions": [".xml"], "max_size_mb": 2},
    "html": {"allowed_mime_types": ["text/html"], "allowed_extensions": [".html", ".htm"], "max_size_mb": 2},
    "json": {"allowed_mime_types": ["application/json"], "allowed_extensions": [".json"], "max_size_mb": 2},
    "archive": {"allowed_extensions": [".zip", ".tar", ".gz", ".rar", ".7z"], "max_size_mb": 200},
    "binary": {"allowed_mime_types": ["application/octet-stream"], "max_size_mb": 50},
    "any": {},
}

# Accept NestJS camelCase validator keys too.
_VALIDATOR_ALIASES = {"maxSizeMB": "max_size_mb", "allowedMimeTypes": "allowed_mime_types",
                      "allowedExtensions": "allowed_extensions"}


def _norm_validators(v: Mapping[str, Any] | None) -> dict[str, Any]:
    return {_VALIDATOR_ALIASES.get(k, k): val for k, val in (v or {}).items()}


# ── storage ───────────────────────────────────────────────────────────────────


@dataclass
class SavedFile:
    key: str
    url: str | None
    mime: str | None
    size: int


class FileStorage(Protocol):
    public_base_url: str | None

    async def save(
        self, data: bytes, *, filename: str | None, mime: str | None, key: str | None = None
    ) -> SavedFile: ...
    async def delete(self, key: str) -> None: ...
    def url_for(self, key: str) -> str | None: ...


def _join(base: str, key: str) -> str:
    return base.rstrip("/") + "/" + key.lstrip("/")


def _ext(filename: str | None, mime: str | None) -> str:
    if filename and os.path.splitext(filename)[1]:
        return os.path.splitext(filename)[1].lower()
    if mime:
        guess = mimetypes.guess_extension(mime) or ""
        return ".jpg" if guess == ".jpe" else guess
    return ""


class LocalStorage:
    """Stores files on disk under ``dest`` with random names."""

    def __init__(self, dest: str | os.PathLike[str] = "uploads", public_base_url: str | None = None) -> None:
        self.dest = Path(dest)
        self.public_base_url = public_base_url

    async def save(self, data: bytes, *, filename: str | None, mime: str | None, key: str | None = None) -> SavedFile:
        key = key or f"{uuid.uuid4().hex}{_ext(filename, mime)}"
        path = self.dest / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return SavedFile(key=key, url=self.url_for(key), mime=mime, size=len(data))

    async def delete(self, key: str) -> None:
        try:
            (self.dest / key).unlink()
        except FileNotFoundError:
            pass

    def url_for(self, key: str) -> str | None:
        return _join(self.public_base_url, key) if self.public_base_url else None


class S3Storage:
    """Stores files in S3 (``pip install "crudman-fastapi[s3]"``)."""

    def __init__(self, bucket: str, *, prefix: str = "", public_base_url: str | None = None,
                 client_kwargs: dict[str, Any] | None = None) -> None:
        self.bucket = bucket
        self.prefix = prefix
        self.public_base_url = public_base_url
        self.client_kwargs = client_kwargs or {}

    def _session(self) -> Any:
        try:
            import aioboto3
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ImportError('S3Storage needs the s3 extra: pip install "crudman-fastapi[s3]"') from exc
        return aioboto3.Session()

    async def save(self, data: bytes, *, filename: str | None, mime: str | None,
                   key: str | None = None) -> SavedFile:  # pragma: no cover - needs S3
        key = self.prefix + (key or f"{uuid.uuid4().hex}{_ext(filename, mime)}")
        async with self._session().client("s3", **self.client_kwargs) as client:
            await client.put_object(Bucket=self.bucket, Key=key, Body=data,
                                    ContentType=mime or "application/octet-stream")
        return SavedFile(key=key, url=self.url_for(key), mime=mime, size=len(data))

    async def delete(self, key: str) -> None:  # pragma: no cover - needs S3
        async with self._session().client("s3", **self.client_kwargs) as client:
            await client.delete_object(Bucket=self.bucket, Key=key)

    def url_for(self, key: str) -> str | None:
        return _join(self.public_base_url, key) if self.public_base_url else None


# ── rules ─────────────────────────────────────────────────────────────────────


def expand_upload_config(cfg: ActionConfig, response: UploadResponseOptions,
                         default_storage: str | None) -> list[UploadMap]:
    """``uploadable={"avatar": "image"}`` shorthand plus any explicit ``upload.map`` rules."""
    rules: list[UploadMap] = []
    defaults = dict(cfg.upload_defaults or {})
    for field, raw_spec in (cfg.uploadable or {}).items():
        spec = str(raw_spec).strip()
        is_array = "[]" in spec
        if ":base64" in spec:
            mode = "base64"
        elif ":blob" in spec:
            mode = "blob"
        else:
            mode = "filename"
        hint = spec.split(":")[0].replace("[]", "")
        target: str | dict[str, str]
        if mode == "filename":
            if response.file_field_mode == "filename_in_field":
                mode, target = "filename_in_field", field
            elif is_array:
                target = {"keys": f"{field}Keys", "urls": f"{field}Urls"}
            else:
                target = {"key": f"{field}Key", "url": f"{field}Url"}
        elif mode == "blob":
            target = {"blob": f"{field}Blob", "mime": f"{field}Mime"}
        else:
            target = f"{field}Base64"
        rules.append(UploadMap(
            source_field=field, target_field=target, storage_mode=mode,  # type: ignore[arg-type]
            storage=defaults.get("storage") or default_storage, is_array=is_array, type_hint=hint,
            validators=_norm_validators(defaults.get("validators")),
            delete_on_replace=bool(defaults.get("delete_on_replace", False)),
        ))
    upload: UploadConfig | None = cfg.upload
    if upload is not None:
        for rule in upload.map:
            if rule.target_field is None:
                rule = rule.model_copy(update={"target_field": rule.source_field})
            if rule.storage is None and rule.storage_mode in ("filename", "filename_in_field"):
                rule = rule.model_copy(update={"storage": defaults.get("storage") or default_storage})
            rules.append(rule)
    return rules


@dataclass
class _Item:
    data: bytes
    filename: str | None
    mime: str | None


_DATA_URL = re.compile(r"^data:(?P<mime>[\w.+-]+/[\w.+-]+)?(;[^,]*)?;base64,(?P<data>.*)$", re.S)


def _decode_base64(value: str) -> _Item | None:
    text = value.strip()
    mime = None
    match = _DATA_URL.match(text)
    if match:
        mime = match.group("mime")
        text = match.group("data")
    try:
        data = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        return None
    return _Item(data=data, filename=None, mime=mime)


def _avatar_errors(field: str, data: bytes) -> list[dict[str, Any]]:
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - optional dependency
        return []
    try:
        with Image.open(io.BytesIO(data)) as img:
            w, h = img.size
    except Exception:
        return [{"type": "imageDimensions", "field": field, "message": "Could not read image dimensions"}]
    errors = []
    if w < 128 or h < 128:
        errors.append({"type": "imageDimensions", "field": field, "message": "Image too small. Min 128x128"})
    if w > 4096 or h > 4096:
        errors.append({"type": "imageDimensions", "field": field, "message": "Image too large. Max 4096x4096"})
    if abs(w / h - 1) > 0.2:
        errors.append({"type": "imageAspect", "field": field, "message": "Image should be near 1:1 aspect (±20%)"})
    return errors


def _check(field: str, item: _Item, rules: Mapping[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    max_mb = rules.get("max_size_mb")
    if max_mb and len(item.data) > max_mb * 1024 * 1024:
        errors.append({"type": "fileSize", "field": field, "message": f"File too large. Max {max_mb} MB"})
    exts = [e.lower() for e in rules.get("allowed_extensions") or []]
    if exts:
        ext = _ext(item.filename, item.mime)
        if ext == ".jpe":
            ext = ".jpg"
        if ext not in exts:
            errors.append({"type": "fileExtension", "field": field,
                           "message": f"Invalid extension. Allowed: {', '.join(exts)}"})
    mimes = [m.lower() for m in rules.get("allowed_mime_types") or []]
    if mimes and (item.mime or "").lower() not in mimes:
        errors.append({"type": "fileMime", "field": field,
                       "message": f"Invalid MIME type. Allowed: {', '.join(mimes)}"})
    if rules.get("avatar") and not errors:
        errors.extend(_avatar_errors(field, item.data))
    return errors


@dataclass
class UploadOutcome:
    errors: list[dict[str, Any]]
    replaced_keys: list[tuple[str, str]]  # (storage name, old key) to delete after a successful update


async def process_uploads(
    rules: list[UploadMap],
    *,
    body: dict[str, Any],
    files: Mapping[str, list[UploadedFile]],
    storages: Mapping[str, Any],
    global_limits: Mapping[str, Any],
    is_create: bool,
    existing: Mapping[str, Any] | None,
    section: str,
) -> UploadOutcome:
    """Validate and store uploads, writing results into ``body``."""
    errors: list[dict[str, Any]] = []
    replaced: list[tuple[str, str]] = []
    for rule in rules:
        field = rule.source_field
        items: list[_Item] = []
        if "multipart" in rule.sources:
            items = [_Item(f.data, f.filename, f.content_type) for f in files.get(field, [])]
        raw = body.get(field)
        if not items and "base64" in rule.sources and isinstance(raw, (str, list)):
            values = raw if isinstance(raw, list) else [raw]
            for value in values:
                if not isinstance(value, str):
                    continue
                # A plain string (e.g. an existing filename sent back on update) is not an upload
                # unless it is a data URL or the rule stores base64/blob.
                if not value.startswith("data:") and rule.storage_mode not in ("base64", "blob"):
                    continue
                decoded = _decode_base64(value)
                if decoded is None:
                    errors.append({"type": "fileBase64", "field": field, "message": "Invalid base64 data"})
                else:
                    items.append(decoded)
        if not items:
            if (is_create and not rule.is_array and rule.storage_mode in ("filename", "filename_in_field")
                    and raw in (None, "")):
                errors.append({"type": "required", "field": field, "message": f"The {field} field is required."})
            continue
        effective = {**PRESETS.get(rule.type_hint or "", {}), **_norm_validators(global_limits),
                     **_norm_validators(rule.validators)}
        item_errors = [e for it in items for e in _check(field, it, effective)]
        if item_errors:
            errors.extend(item_errors)
            continue
        if not rule.is_array:
            items = items[:1]
        body.pop(field, None)  # the raw upload is replaced by the stored result below

        if rule.storage_mode in ("filename", "filename_in_field"):
            storage = storages.get(rule.storage or "")
            if storage is None:
                raise RuntimeError(
                    f"Upload field '{field}' needs a file storage; configure CrudmanOptions.file_storages "
                    "and default_file_storage (or upload_defaults={'storage': ...})."
                )
            saved = []
            for it in items:
                key = None
                if rule.key_pattern is not None:
                    key = rule.key_pattern(section=section, field=field, original_name=it.filename,
                                           ext=_ext(it.filename, it.mime), uuid=uuid.uuid4().hex)
                saved.append(await storage.save(it.data, filename=it.filename, mime=it.mime, key=key))
            target = rule.target_field
            if rule.storage_mode == "filename_in_field" or isinstance(target, str):
                tf = target if isinstance(target, str) else field
                keys = [s.key for s in saved]
                if rule.is_array:
                    old = list((existing or {}).get(tf) or []) if rule.mode == "append" else []
                    body[tf] = old + keys
                else:
                    if existing and existing.get(tf) and rule.delete_on_replace:
                        replaced.append((rule.storage or "", str(existing[tf])))
                    body[tf] = keys[0]
            else:
                assert isinstance(target, Mapping)
                if rule.is_array:
                    if target.get("keys"):
                        body[target["keys"]] = [s.key for s in saved]
                    if target.get("urls"):
                        body[target["urls"]] = [s.url for s in saved if s.url]
                else:
                    if target.get("key"):
                        if existing and existing.get(target["key"]) and rule.delete_on_replace:
                            replaced.append((rule.storage or "", str(existing[target["key"]])))
                        body[target["key"]] = saved[0].key
                    if target.get("url") and saved[0].url:
                        body[target["url"]] = saved[0].url
        elif rule.storage_mode == "base64":
            tf = rule.target_field if isinstance(rule.target_field, str) else field
            encoded = [base64.b64encode(it.data).decode("ascii") for it in items]
            body[tf] = encoded if rule.is_array else encoded[0]
        elif rule.storage_mode == "blob":
            target = rule.target_field if isinstance(rule.target_field, Mapping) else {"blob": field}
            body[target["blob"]] = items[0].data
            if target.get("mime"):
                body[target["mime"]] = items[0].mime or "application/octet-stream"
    return UploadOutcome(errors=errors, replaced_keys=replaced)


def base_urls(rules: list[UploadMap], storages: Mapping[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for rule in rules:
        if rule.storage_mode not in ("filename", "filename_in_field"):
            continue
        storage = storages.get(rule.storage or "")
        base = getattr(storage, "public_base_url", None)
        if base:
            out[rule.source_field] = base if base.endswith("/") else base + "/"
    return out


def file_fields(rules: list[UploadMap]) -> list[str]:
    return [r.source_field for r in rules]


__all__ = [
    "PRESETS",
    "FileStorage",
    "LocalStorage",
    "S3Storage",
    "SavedFile",
    "UploadOutcome",
    "base_urls",
    "expand_upload_config",
    "file_fields",
    "process_uploads",
]
