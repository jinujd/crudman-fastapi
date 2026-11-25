"""Per-request objects: the request crudman works on, the hook context, and the result."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fastapi.encoders import jsonable_encoder
from starlette.responses import JSONResponse, Response

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from .service import CrudmanService


async def maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def call_hook(fn: Callable[..., Any] | None, *args: Any) -> Any:
    if fn is None:
        return None
    return await maybe_await(fn(*args))


@dataclass
class UploadedFile:
    """A file from a multipart request, read into memory."""

    filename: str | None
    content_type: str | None
    data: bytes

    @property
    def size(self) -> int:
        return len(self.data)


@dataclass
class CrudRequest:
    """What an action works on. Built from a FastAPI request or by ``call_action``."""

    params: dict[str, Any] = field(default_factory=dict)
    query: dict[str, Any] = field(default_factory=dict)
    body: dict[str, Any] = field(default_factory=dict)
    files: dict[str, list[UploadedFile]] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    raw_body: bytes | None = None
    payload: Any = None  # parsed JSON body as sent (may be a list, e.g. for bulk import)
    content_type: str = ""
    request: Any = None
    identity: dict[str, Any] | None = None
    nested: bool = False


class Repository:
    """Small helper bound to a model and the request's session (``ctx.repository``)."""

    def __init__(self, session: AsyncSession, model: Any) -> None:
        self.session = session
        self.model = model

    async def get(self, ident: Any) -> Any | None:
        return await self.session.get(self.model, ident)

    async def find(self, **filters: Any) -> list[Any]:
        from sqlalchemy import select

        stmt = select(self.model).filter_by(**filters)
        return list((await self.session.execute(stmt)).scalars().all())

    async def find_one(self, **filters: Any) -> Any | None:
        from sqlalchemy import select

        stmt = select(self.model).filter_by(**filters).limit(1)
        return (await self.session.execute(stmt)).scalars().first()

    async def exists(self, **filters: Any) -> bool:
        return await self.find_one(**filters) is not None

    async def add(self, obj: Any = None, **values: Any) -> Any:
        instance = obj if obj is not None else self.model(**values)
        self.session.add(instance)
        await self.session.flush()
        return instance

    async def delete(self, obj: Any) -> None:
        await self.session.delete(obj)
        await self.session.flush()


_RESERVED = {
    "service", "session", "repository", "section", "action", "model", "request", "identity",
    "params", "query", "body", "files", "crud_request",
}


class HookContext:
    """Passed to every hook as ``ctx``. Reserved keys cannot be overwritten by context builders."""

    def __init__(
        self,
        *,
        service: CrudmanService,
        session: AsyncSession,
        section: str,
        action: str,
        model: Any,
        crud_request: CrudRequest,
    ) -> None:
        self.service = service
        self.session = session
        self.section = section
        self.action = action
        self.model = model
        self.crud_request = crud_request
        self.repository = Repository(session, model)
        self.services: dict[str, Any] = {}
        self.repositories: dict[str, Any] = {}
        self.extra: dict[str, Any] = {}

    # request parts
    @property
    def request(self) -> Any:
        return self.crud_request.request

    @property
    def identity(self) -> dict[str, Any]:
        return self.crud_request.identity or {}

    @property
    def params(self) -> dict[str, Any]:
        return self.crud_request.params

    @property
    def query(self) -> dict[str, Any]:
        return self.crud_request.query

    @property
    def body(self) -> dict[str, Any]:
        return self.crud_request.body

    @body.setter
    def body(self, value: dict[str, Any]) -> None:
        self.crud_request.body = value

    @property
    def files(self) -> dict[str, list[UploadedFile]]:
        return self.crud_request.files

    def merge(self, extra: Mapping[str, Any] | None) -> None:
        """Merge user context; ``services``/``repositories`` are merged, reserved keys are skipped."""
        if not extra:
            return
        for key, value in extra.items():
            if key == "services" and isinstance(value, Mapping):
                self.services.update(value)
            elif key == "repositories" and isinstance(value, Mapping):
                for name, repo in value.items():
                    self.repositories[name] = _as_repository(self.session, repo)
            elif key in _RESERVED or key == "get_hook_context":
                continue
            else:
                self.extra[key] = value

    def __getattr__(self, name: str) -> Any:
        extra = self.__dict__.get("extra", {})
        if name in extra:
            return extra[name]
        raise AttributeError(name)

    def get(self, name: str, default: Any = None) -> Any:
        return self.extra.get(name, default)


def _as_repository(session: AsyncSession, value: Any) -> Any:
    try:
        from sqlalchemy import inspect as sa_inspect

        sa_inspect(value)
        if isinstance(value, type):
            return Repository(session, value)
    except Exception:
        pass
    return value


@dataclass
class CrudResult:
    """The outcome of an action, independent of FastAPI."""

    status_code: int = 200
    body: Any = None
    headers: dict[str, str] = field(default_factory=dict)
    media_type: str = "application/json"
    content: bytes | str | None = None
    response: Response | None = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def to_response(self) -> Response:
        if self.response is not None:
            return self.response
        if self.content is not None:
            return Response(
                content=self.content, status_code=self.status_code, headers=self.headers,
                media_type=self.media_type,
            )
        return JSONResponse(jsonable_encoder(self.body), status_code=self.status_code, headers=self.headers)


class CrudAbort(Exception):
    """Raise from a hook to stop the action and return ``result`` as-is."""

    def __init__(self, result: CrudResult | Response) -> None:
        super().__init__("crud action aborted")
        self.result = result


HookFn = Callable[..., Any | Awaitable[Any]]

__all__ = [
    "CrudAbort",
    "CrudRequest",
    "CrudResult",
    "HookContext",
    "Repository",
    "UploadedFile",
    "call_hook",
    "maybe_await",
]
