"""FastAPI integration: ``Crudman.init``, ``crud_router``, ``crud`` decorators and ``CrudController``."""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Path, Request
from fastapi.params import Depends as DependsParam
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from .errors import CrudmanConfigError
from .naming import resolve_path, section_name_for
from .options import (
    ACTIONS,
    ALL_ACTIONS,
    DEFAULT_ACTIONS,
    ActionConfig,
    CrudmanOptions,
    Section,
    effective_config,
    to_section,
)
from .query import resolve_field
from .registry import registry
from .schemas import PydanticValidator, body_schema, column_keys, read_schema, relations_of
from .service import CrudmanService, read_request
from .uploads import expand_upload_config, file_fields

_BODY_ACTIONS = {"create", "update", "save", "bulk_import", "bulk_delete"}


async def crudman_session() -> AsyncSession:
    """Placeholder dependency. ``Crudman.init`` points it at your ``session_dependency``."""
    raise RuntimeError(
        "crudman has no database session. Call Crudman.init(app, CrudmanOptions(session_dependency=get_session))."
    )


def get_crud(session: AsyncSession = Depends(crudman_session)) -> CrudmanService:
    """Dependency for your own routes: ``svc: CrudmanService = Depends(get_crud)``."""
    return CrudmanService(session)


class Crudman:
    """Global setup."""

    @staticmethod
    def init(app: FastAPI | None = None, options: CrudmanOptions | None = None, **kwargs: Any) -> CrudmanOptions:
        opts = options if options is not None else CrudmanOptions(**kwargs)
        registry.set_options(opts)
        if app is not None and opts.session_dependency is not None:
            app.dependency_overrides[crudman_session] = opts.session_dependency
        return opts

    @staticmethod
    def reset() -> None:
        """Forget all options and sections (useful in tests)."""
        registry.reset()

    @staticmethod
    def sections() -> list[str]:
        return sorted(registry.sections)


# ── config checks ─────────────────────────────────────────────────────────────


def _layers(section: Section) -> list[tuple[str, ActionConfig]]:
    out: list[tuple[str, ActionConfig]] = [("section", section)]
    if section.common is not None:
        out.append(("common", section.common))
    for action in ALL_ACTIONS:
        block = getattr(section, action, None)
        if isinstance(block, ActionConfig):
            out.append((action, block))
    return out


def _check_config(name: str, model: Any, section: Section) -> None:
    cols = column_keys(model)
    rels = relations_of(model)
    problems: list[str] = []

    def need_cols(where: str, key: str, fields: Iterable[str] | None) -> None:
        for f in fields or []:
            if resolve_field(f, cols) is None:
                problems.append(f"{where}.{key}: '{f}' is not a column of {model.__name__}")

    for where, cfg in _layers(section):
        need_cols(where, "filters_whitelist", cfg.filters_whitelist)
        need_cols(where, "sorting_whitelist", cfg.sorting_whitelist)
        need_cols(where, "fields_for_uniqueness_validation", cfg.fields_for_uniqueness_validation)
        need_cols(where, "order_by", [f for f, _ in cfg.order_by or []])
        if cfg.record_selection_field:
            need_cols(where, "record_selection_field", [cfg.record_selection_field])
        if cfg.ownership:
            if "field" not in cfg.ownership:
                problems.append(f"{where}.ownership needs a 'field' key")
            else:
                need_cols(where, "ownership", [cfg.ownership["field"]])
        spec = cfg.relations
        names: list[str] = []
        if isinstance(spec, (list, tuple)):
            names = list(spec)
        elif isinstance(spec, Mapping):
            for key in ("include", "exclude"):
                value = spec.get(key)
                if isinstance(value, (list, tuple)):
                    names.extend(value)
        for rel in names:
            if rel.split(".")[0] not in rels:
                problems.append(f"{where}.relations: '{rel}' is not a relationship of {model.__name__}")
    if problems:
        raise CrudmanConfigError(f"Section '{name}' is misconfigured:\n  - " + "\n  - ".join(problems))


# ── endpoint factory ──────────────────────────────────────────────────────────


def _ident(text: str) -> str:
    return re.sub(r"\W", "_", text)


