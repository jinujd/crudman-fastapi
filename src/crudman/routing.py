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

from .auth import AuthPolicy, ResolvedAuth, crudman_auth, crudman_default_auth, enforce, resolve
from .context import CrudResult, maybe_await
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


async def _no_identity() -> None:
    return None


def include_controllers(app: FastAPI | APIRouter, controllers: Iterable[Any]) -> None:
    """Include the routers of several controller classes."""
    for controller in controllers:
        router = getattr(controller, "router", None)
        if not isinstance(router, APIRouter):
            raise CrudmanConfigError(f"{controller!r} is not a controller (no .router)")
        app.include_router(router)


class Crudman:
    """Global setup."""

    @staticmethod
    def init(app: FastAPI | None = None, options: CrudmanOptions | None = None, **kwargs: Any) -> CrudmanOptions:
        opts = options if options is not None else CrudmanOptions(**kwargs)
        registry.set_options(opts)
        if app is not None and opts.session_dependency is not None:
            app.dependency_overrides[crudman_session] = opts.session_dependency
        if app is not None and opts.auth is not None:
            # routes built before init use placeholders; point them at the real dependency
            app.dependency_overrides[crudman_auth] = opts.auth.dependency
            app.dependency_overrides[crudman_default_auth] = (
                opts.auth.dependency if opts.auth.default == "private" else _no_identity
            )
        if app is not None and opts.controllers:
            include_controllers(app, opts.controllers)
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
    auth: ResolvedAuth | None = None,
    instance_dependency: Callable[..., Any] | None = None,
    after: Callable[..., Any] | None = None,
) -> Callable[..., Any]:
    """Build a FastAPI endpoint function for one section action.

    ``auth`` adds the auth dependency (401/403 handling); ``instance_dependency`` + ``after`` let a controller
    method post-process the result.
    """
    entry = registry.sections.get(section)
    deps = _context_deps(entry.config if entry else None, action)
    dep_params = {key: f"ctx_{key[0]}_{_ident(key[1])}" for key in deps}
    with_body = action in _BODY_ACTIONS

    async def endpoint(**kwargs: Any) -> Response:
        request: Request = kwargs["request"]
        session: AsyncSession = kwargs["crudman_session_"]
        identity: dict[str, Any] | None = None
        if auth is not None:
            identity = await enforce(auth, kwargs.get("crudman_identity_"))
            if identity is not None:
                request.state.identity = identity
        resolved = {key: kwargs[param] for key, param in dep_params.items()}
        svc = CrudmanService(session, resolved_deps=resolved)
        creq = await read_request(request, with_body=with_body)
        if identity is not None:
            creq.identity = identity
        result = await svc.run(section, action, creq)
        if after is not None:
            out = await maybe_await(after(kwargs.get("crudman_self_"), result))
            if isinstance(out, Response):
                return out
            if isinstance(out, CrudResult):
                result = out
            elif out is not None:
                result.body = out
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
    if auth is not None:
        params.append(inspect.Parameter("crudman_identity_", inspect.Parameter.KEYWORD_ONLY,
                                        default=Depends(auth.dependency), annotation=Any))
    if instance_dependency is not None:
        params.append(inspect.Parameter("crudman_self_", inspect.Parameter.KEYWORD_ONLY,
                                        default=Depends(instance_dependency), annotation=Any))
    endpoint.__signature__ = inspect.Signature(params, return_annotation=Response)  # type: ignore[attr-defined]
    endpoint.__name__ = name or f"{_ident(section)}_{action}"
    endpoint.__qualname__ = endpoint.__name__
    return endpoint


def route_for(action: str, selection_field: str, update_verb: str) -> tuple[str, list[str]]:
    """Default path (relative to the section) and HTTP methods of an action."""
    sel = selection_field
    return {
        "list": ("", ["GET"]),
        "details": (f"/{{{sel}}}", ["GET"]),
        "create": ("", ["POST"]),
        "update": (f"/{{{sel}}}", [update_verb.upper()]),
        "delete": (f"/{{{sel}}}", ["DELETE"]),
        "save": ("/save", ["POST"]),
        "bulk_import": ("/bulk/import", ["POST"]),
        "bulk_delete": ("/bulk/delete", ["POST"]),
    }[action]


def section_auth_policy(cfg: ActionConfig) -> AuthPolicy | None:
    return AuthPolicy(mode=cfg.auth) if cfg.auth else None


