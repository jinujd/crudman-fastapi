"""NestJS-style controllers: routes defined with decorators.

    @Controller("/api/companies")
    @Crud(Company)                       # list, details, create, update, delete
    class CompaniesController:
        @Roles("admin")
        @CrudDelete()
        async def remove(self): ...      # empty body: crudman handles it

        @Get("/{id}/summary")
        async def summary(self, id: int, request: Request):
            return (await self.crud.details("companies", request)).body

    app.include_router(CompaniesController.router)

The router is built the first time ``.router`` is read, so class decorators can be stacked in any order and
``Crudman.init`` options (auth, path style, update method) apply even if the class was defined first.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, TypeVar

from fastapi import APIRouter, Depends, Request
from starlette.responses import Response

from .auth import ORIGINAL_ATTR, enforce, policy_of, resolve, resolved_signature
from .context import CrudResult, maybe_await
from .errors import CrudmanConfigError
from .naming import apply_path_style, normalize_path
from .options import ALL_ACTIONS, DEFAULT_ACTIONS, effective_config
from .registry import registry
from .routing import add_crud_route, crudman_session, register_section, route_for
from .service import CrudmanService

C = TypeVar("C", bound=type)
F = TypeVar("F", bound=Callable[..., Any])

CONTROLLER_ATTR = "__crudman_controller__"
CRUDS_ATTR = "__crudman_cruds__"
ROUTE_ATTR = "__crudman_route__"
BUILT_ATTR = "__crudman_router_built__"


@dataclass(frozen=True)
class ControllerMeta:
    prefix: str = ""
    tags: tuple[str, ...] | None = None
    dependencies: tuple[Any, ...] = ()


@dataclass(frozen=True)
class CrudSpec:
    model: Any
    section: str | None
    config: Any
    path: str | None
    actions: tuple[str, ...] | None


@dataclass(frozen=True)
class RouteSpec:
    kind: str  # "crud" or "custom"
    path: str | None
    action: str | None = None
    section: str | None = None
    methods: tuple[str, ...] = ()
    options: dict[str, Any] = field(default_factory=dict)


# ── lazy router ───────────────────────────────────────────────────────────────


class _LazyRouter:
    """Class attribute that builds the controller's ``APIRouter`` on first access."""

    def __get__(self, instance: Any, owner: type) -> APIRouter:
        built = owner.__dict__.get(BUILT_ATTR)
        if built is None:
            built = build_router(owner)
            setattr(owner, BUILT_ATTR, built)
        return built


def _install(cls: type) -> None:
    if not isinstance(cls.__dict__.get("router"), _LazyRouter):
        cls.router = _LazyRouter()  # type: ignore[attr-defined]


# ── class decorators ──────────────────────────────────────────────────────────


def Controller(  # noqa: N802 - NestJS-style name
    prefix: str = "",
    *,
    tags: Sequence[str] | None = None,
    dependencies: Sequence[Any] | None = None,
) -> Callable[[C], C]:
    """URL prefix (and optional tags / FastAPI dependencies) for every route in the class."""

    def apply(cls: C) -> C:
        if not inspect.isclass(cls):
            raise CrudmanConfigError("@Controller(...) decorates a class")
        setattr(cls, CONTROLLER_ATTR, ControllerMeta(prefix, tuple(tags) if tags else None,
                                                     tuple(dependencies or ())))
        _install(cls)
        return cls

    return apply


def Crud(  # noqa: N802
    model: Any,
    section: str | None = None,
    config: Any = None,
    *,
    path: str | None = None,
    actions: Sequence[str] | None = None,
) -> Callable[[C], C]:
    """Register a CRUD section on the controller and generate its routes.

    ``actions=None`` generates list, details, create, update, delete; ``actions=[]`` generates none (only routes
    declared with ``@CrudList()`` etc. are mounted). ``path`` is relative to the controller prefix; it defaults to
    ``""`` for a single ``@Crud`` and ``/{section}`` when the controller has several.
    """
    for action in actions or ():
        if action not in ALL_ACTIONS and action != "*":
            raise CrudmanConfigError(f"@Crud(actions=...): unknown action '{action}'")

    def apply(cls: C) -> C:
        if not inspect.isclass(cls):
            raise CrudmanConfigError("@Crud(...) decorates a class")
        specs: list[CrudSpec] = list(cls.__dict__.get(CRUDS_ATTR, []))
        # class decorators run bottom-up; insert at the front to keep top-to-bottom order
        specs.insert(0, CrudSpec(model, section, config, path, tuple(actions) if actions is not None else None))
        setattr(cls, CRUDS_ATTR, specs)
        _install(cls)
        return cls

    return apply