def _context_deps(section: Section | None, action: str) -> dict[tuple[str, str], DependsParam]:
    """``Depends(...)`` values declared in context dicts, so FastAPI can resolve them per request."""
    raws: list[Any] = []
    defaults = registry.options.defaults
    if defaults is not None and "context" in defaults.model_fields_set:
        raws.append(defaults.context)
    if section is not None:
        raws.append(section.context)
        if section.common is not None:
            raws.append(section.common.context)
        block = getattr(section, action, None)
        if isinstance(block, ActionConfig):
            raws.append(block.context)
    found: dict[tuple[str, str], DependsParam] = {}
    for raw in raws:
        if not isinstance(raw, Mapping):
            continue
        for key, value in raw.items():
            if key in ("services", "repositories") and isinstance(value, Mapping):
                for name, item in value.items():
                    if isinstance(item, DependsParam):
                        found[(key, name)] = item
            elif isinstance(value, DependsParam):
                found[("extra", key)] = value
    return found


def make_endpoint(
    section: str,
    action: str,
    *,
    path_param: str | None = None,
    session_dependency: Callable[..., Any] | None = None,
    name: str | None = None,
) -> Callable[..., Any]:
    """Build a FastAPI endpoint function for one section action."""
    entry = registry.sections.get(section)
    deps = _context_deps(entry.config if entry else None, action)
    dep_params = {key: f"ctx_{key[0]}_{_ident(key[1])}" for key in deps}
    with_body = action in _BODY_ACTIONS

    async def endpoint(**kwargs: Any) -> Response:
        request: Request = kwargs["request"]
        session: AsyncSession = kwargs["crudman_session_"]
        resolved = {key: kwargs[param] for key, param in dep_params.items()}
        svc = CrudmanService(session, resolved_deps=resolved)
        creq = await read_request(request, with_body=with_body)
        result = await svc.run(section, action, creq)
        return result.to_response()

    params = [
        inspect.Parameter("request", inspect.Parameter.KEYWORD_ONLY, annotation=Request),
        inspect.Parameter(
            "crudman_session_", inspect.Parameter.KEYWORD_ONLY,
            default=Depends(session_dependency or crudman_session), annotation=Any,
        ),
    ]
    if path_param:
        params.append(inspect.Parameter(
            path_param, inspect.Parameter.KEYWORD_ONLY, default=Path(...), annotation=str,
        ))
    for key, param_name in dep_params.items():
        params.append(inspect.Parameter(param_name, inspect.Parameter.KEYWORD_ONLY, default=deps[key],
                                        annotation=Any))
    endpoint.__signature__ = inspect.Signature(params, return_annotation=Response)  # type: ignore[attr-defined]
    endpoint.__name__ = name or f"{_ident(section)}_{action}"
    endpoint.__qualname__ = endpoint.__name__
    return endpoint


# ── OpenAPI ───────────────────────────────────────────────────────────────────


def _list_parameters(cfg: ActionConfig) -> list[dict[str, Any]]:
    names = cfg.param_names()
    return [
        {"name": names.page, "in": "query", "required": False, "schema": {"type": "integer", "minimum": 1},
         "description": "Page number (default 1)"},
        {"name": names.per_page, "in": "query", "required": False, "schema": {"type": "integer", "minimum": 0},
         "description": "Items per page (default 30; 0 returns everything when allowed)"},
        {"name": names.paginate, "in": "query", "required": False, "schema": {"type": "string"},
         "description": "false / 0 / no to return everything"},
        {"name": names.keyword, "in": "query", "required": False, "schema": {"type": "string"},
         "description": "Keyword search"},
        {"name": "x-content-type", "in": "header", "required": False,
         "schema": {"type": "string", "enum": list(registry.options.export_content_types)},
         "description": "Response format; filters use field=value, field.like, .min, .max, .gt, .lt, "
                        ".between; sorting uses sort.<field>=asc|desc"},
    ]


def _envelope(action: str, item: dict[str, Any]) -> dict[str, Any]:
    base: dict[str, Any] = {
        "errors": {"type": "array", "items": {"type": "object"}},
        "success": {"type": "boolean"},
        "meta": {"type": "object"},
    }
    if action == "list":
        return {"type": "object", "properties": {
            "data": {"type": "array", "items": item}, **base,
            "pagination": {"type": "object", "properties": {
                k: {"type": "integer"} for k in ("page", "perPage", "totalItemsCount", "totalPagesCount")
            } | {"isHavingNextPage": {"type": "boolean"}, "isHavingPreviousPage": {"type": "boolean"}}},
            "filters": {"type": "array", "items": {"type": "object"}},
            "sorting": {"type": "array", "items": {"type": "object"}},
        }}
    if action == "delete":
        return {"type": "object", "properties": {"data": {"type": "object", "properties": {
            "message": {"type": "string"}}}, **base}}
    if action.startswith("bulk"):
        return {"type": "object", "properties": {"data": {"type": "object"}, **base}}
    return {"type": "object", "properties": {"data": item, **base}}