def add_crud_route(
    router: APIRouter,
    section: str,
    action: str,
    *,
    path: str | None = None,
    auth_levels: Sequence[AuthPolicy | None] = (),
    update_method: str | None = None,
    instance_dependency: Callable[..., Any] | None = None,
    after: Callable[..., Any] | None = None,
    name: str | None = None,
    operation_id: str | None = None,
) -> None:
    """Add one CRUD action route to ``router`` (shared by ``crud_router`` and controllers)."""
    opts = registry.options
    entry = registry.get(section)
    cfg = effective_config(opts.defaults, entry.config, action)
    sel = cfg.selection_field()
    default_path, methods = route_for(action, sel, update_method or opts.update_method)
    route_path = default_path if path is None else path
    path_params = re.findall(r"{(\w+)}", route_path)
    if action in ("details", "update", "delete") and not path_params:
        raise CrudmanConfigError(
            f"Route '{route_path}' for {section}.{action} needs a path parameter such as '/{{{sel}}}'."
        )
    auth = resolve(*auth_levels, section_auth_policy(cfg))
    endpoint = make_endpoint(
        section, action, path_param=path_params[0] if path_params else None,
        session_dependency=cfg.session or entry.config.session, name=name, auth=auth,
        instance_dependency=instance_dependency, after=after,
    )
    include = (entry.config.openapi or {}).get("enabled", True) and opts.openapi.enabled
    router.add_api_route(
        route_path, endpoint, methods=methods, name=name or f"{section}_{action}",
        operation_id=operation_id or f"{_ident(section)}_{action}",
        summary=f"{entry.config.title or section}: {action.replace('_', ' ')}",
        description=entry.config.description, include_in_schema=include,
        openapi_extra=_openapi_for(section, entry.model, action, cfg) if include else None,
    )


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


def _router_policies(
    action: str,
    auth: str | bool | None,
    public: Sequence[str] | None,
    private: Sequence[str] | None,
    roles: Mapping[str, Sequence[str]] | Sequence[str] | None,
) -> list[AuthPolicy | None]:
    """crud_router(auth=..., public=[...], private=[...], roles=...) as policies, nearest first."""
    per_action: AuthPolicy | None = None
    if isinstance(roles, Mapping) and roles.get(action):
        per_action = AuthPolicy(mode="private", roles=tuple(roles[action]))
    elif public and action in public:
        per_action = AuthPolicy(mode="public")
    elif private and action in private:
        per_action = AuthPolicy(mode="private")
    router_wide: AuthPolicy | None = None
    if roles is not None and not isinstance(roles, Mapping) and roles:
        router_wide = AuthPolicy(mode="private", roles=tuple(roles))
    elif auth is not None:
        mode = "private" if auth is True or auth == "private" else "public"
        router_wide = AuthPolicy(mode=mode)  # type: ignore[arg-type]
    return [per_action, router_wide]


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
    auth: str | bool | None = None,
    public: Sequence[str] | None = None,
    private: Sequence[str] | None = None,
    roles: Mapping[str, Sequence[str]] | Sequence[str] | None = None,
) -> APIRouter:
    """Build an ``APIRouter`` with CRUD routes for ``model``.

    ``section`` defaults to the model's table name; ``path`` defaults to ``/{section}``.
    Pass a list of models (or tuples) to mount several sections in one router.

    Auth (routes are public unless asked): ``auth="private"`` protects every route, ``private=["create"]`` /
    ``public=["list"]`` pick actions, ``roles={"delete": ["admin"]}`` (or a list for every action) adds roles.
    """
    opts = registry.options
    style = path_style or opts.path_style
    _check_actions_named("public", public)
    _check_actions_named("private", private)
    if isinstance(roles, Mapping):
        _check_actions_named("roles", list(roles))
    if isinstance(model, (list, tuple)) and not isinstance(model, str):
        if section is not None or config is not None or path is not None:
            raise CrudmanConfigError("With a list of models, give names and settings inside the tuples.")
        combined = APIRouter(dependencies=list(dependencies or []))
        for entry in model:
            m, name, cfg = _unpack(entry)
            combined.include_router(crud_router(m, name, cfg, actions=actions, path_style=style,
                                                update_method=update_method, auth=auth, public=public,
                                                private=private, roles=roles))
        return combined

    name = register_section(model, section, config)
    prefix = resolve_path(name, path, style, opts.route_prefix)  # type: ignore[arg-type]
    router = APIRouter(prefix=prefix, tags=list(tags or [name]), dependencies=list(dependencies or []))
    for action in _expand_actions(actions):
        add_crud_route(router, name, action, update_method=update_method,
                       auth_levels=_router_policies(action, auth, public, private, roles))
    # declared routes that collide ("/save" vs "/{id}" for GET) are ordered: fixed paths first
    router.routes.sort(key=lambda r: "{" in getattr(r, "path", ""))
    return router


def _check_actions_named(option: str, names: Sequence[str] | None) -> None:
    for action in names or []:
        if action not in ALL_ACTIONS:
            raise CrudmanConfigError(f"crud_router({option}=...): unknown action '{action}'. "
                                     f"Use: {', '.join(ALL_ACTIONS)}.")


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