# ── method decorators ─────────────────────────────────────────────────────────


def _set_route(fn: F, spec: RouteSpec) -> F:
    if getattr(fn, ROUTE_ATTR, None) is not None:
        raise CrudmanConfigError(f"{getattr(fn, '__qualname__', fn)} has more than one route decorator")
    setattr(fn, ROUTE_ATTR, spec)
    return fn


def _crud_decorator(action: str) -> Callable[..., Callable[[F], F]]:
    def factory(path: str | None = None, *, section: str | None = None) -> Callable[[F], F]:
        def apply(fn: F) -> F:
            return _set_route(fn, RouteSpec(kind="crud", path=path, action=action, section=section))

        return apply

    factory.__name__ = "Crud" + "".join(part.capitalize() for part in action.split("_"))
    factory.__doc__ = (f"Mount the {action.replace('_', ' ')} action. ``path`` overrides its default path "
                       "(relative to the section); an empty body lets crudman handle the request, and a "
                       "``result: CrudResult`` parameter receives the result to change or replace it.")
    return factory


CrudList = _crud_decorator("list")
CrudDetails = _crud_decorator("details")
CrudCreate = _crud_decorator("create")
CrudUpdate = _crud_decorator("update")
CrudDelete = _crud_decorator("delete")
CrudSave = _crud_decorator("save")
CrudBulkImport = _crud_decorator("bulk_import")
CrudBulkDelete = _crud_decorator("bulk_delete")


def _http_decorator(method: str) -> Callable[..., Callable[[F], F]]:
    def factory(path: str = "", **options: Any) -> Callable[[F], F]:
        def apply(fn: F) -> F:
            return _set_route(fn, RouteSpec(kind="custom", path=path, methods=(method,), options=options))

        return apply

    factory.__name__ = method.capitalize()
    factory.__doc__ = (f"A custom {method} route. Extra keyword arguments (status_code, response_model, "
                       "summary, …) are passed to FastAPI.")
    return factory


Get = _http_decorator("GET")
Post = _http_decorator("POST")
Put = _http_decorator("PUT")
Patch = _http_decorator("PATCH")
Delete = _http_decorator("DELETE")

# Lowercase aliases
controller = Controller
crud_resource = Crud
crud_list, crud_details, crud_create, crud_update = CrudList, CrudDetails, CrudCreate, CrudUpdate
crud_delete, crud_save, crud_bulk_import, crud_bulk_delete = CrudDelete, CrudSave, CrudBulkImport, CrudBulkDelete
get, post, put, patch, delete = Get, Post, Put, Patch, Delete


# ── building the router ───────────────────────────────────────────────────────


def _instance_factory(cls: type) -> Callable[..., Any]:
    """A dependency that creates the controller per request, resolving ``Depends`` in ``__init__``."""
    init = cls.__dict__.get("__init__") or next(
        (k.__dict__["__init__"] for k in cls.__mro__ if "__init__" in k.__dict__), object.__init__)
    params: list[inspect.Parameter] = []
    if init is not object.__init__:
        for p in list(resolved_signature(init).parameters.values())[1:]:
            if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
                continue
            params.append(p.replace(kind=inspect.Parameter.KEYWORD_ONLY))
    params.append(inspect.Parameter("crudman_session_", inspect.Parameter.KEYWORD_ONLY,
                                    default=Depends(crudman_session), annotation=Any))

    async def factory(**kwargs: Any) -> Any:
        session = kwargs.pop("crudman_session_")
        instance = cls(**kwargs)
        instance.crud = CrudmanService(session)
        return instance

    factory.__signature__ = inspect.Signature(params)  # type: ignore[attr-defined]
    factory.__name__ = f"{cls.__name__}_instance"
    return factory