def _openapi_for(section: str, model: Any, action: str, cfg: ActionConfig) -> dict[str, Any]:
    opts = registry.options
    extra: dict[str, Any] = {}
    if action == "list":
        extra["parameters"] = _list_parameters(cfg)
    elif action == "details":
        extra["parameters"] = [_list_parameters(cfg)[-1]]
    if action in ("create", "update", "save"):
        is_update = action == "update"
        rules = PydanticValidator().generate_rules(model, is_update, cfg.write_attributes())
        schema_model = PydanticValidator().build(f"{model.__name__}{'Update' if is_update else 'Create'}",
                                                 rules, is_update)
        uploads = file_fields(expand_upload_config(cfg, opts.upload_response, opts.default_file_storage)) \
            if (cfg.uploadable or cfg.upload) else []
        content: dict[str, Any] = {}
        kinds = opts.openapi.request_body_content_types
        if "json" in kinds:
            content["application/json"] = {"schema": body_schema(schema_model)}
        if "form" in kinds and not uploads:
            content["application/x-www-form-urlencoded"] = {"schema": body_schema(schema_model)}
        if "multipart" in kinds:
            content["multipart/form-data"] = {"schema": body_schema(schema_model, uploads, multipart=True)}
        extra["requestBody"] = {"required": action != "update", "content": content}
    elif action == "bulk_import":
        extra["requestBody"] = {"required": True, "content": {
            "application/json": {"schema": {"type": "array", "items": {"type": "object"}}},
            "text/csv": {"schema": {"type": "string"}},
        }}
        extra["parameters"] = [
            {"name": n, "in": "query", "required": False, "schema": s} for n, s in (
                ("policy", {"type": "string", "enum": ["upsert", "insert_only", "update_only",
                                                       "ignore_on_conflict", "replace"]}),
                ("batch_size", {"type": "integer"}), ("dry_run", {"type": "boolean"}),
                ("stop_on_error", {"type": "boolean"}), ("record_selection_field", {"type": "string"}),
            )
        ]
    elif action == "bulk_delete":
        extra["requestBody"] = {"required": True, "content": {
            "application/json": {"schema": {"type": "object", "properties": {
                "ids": {"type": "array", "items": {}}}}},
            "text/csv": {"schema": {"type": "string"}},
        }}
    item = read_schema(model, cfg.read_attributes(), opts.field_alias)
    responses: dict[str, Any] = {"200": {"description": "Success", "content": {"application/json": {
        "schema": _envelope(action, item)}}}}
    if action in ("list", "details"):
        responses["200"]["content"]["text/csv"] = {"schema": {"type": "string"}}
    extra["responses"] = responses
    return extra


# ── crud_router ───────────────────────────────────────────────────────────────

ModelEntry = Any


def _expand_actions(actions: Sequence[str] | None) -> list[str]:
    if actions is None:
        return list(DEFAULT_ACTIONS)
    out: list[str] = []
    for action in actions:
        items = DEFAULT_ACTIONS if action == "*" else (action,)
        for item in items:
            if item not in ALL_ACTIONS:
                raise CrudmanConfigError(f"Unknown action '{item}'. Use: {', '.join(ALL_ACTIONS)} or '*'.")
            if item not in out:
                out.append(item)
    return out


def _unpack(entry: ModelEntry) -> tuple[Any, str | None, Any]:
    if isinstance(entry, tuple):
        if len(entry) == 1:
            return entry[0], None, None
        if len(entry) == 2:
            second = entry[1]
            return (entry[0], second, None) if isinstance(second, str) else (entry[0], None, second)
        if len(entry) == 3:
            return entry[0], entry[1], entry[2]
        raise CrudmanConfigError("Model tuples are (Model), (Model, name), (Model, config) or (Model, name, config)")
    return entry, None, None


def register_section(model: Any, section: str | None = None, config: Any = None) -> str:
    sec = to_section(config)
    name = section_name_for(model, section)
    _check_config(name, model, sec)
    registry.register(name, model, sec)
    return name