def _wants_result(fn: Callable[..., Any]) -> bool:
    return "result" in inspect.signature(fn).parameters


def _custom_endpoint(cls: type, attr: str, obj: Any, factory: Callable[..., Any],
                     auth: Any, status_code: int | None = None) -> Callable[..., Any]:
    fn = getattr(obj, ORIGINAL_ATTR, obj)
    sig = resolved_signature(fn)
    params = [p.replace(kind=inspect.Parameter.KEYWORD_ONLY) for p in list(sig.parameters.values())[1:]
              if p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)]
    names = {p.name for p in params}
    # FastAPI injects the Request into only one parameter, so reuse the method's own if it has one
    own_request = next((p.name for p in params if p.annotation in (Request, "Request")), None)
    extra = [inspect.Parameter("crudman_self_", inspect.Parameter.KEYWORD_ONLY, default=Depends(factory),
                               annotation=Any)]
    if auth is not None:
        extra.append(inspect.Parameter("crudman_identity_", inspect.Parameter.KEYWORD_ONLY,
                                       default=Depends(auth.dependency), annotation=Any))
        if own_request is None:
            extra.append(inspect.Parameter("crudman_request_", inspect.Parameter.KEYWORD_ONLY, annotation=Request))

    async def endpoint(**kwargs: Any) -> Any:
        instance = kwargs.pop("crudman_self_")
        if auth is not None:
            request: Request = kwargs.pop("crudman_request_") if own_request is None else kwargs[own_request]
            identity = await enforce(auth, kwargs.pop("crudman_identity_", None))
            if identity is not None:
                request.state.identity = identity
        out = await maybe_await(fn(instance, **{k: v for k, v in kwargs.items() if k in names}))
        if isinstance(out, CrudResult):
            return _with_status(out, status_code)
        return out

    endpoint.__signature__ = sig.replace(parameters=[*params, *extra])  # type: ignore[attr-defined]
    endpoint.__name__ = f"{cls.__name__}_{attr}"
    endpoint.__doc__ = fn.__doc__
    return endpoint


def _with_status(result: CrudResult, status_code: int | None) -> Response:
    """A returned ``CrudResult`` as a response. The route's ``status_code=`` applies to a successful result;
    errors keep crudman's status, and a result that wraps a ready ``Response`` is sent unchanged."""
    if status_code is None or not result.ok or result.response is not None:
        return result.to_response()
    if status_code in (204, 304):  # no body allowed
        return Response(status_code=status_code, headers=result.headers)
    return replace(result, status_code=status_code).to_response()


def build_router(cls: type) -> APIRouter:
    """Build the ``APIRouter`` for a controller class."""
    meta: ControllerMeta = getattr(cls, CONTROLLER_ATTR, ControllerMeta())
    class_policy = policy_of(cls)
    cruds: list[CrudSpec] = list(cls.__dict__.get(CRUDS_ATTR, []))
    opts = registry.options
    router = APIRouter(
        prefix=normalize_path(meta.prefix),
        tags=list(meta.tags) if meta.tags else [cls.__name__.removesuffix("Controller") or cls.__name__],
        dependencies=list(meta.dependencies),
    )

    sections: dict[str, str] = {}  # section name → base path
    names: list[str] = []
    for spec in cruds:
        name = register_section(spec.model, spec.section, spec.config)
        names.append(name)
        if name in sections:
            raise CrudmanConfigError(f"{cls.__name__}: @Crud for section '{name}' is declared twice")
        if spec.path is not None:
            base = normalize_path(spec.path)
        elif len(cruds) == 1:
            base = ""
        else:
            base = normalize_path(apply_path_style(name, opts.path_style))
        sections[name] = base

    overrides: dict[tuple[str, str], tuple[str, Any, RouteSpec]] = {}
    customs: list[tuple[str, Any, RouteSpec]] = []
    for attr, obj in cls.__dict__.items():
        route = getattr(obj, ROUTE_ATTR, None)
        if not isinstance(route, RouteSpec):
            continue
        if route.kind == "custom":
            customs.append((attr, obj, route))
            continue
        if route.section is not None:
            section = route.section
        elif len(sections) == 1:
            section = next(iter(sections))
        elif not sections:
            raise CrudmanConfigError(f"{cls.__name__}.{attr}: add @Crud(Model) to the class before using "
                                     f"@{'Crud' + ''.join(p.capitalize() for p in (route.action or '').split('_'))}()")
        else:
            raise CrudmanConfigError(f"{cls.__name__}.{attr}: the controller has several sections "
                                     f"({', '.join(sections)}); pass section='...'")
        if section not in sections:
            raise CrudmanConfigError(f"{cls.__name__}.{attr}: section '{section}' is not declared with @Crud")
        key = (section, route.action or "")
        if key in overrides:
            raise CrudmanConfigError(f"{cls.__name__}: {section}.{route.action} is defined twice "
                                     f"({overrides[key][0]} and {attr})")
        overrides[key] = (attr, obj, route)

    factory = _instance_factory(cls)
    seen: dict[tuple[str, str], str] = {}

    def claim(methods: Sequence[str], path: str, what: str) -> None:
        for method in methods:
            key = (method.upper(), path or "/")
            if key in seen:
                raise CrudmanConfigError(f"{cls.__name__}: {method} {meta.prefix}{path} is defined by both "
                                         f"{seen[key]} and {what}")
            seen[key] = what

    for spec, section in zip(cruds, names, strict=True):
        actions = list(DEFAULT_ACTIONS if spec.actions is None else
                       [a for a in spec.actions if a != "*"] + (list(DEFAULT_ACTIONS) if "*" in spec.actions else []))
        for (sec, action) in overrides:
            if sec == section and action not in actions:
                actions.append(action)
        for action in actions:
            override = overrides.get((section, action))
            cfg = effective_config(opts.defaults, registry.get(section).config, action)
            default_rel, methods = route_for(action, cfg.selection_field(), opts.update_method)
            rel = default_rel
            levels = [class_policy]
            after = None
            route_name: str | None = None
            if override is not None:
                attr, obj, rspec = override
                if rspec.path is not None:
                    rel = normalize_path(rspec.path) if rspec.path not in ("", "/") else ""
                levels = [policy_of(obj), class_policy]
                fn = getattr(obj, ORIGINAL_ATTR, obj)
                if _wants_result(fn):
                    def after(instance: Any, result: CrudResult, _fn: Any = fn) -> Any:
                        return _fn(instance, result=result)
                route_name = f"{cls.__name__}_{attr}"
            full = sections[section] + rel
            claim(methods, full, route_name or f"{section}.{action}")
            add_crud_route(
                router, section, action, path=full, auth_levels=levels,
                instance_dependency=factory if after is not None else None, after=after,
                name=route_name, operation_id=route_name,
            )

    for attr, obj, custom in customs:
        auth = resolve(policy_of(obj), class_policy)
        path = normalize_path(custom.path or "")
        claim(custom.methods, path, f"{cls.__name__}.{attr}")
        options = dict(custom.options)
        endpoint = _custom_endpoint(cls, attr, obj, factory, auth, options.get("status_code"))
        options.setdefault("response_model", None)
        options.setdefault("operation_id", f"{cls.__name__}_{attr}")
        fn = getattr(obj, ORIGINAL_ATTR, obj)
        doc = (inspect.getdoc(fn) or "").strip().splitlines()
        options.setdefault("summary", doc[0] if doc else attr.replace("_", " ").capitalize())
        options.setdefault("name", f"{cls.__name__}_{attr}")
        router.add_api_route(path, endpoint, methods=list(custom.methods), **options)

    router.routes.sort(key=lambda r: "{" in getattr(r, "path", ""))
    return router


__all__ = [
    "Controller",
    "Crud",
    "CrudBulkDelete",
    "CrudBulkImport",
    "CrudCreate",
    "CrudDelete",
    "CrudDetails",
    "CrudList",
    "CrudSave",
    "CrudUpdate",
    "Delete",
    "Get",
    "Patch",
    "Post",
    "Put",
    "build_router",
    "controller",
    "crud_bulk_delete",
    "crud_bulk_import",
    "crud_create",
    "crud_delete",
    "crud_details",
    "crud_list",
    "crud_resource",
    "crud_save",
    "crud_update",
    "delete",
    "get",
    "patch",
    "post",
    "put",
]