def crud_router(
    model: Any,
    section: str | None = None,
    config: Section | Mapping[str, Any] | None = None,
    *,
    path: str | None = None,
    actions: Sequence[str] | None = None,
    tags: list[str] | None = None,
    path_style: str | None = None,
    update_method: str | None = None,
    dependencies: Sequence[Any] | None = None,
) -> APIRouter:
    """Build an ``APIRouter`` with CRUD routes for ``model``.

    ``section`` defaults to the model's table name; ``path`` defaults to ``/{section}``.
    Pass a list of models (or tuples) to mount several sections in one router.
    """
    opts = registry.options
    style = path_style or opts.path_style
    if isinstance(model, (list, tuple)) and not isinstance(model, str):
        if section is not None or config is not None or path is not None:
            raise CrudmanConfigError("With a list of models, give names and settings inside the tuples.")
        combined = APIRouter(dependencies=list(dependencies or []))
        for entry in model:
            m, name, cfg = _unpack(entry)
            combined.include_router(crud_router(m, name, cfg, actions=actions, path_style=style,
                                                update_method=update_method))
        return combined

    name = register_section(model, section, config)
    entry = registry.get(name)
    prefix = resolve_path(name, path, style, opts.route_prefix)  # type: ignore[arg-type]
    router = APIRouter(prefix=prefix, tags=list(tags or [name]), dependencies=list(dependencies or []))
    verb = (update_method or opts.update_method).upper()
    session_dep = entry.config.session

    for action in _expand_actions(actions):
        cfg = effective_config(opts.defaults, entry.config, action)
        sel = cfg.selection_field()
        needs_id = action in ("details", "update", "delete")
        endpoint = make_endpoint(name, action, path_param=sel if needs_id else None,
                                 session_dependency=cfg.session or session_dep)
        route_path, methods = {
            "list": ("", ["GET"]),
            "details": (f"/{{{sel}}}", ["GET"]),
            "create": ("", ["POST"]),
            "update": (f"/{{{sel}}}", [verb]),
            "delete": (f"/{{{sel}}}", ["DELETE"]),
            "save": ("/save", ["POST"]),
            "bulk_import": ("/bulk/import", ["POST"]),
            "bulk_delete": ("/bulk/delete", ["POST"]),
        }[action]
        include = (entry.config.openapi or {}).get("enabled", True) and opts.openapi.enabled
        router.add_api_route(
            route_path, endpoint, methods=methods, name=f"{name}_{action}", operation_id=f"{_ident(name)}_{action}",
            summary=f"{entry.config.title or name}: {action.replace('_', ' ')}",
            description=entry.config.description, include_in_schema=include,
            openapi_extra=_openapi_for(name, model, action, cfg) if include else None,
        )
    # declared routes that collide ("/save" vs "/{id}" for GET) are ordered: fixed paths first
    router.routes.sort(key=lambda r: "{" in getattr(r, "path", ""))
    return router


# ── decorators ────────────────────────────────────────────────────────────────


class _Crud:
    """``crud.register(Model)`` and ``@crud.list("section")`` style decorators."""

    def register(self, model: Any, section: str | None = None, config: Any = None) -> str:
        return register_section(model, section, config)

    def _decorator(self, section: str, action: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def wrap(fn: Callable[..., Any]) -> Callable[..., Any]:
            entry = registry.sections.get(section)
            session_dep = entry.config.session if entry else None
            endpoint = make_endpoint(section, action, session_dependency=session_dep, name=fn.__name__)
            endpoint.__doc__ = fn.__doc__
            return endpoint

        return wrap

    def list(self, section: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._decorator(section, "list")

    def details(self, section: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._decorator(section, "details")

    def create(self, section: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._decorator(section, "create")

    def update(self, section: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._decorator(section, "update")

    def delete(self, section: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._decorator(section, "delete")

    def save(self, section: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._decorator(section, "save")

    def bulk_import(self, section: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._decorator(section, "bulk_import")

    def bulk_delete(self, section: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._decorator(section, "bulk_delete")


crud = _Crud()


class CrudController:
    """Class-based form::

        class CompaniesController(CrudController, model=Company):
            pass

        app.include_router(CompaniesController.router)
    """

    router: APIRouter
    section: str

    def __init_subclass__(
        cls,
        *,
        model: Any = None,
        section: str | None = None,
        config: Any = None,
        path: str | None = None,
        actions: Sequence[str] | None = None,
        tags: list[str] | None = None,
        prefix: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init_subclass__(**kwargs)
        if model is None:
            return
        router = crud_router(model, section, config, path=path, actions=actions, tags=tags)
        if prefix:
            outer = APIRouter(prefix=prefix)
            outer.include_router(router)
            router = outer
        cls.router = router
        cls.section = section_name_for(model, section)


__all__ = [
    "ACTIONS",
    "Crudman",
    "CrudController",
    "crud",
    "crud_router",
    "crudman_session",
    "get_crud",
    "make_endpoint",
    "register_section",
]
