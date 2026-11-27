"""The CRUD pipeline. Framework-agnostic: takes a ``CrudRequest``, returns a ``CrudResult``."""

from __future__ import annotations

import builtins
import json
from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException
from fastapi.params import Depends as DependsParam
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.requests import Request
from starlette.responses import Response

from .adapters.sqlalchemy import FilterValueError, ListQuery, SqlAlchemyAdapter
from .cache import default_cache_key
from .context import CrudAbort, CrudRequest, CrudResult, HookContext, UploadedFile, call_hook, maybe_await
from .export import EXCEL_MIME, list_headers, parse_csv, requested_format, to_csv, to_excel
from .options import ActionConfig, Keyword, Pagination
from .query import (
    SortItem,
    finalize_pagination,
    keyword_paths,
    parse_filters,
    parse_keyword,
    parse_pagination,
    parse_sorting,
    to_snake,
)
from .registry import Registry, SectionEntry, registry
from .response import DELETE_PAYLOAD, FormatInput, default_response_formatter
from .schemas import PydanticValidator, column_keys, columns_of, primary_key_of, serialize
from .uploads import base_urls, expand_upload_config, process_uploads

WRITE_ACTIONS = {"create", "update", "save"}
BULK_POLICIES = {"upsert", "insert_only", "update_only", "ignore_on_conflict", "replace"}


def _err(kind: str, message: str, field: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"type": kind, "message": message}
    if field is not None:
        out["field"] = field
    return out


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


async def read_request(request: Request, *, with_body: bool) -> CrudRequest:
    """Turn a FastAPI/Starlette request into a ``CrudRequest``."""
    headers = {k.lower(): v for k, v in request.headers.items()}
    creq = CrudRequest(
        params=dict(request.path_params),
        query=dict(request.query_params),
        headers=headers,
        request=request,
        content_type=headers.get("content-type", "").split(";")[0].strip().lower(),
    )
    if not with_body:
        return creq
    ctype = creq.content_type
    if ctype in ("multipart/form-data", "application/x-www-form-urlencoded"):
        form = await request.form()
        for key, value in form.multi_items():
            if isinstance(value, StarletteUploadFile):
                data = await value.read()
                creq.files.setdefault(key, []).append(
                    UploadedFile(filename=value.filename, content_type=value.content_type, data=data)
                )
            elif key in creq.body:
                prev = creq.body[key]
                creq.body[key] = [*prev, value] if isinstance(prev, list) else [prev, value]
            else:
                creq.body[key] = value
        return creq
    raw = await request.body()
    creq.raw_body = raw
    if not raw.strip():
        return creq
    if ctype in ("", "application/json") or ctype.endswith("+json"):
        try:
            creq.payload = json.loads(raw)
        except ValueError as exc:
            raise HTTPException(
                400, {"data": None, "success": False, "errors": [_err("json", f"Invalid JSON body: {exc}")]}
            ) from exc
        if isinstance(creq.payload, dict):
            creq.body = dict(creq.payload)
    return creq


class CrudmanService:
    """Runs CRUD actions. Get one in your own routes with ``Depends(get_crud)``."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        reg: Registry | None = None,
        resolved_deps: Mapping[tuple[str, str], Any] | None = None,
    ) -> None:
        self.session = session
        self.registry = reg or registry
        self.default_adapter = SqlAlchemyAdapter()
        self.adapter: Any = self.default_adapter
        self.resolved_deps = dict(resolved_deps or {})
        self._rollback_only = False

    # ── public API ────────────────────────────────────────────────────────

    async def list(self, section: str, request: Request | CrudRequest) -> CrudResult:
        return await self.run(section, "list", await self._as_crud_request(request, with_body=False))

    async def details(self, section: str, request: Request | CrudRequest) -> CrudResult:
        return await self.run(section, "details", await self._as_crud_request(request, with_body=False))

    async def create(self, section: str, request: Request | CrudRequest) -> CrudResult:
        return await self.run(section, "create", await self._as_crud_request(request, with_body=True))

    async def update(self, section: str, request: Request | CrudRequest) -> CrudResult:
        return await self.run(section, "update", await self._as_crud_request(request, with_body=True))

    async def save(self, section: str, request: Request | CrudRequest) -> CrudResult:
        return await self.run(section, "save", await self._as_crud_request(request, with_body=True))

    async def delete(self, section: str, request: Request | CrudRequest) -> CrudResult:
        return await self.run(section, "delete", await self._as_crud_request(request, with_body=False))

    async def bulk_import(self, section: str, request: Request | CrudRequest) -> CrudResult:
        return await self.run(section, "bulk_import", await self._as_crud_request(request, with_body=True))

    async def bulk_delete(self, section: str, request: Request | CrudRequest) -> CrudResult:
        return await self.run(section, "bulk_delete", await self._as_crud_request(request, with_body=True))

    async def call_action(
        self,
        section: str,
        action: str,
        *,
        body: Mapping[str, Any] | builtins.list[Any] | None = None,
        params: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        identity: Mapping[str, Any] | None = None,
        ctx: HookContext | None = None,
    ) -> CrudResult:
        """Run another section's action. With ``ctx`` it joins the current request's transaction."""
        creq = CrudRequest(
            params=dict(params or {}),
            query={k: str(v) for k, v in (query or {}).items()},
            body=dict(body) if isinstance(body, Mapping) else {},
            payload=body,
            headers={k.lower(): v for k, v in (headers or {}).items()},
            identity=dict(identity) if identity is not None else (dict(ctx.identity) if ctx else None),
            request=ctx.request if ctx else None,
            nested=ctx is not None,
        )
        if body is not None and not isinstance(body, Mapping):
            creq.content_type = "application/json"
        return await self.run(section, action, creq)

    # ── pipeline ──────────────────────────────────────────────────────────

    async def _as_crud_request(self, request: Request | CrudRequest, *, with_body: bool) -> CrudRequest:
        if isinstance(request, CrudRequest):
            return request
        return await read_request(request, with_body=with_body)

    @property
    def options(self) -> Any:
        return self.registry.options

    def _format(self, f: FormatInput) -> Any:
        fmt = self.options.response_formatter or default_response_formatter
        return fmt(f)

    def _error(self, action: str, status: int, errors: builtins.list[dict[str, Any]]) -> CrudResult:
        body = self._format(FormatInput(action=action, payload=None, errors=errors, success=False))  # type: ignore[arg-type]
        return CrudResult(status_code=status, body=body)

    async def _identity(self, creq: CrudRequest) -> dict[str, Any]:
        if creq.identity is not None:
            return creq.identity
        accessor = self.options.identity_accessor
        identity: Any = None
        if accessor is not None and creq.request is not None:
            identity = await maybe_await(accessor(creq.request))
        elif creq.request is not None:
            state = getattr(creq.request, "state", None)
            identity = getattr(state, "identity", None) or getattr(state, "user", None)
        if identity is None:
            identity = {}
        elif not isinstance(identity, Mapping):
            identity = {k: getattr(identity, k) for k in ("id", "role", "roles") if hasattr(identity, k)}
        creq.identity = dict(identity)
        return creq.identity

    async def run(self, section: str, action: str, creq: CrudRequest) -> CrudResult:
        entry = self.registry.get(section)
        cfg = entry.action_config(self.options.defaults, action)
        session = self.session
        previous_adapter = self.adapter
        self.adapter = cfg.orm or self.default_adapter  # per-section ORM adapter override
        try:
            try:
                result = await self._run(entry, action, cfg, creq)
            except CrudAbort as abort:
                result = abort.result if isinstance(abort.result, CrudResult) else CrudResult(response=abort.result)
                if not creq.nested:
                    await session.rollback()
                return result
            except FilterValueError as exc:
                if not creq.nested:
                    await session.rollback()
                result = self._error(action, 400, [_err("filter", str(exc), exc.field)])
            except IntegrityError:
                # A database constraint (unique column, foreign key, NOT NULL) rejected the write.
                # Nested calls re-raise so the outer request rolls back the whole transaction.
                if creq.nested:
                    raise
                await session.rollback()
                result = self._error(action, 409, [_err(
                    "conflict",
                    "The change conflicts with existing data: a unique value already exists "
                    "or a related record is missing.",
                )])
            except Exception:
                if not creq.nested:
                    await session.rollback()
                raise
            else:
                if not creq.nested:
                    if result.ok and not self._rollback_only:
                        await session.commit()
                    else:
                        await session.rollback()
        finally:
            self.adapter = previous_adapter
        self._rollback_only = False
        if self.options.throw_on_error and not result.ok and not creq.nested and result.response is None:
            raise HTTPException(status_code=result.status_code, detail=result.body)
        return result

    async def _run(self, entry: SectionEntry, action: str, cfg: ActionConfig, creq: CrudRequest) -> CrudResult:
        await self._identity(creq)
        ctx = HookContext(
            service=self, session=self.session, section=entry.name, action=action, model=entry.model,
            crud_request=creq,
        )
        await self._build_context(ctx, entry, action)

        roles = cfg.required_roles
        if roles:
            checker = self.options.role_checker or (
                lambda identity, required: not required or identity.get("role") in required
            )
            if not await maybe_await(checker(ctx.identity, roles)):
                return self._error(action, 403, [_err("forbidden", "You do not have access to this resource")])
        if cfg.ownership and self._owner_id(cfg, ctx) is None:
            return self._error(action, 403, [_err("forbidden", "Sign in to access this resource")])

        before = await call_hook(cfg.on_before_action, ctx)
        if before is False:
            return self._error(action, 403, [_err("forbidden", "Action blocked")])
        if isinstance(before, CrudResult):
            return before
        if isinstance(before, Response):
            return CrudResult(response=before)

        if cfg.custom_implementation is not None:
            out = await call_hook(cfg.custom_implementation, ctx)
            if isinstance(out, CrudResult):
                return out
            if isinstance(out, Response):
                return CrudResult(response=out)
            return CrudResult(status_code=200, body=out)

        if action == "list":
            return await self._list(entry, cfg, ctx)
        if action == "details":
            return await self._details(entry, cfg, ctx)
        if action in WRITE_ACTIONS:
            return await self._write(entry, cfg, ctx, action)
        if action == "delete":
            return await self._delete(entry, cfg, ctx)
        if action == "bulk_import":
            return await self._bulk_import(entry, cfg, ctx)
        if action == "bulk_delete":
            return await self._bulk_delete(entry, cfg, ctx)
        return self._error(action, 400, [_err("action", f"Unknown action '{action}'")])

    # ── context ───────────────────────────────────────────────────────────

    async def _build_context(self, ctx: HookContext, entry: SectionEntry, action: str) -> None:
        levels: builtins.list[Any] = []
        defaults = self.options.defaults
        if defaults is not None and "context" in defaults.model_fields_set:
            levels.append(defaults.context)
        if "context" in entry.config.model_fields_set:
            levels.append(entry.config.context)
        if entry.config.common is not None and "context" in entry.config.common.model_fields_set:
            levels.append(entry.config.common.context)
        block = getattr(entry.config, action, None)
        if isinstance(block, ActionConfig) and "context" in block.model_fields_set:
            levels.append(block.context)
        for raw in levels:
            await self._apply_context(ctx, raw)

    async def _apply_context(self, ctx: HookContext, raw: Any) -> None:
        if raw is None:
            return
        if callable(raw) and not isinstance(raw, Mapping):
            ctx.merge(await maybe_await(raw(ctx)))
            return
        if not isinstance(raw, Mapping):
            return
        resolved: dict[str, Any] = {}
        for key, value in raw.items():
            if key in ("services", "repositories"):
                if callable(value) and not isinstance(value, Mapping):
                    value = await maybe_await(value(ctx))
                group: dict[str, Any] = {}
                for name, item in (value or {}).items():
                    if isinstance(item, DependsParam):
                        group[name] = self.resolved_deps.get((key, name))
                    else:
                        group[name] = item
                resolved[key] = group
            elif key == "get_hook_context":
                continue
            elif isinstance(value, DependsParam):
                resolved[key] = self.resolved_deps.get(("extra", key))
            else:
                resolved[key] = value
        ctx.merge(resolved)
        builder = raw.get("get_hook_context")
        if callable(builder):
            ctx.merge(await maybe_await(builder(ctx)))

    # ── shared helpers ────────────────────────────────────────────────────

    def _owner_id(self, cfg: ActionConfig, ctx: HookContext) -> Any:
        own = cfg.ownership or {}
        return ctx.identity.get(own.get("identity_field", "id"))

    async def _where(self, model: Any, cfg: ActionConfig, ctx: HookContext) -> builtins.list[Any]:
        where: builtins.list[Any] = []
        cond = cfg.conditions
        if callable(cond):
            cond = await maybe_await(cond(ctx))
        if cond is not None:
            if isinstance(cond, Mapping):
                where.extend(getattr(model, k) == v for k, v in cond.items())
            elif isinstance(cond, (list, tuple)):
                where.extend(cond)
            else:
                where.append(cond)
        if cfg.ownership:
            where.append(getattr(model, cfg.ownership["field"]) == self._owner_id(cfg, ctx))
        return where

    async def _relations(self, model: Any, cfg: ActionConfig, ctx: HookContext) -> builtins.list[str]:
        spec = cfg.relations
        if cfg.get_relations is not None:
            spec = await call_hook(cfg.get_relations, ctx)
        return list(self.adapter.resolve_relations(model, spec))

    def _selection_value(self, cfg: ActionConfig, ctx: HookContext) -> Any:
        field = cfg.selection_field()
        params = ctx.params
        if field in params:
            return params[field]
        if "id" in params:
            return params["id"]
        if params:
            return next(iter(params.values()))
        return None

    def _upload_rules(self, cfg: ActionConfig) -> builtins.list[Any]:
        if not cfg.uploadable and cfg.upload is None:
            return []
        return expand_upload_config(cfg, self.options.upload_response, self.options.default_file_storage)

    def _serialize(self, obj: Any, cfg: ActionConfig) -> dict[str, Any] | None:
        return serialize(obj, cfg.read_attributes(), alias=self.options.field_alias)

    async def _finish(self, body: Any, cfg: ActionConfig, ctx: HookContext, action: str) -> Any:
        extra: dict[str, Any] = {}
        additional = cfg.additional_response
        if callable(additional):
            additional = await maybe_await(additional(body, ctx))
        if isinstance(additional, Mapping):
            extra.update(additional)
        if cfg.get_additional_response is not None:
            more = await call_hook(cfg.get_additional_response, body, ctx)
            if isinstance(more, Mapping):
                extra.update(more)
        if action in self.options.upload_response.include_base_urls_on:
            bases = base_urls(self._upload_rules(cfg), self.options.file_storages)
            if bases:
                extra["baseUrls"] = bases
        if action in ("list", "details"):
            pref = (ctx.crud_request.headers.get("x-file-url") or str(ctx.query.get("x-file-url") or "")).lower()
            if pref in ("full", "key_only"):
                extra["fileUrlMode"] = pref
        if extra and isinstance(body, dict):
            body["meta"] = {**(body.get("meta") or {}), **extra}
        if cfg.response_handler is not None:
            body = await call_hook(cfg.response_handler, body, ctx)
        after = await call_hook(cfg.on_after_action, body, ctx)
        if after is not None:
            body = after
        return body

    def _negotiate(self, action: str, body: Any, ctx: HookContext, status: int = 200) -> CrudResult:
        fmt = requested_format(ctx.crud_request.headers, ctx.query)
        if fmt not in self.options.export_content_types:
            fmt = "json"
        if fmt == "json":
            return CrudResult(status_code=status, body=body)
        data = body.get("data") if isinstance(body, Mapping) else body
        rows = data if isinstance(data, list) else ([data] if data is not None else [])
        headers = list_headers(body) if action == "list" and isinstance(body, Mapping) else {}
        if fmt == "csv":
            return CrudResult(status_code=status, content=to_csv(rows), headers=headers,
                              media_type="text/csv; charset=utf-8")
        try:
            content = to_excel(rows)
        except ImportError as exc:
            return self._error(action, 400, [_err("export", str(exc))])
        headers["Content-Disposition"] = f'attachment; filename="{ctx.section}.xlsx"'
        return CrudResult(status_code=status, content=content, headers=headers, media_type=EXCEL_MIME)

    async def _invalidate(self, section: str) -> None:
        cache = self.registry.cache
        opts = self.options.cache
        if cache is not None and opts is not None and opts.invalidate_lists_on_write:
            await cache.invalidate_section(section)

    def _cache_key(self, cfg: ActionConfig, ctx: HookContext, relations: builtins.list[str]) -> str:
        spec = cfg.enable_cache
        if isinstance(spec, Mapping) and callable(spec.get("key")):
            return f"{ctx.section}:{ctx.action}:{spec['key'](ctx)}"
        identity = ctx.identity.get("id") if (cfg.ownership or cfg.required_roles) else None
        return default_cache_key(ctx.section, ctx.action, ctx.params, ctx.query, relations, identity)

    def _cache_ttl(self, cfg: ActionConfig) -> int | None:
        spec = cfg.enable_cache
        return int(spec["ttl"]) if isinstance(spec, Mapping) and spec.get("ttl") else None

    # ── list / details ────────────────────────────────────────────────────

    async def _list(self, entry: SectionEntry, cfg: ActionConfig, ctx: HookContext) -> CrudResult:
        model = entry.model
        names = cfg.param_names()
        columns = column_keys(model)
        relations = await self._relations(model, cfg, ctx)

        cache = self.registry.cache if cfg.enable_cache else None
        key = self._cache_key(cfg, ctx, relations) if cache is not None else ""
        if cache is not None:
            hit = await cache.get(key)
            if hit is not None:
                return self._negotiate("list", hit, ctx)

        pagination = parse_pagination(ctx.query, names, (cfg.pagination or Pagination()).to_options())
        sorting = parse_sorting(ctx.query, cfg.sorting_whitelist or columns, names.sort_prefix)
        if not sorting:
            if cfg.order_by:
                sorting = [SortItem(f, "ASC" if d.upper() == "ASC" else "DESC") for f, d in cfg.order_by]
            else:
                sorting = self.adapter.default_sorting(model)
        filters = parse_filters(ctx.query, cfg.filters_whitelist or columns, names)
        kw_opts = (cfg.keyword or Keyword()).to_options()
        keyword = parse_keyword(ctx.query, names, kw_opts)

        q = ListQuery(
            filters=filters, sorting=sorting, keyword=keyword,
            keyword_paths=keyword_paths(kw_opts, columns), keyword_case_sensitive=kw_opts.is_case_sensitive,
            offset=pagination.offset, limit=pagination.limit, relations=relations,
            where=await self._where(model, cfg, ctx),
        )
        stmt = self.adapter.build_list_statement(model, q)
        hooked = await call_hook(cfg.on_before_query, stmt, ctx)
        if hooked is not None:
            stmt = hooked
        rows, total = await self.adapter.run_list(self.session, stmt, q.offset, q.limit)
        info = finalize_pagination(pagination, total, len(rows))
        data: Any = [self._serialize(r, cfg) for r in rows]
        fetched = await call_hook(cfg.on_after_fetch, data, ctx)
        if fetched is not None:
            data = fetched
        body = self._format(FormatInput(
            action="list", payload={"items": data}, pagination=info.to_dict(),
            filters=[f.to_dict() for f in filters], sorting=[s.to_dict() for s in sorting],
            request=ctx.request,
        ))
        body = await self._finish(body, cfg, ctx, "list")
        if cache is not None:
            await cache.set(key, body, self._cache_ttl(cfg))
        return self._negotiate("list", body, ctx)

    async def _details(self, entry: SectionEntry, cfg: ActionConfig, ctx: HookContext) -> CrudResult:
        model = entry.model
        relations = await self._relations(model, cfg, ctx)
        cache = self.registry.cache if cfg.enable_cache else None
        key = self._cache_key(cfg, ctx, relations) if cache is not None else ""
        if cache is not None:
            hit = await cache.get(key)
            if hit is not None:
                return self._negotiate("details", hit, ctx)
        value = self._selection_value(cfg, ctx)
        stmt = self.adapter.build_one_statement(
            model, cfg.selection_field(), value, relations, await self._where(model, cfg, ctx)
        )
        hooked = await call_hook(cfg.on_before_query, stmt, ctx)
        if hooked is not None:
            stmt = hooked
        obj = await self.adapter.run_one(self.session, stmt)
        if obj is None:
            return self._error("details", 404, [_err("notFound", "Record not found")])
        data: Any = self._serialize(obj, cfg)
        fetched = await call_hook(cfg.on_after_fetch, data, ctx)
        if fetched is not None:
            data = fetched
        body = self._format(FormatInput(action="details", payload=data, request=ctx.request))
        body = await self._finish(body, cfg, ctx, "details")
        if cache is not None:
            await cache.set(key, body, self._cache_ttl(cfg))
        return self._negotiate("details", body, ctx)

    # ── writes ────────────────────────────────────────────────────────────

    def _unalias(self, model: Any, body: Mapping[str, Any]) -> dict[str, Any]:
        if self.options.field_alias != "camel":
            return dict(body)
        keys = set(column_keys(model))
        out: dict[str, Any] = {}
        for k, v in body.items():
            snake = to_snake(k)
            out[snake if k not in keys and snake in keys else k] = v
        return out

    async def _find_existing(self, model: Any, cfg: ActionConfig, ctx: HookContext, value: Any) -> Any:
        stmt = self.adapter.build_one_statement(model, cfg.selection_field(), value, [],
                                                await self._where(model, cfg, ctx))
        return await self.adapter.run_one(self.session, stmt)

    async def _validate(
        self, model: Any, cfg: ActionConfig, ctx: HookContext, body: Mapping[str, Any], *,
        is_update: bool, existing: Any, run_hooks: bool = True,
    ) -> tuple[dict[str, Any], builtins.list[dict[str, Any]], bool]:
        """Returns (data, errors, stopped)."""
        validator = cfg.validator or PydanticValidator()
        rules: Any = validator.generate_rules(model, is_update, cfg.write_attributes())
        if cfg.ownership:
            # the owner column is filled from the identity, never from the client
            owner = cfg.ownership["field"]
            if isinstance(rules, dict):
                rules.pop(owner, None)
            body = {k: v for k, v in body.items() if k != owner}
        final = await call_hook(cfg.get_final_validation_rules, rules, ctx)
        if final is not None:
            rules = final
        if run_hooks and await call_hook(cfg.on_before_validate, rules, ctx) is False:
            return {}, [_err("validation", "Validation stopped by on_before_validate")], True
        name = f"{getattr(model, '__name__', 'Item')}{'Update' if is_update else 'Create'}"
        schema = validator.build(name, rules, is_update)
        data, errors = validator.validate(schema, body)
        fields = cfg.fields_for_uniqueness_validation or []
        if fields and not errors:
            pk = None
            values = dict(data)
            if existing is not None:
                pk = getattr(existing, primary_key_of(model))
                current = {c.key: getattr(existing, c.key) for c in columns_of(model)}
                values = {**current, **data} if cfg.condition_type_for_uniqueness_validation == "and" else values
            conflicts = await self.adapter.unique_conflicts(
                self.session, model, fields, values, cfg.condition_type_for_uniqueness_validation or "or", pk
            )
            errors.extend(_err("unique", f"{f} must be unique", f) for f in conflicts)
        return data, errors, False

    async def _write(self, entry: SectionEntry, cfg: ActionConfig, ctx: HookContext, action: str) -> CrudResult:
        model = entry.model
        field = cfg.selection_field()
        existing = None
        if action == "update":
            existing = await self._find_existing(model, cfg, ctx, self._selection_value(cfg, ctx))
            if existing is None:
                return self._error(action, 404, [_err("notFound", "Record not found")])
        elif action == "save":
            value = self._selection_value(cfg, ctx)
            if value is None:
                value = ctx.body.get(field)
            if value not in (None, ""):
                existing = await self._find_existing(model, cfg, ctx, value)
        is_update = existing is not None

        body = self._unalias(model, ctx.body)
        if is_update and action == "save":
            body.pop(field, None)
        rules = self._upload_rules(cfg)
        upload_errors: builtins.list[dict[str, Any]] = []
        replaced: builtins.list[tuple[str, str]] = []
        if rules:
            current = self._serialize(existing, cfg) if existing is not None else None
            outcome = await process_uploads(
                rules, body=body, files=ctx.files, storages=self.options.file_storages,
                global_limits=self.options.upload_limits, is_create=not is_update, existing=current,
                section=ctx.section,
            )
            upload_errors, replaced = outcome.errors, outcome.replaced_keys
        ctx.body = body

        data, errors, stopped = await self._validate(model, cfg, ctx, body, is_update=is_update, existing=existing)
        if stopped:
            return self._error(action, 400, errors)
        errors = [*upload_errors, *errors]
        if await call_hook(cfg.on_after_validate, errors, ctx) is False:
            return self._error(action, 400, errors or [_err("validation", "Validation stopped by on_after_validate")])
        if errors:
            return self._error(action, 400, errors)

        if cfg.ownership:
            data[cfg.ownership["field"]] = self._owner_id(cfg, ctx)
        if is_update:
            obj = await self.adapter.update(self.session, existing, data)
        else:
            obj = await self.adapter.create(self.session, model, data)
        relations = await self._relations(model, cfg, ctx)
        obj = await self.adapter.reload(self.session, model, obj, relations)
        for storage_name, key in replaced:
            storage = self.options.file_storages.get(storage_name)
            if storage is not None:
                await storage.delete(key)

        status = 201 if (not is_update and self.options.strict_status) else 200
        body_out = self._format(FormatInput(action=action, payload=self._serialize(obj, cfg),  # type: ignore[arg-type]
                                            request=ctx.request))
        body_out = await self._finish(body_out, cfg, ctx, action)
        await self._invalidate(ctx.section)
        return CrudResult(status_code=status, body=body_out)

    async def _delete(self, entry: SectionEntry, cfg: ActionConfig, ctx: HookContext) -> CrudResult:
        model = entry.model
        existing = await self._find_existing(model, cfg, ctx, self._selection_value(cfg, ctx))
        if existing is None:
            return self._error("delete", 404, [_err("notFound", "Record not found")])
        await self.adapter.delete(self.session, existing)
        body = self._format(FormatInput(action="delete", payload=dict(DELETE_PAYLOAD), request=ctx.request))
        body = await self._finish(body, cfg, ctx, "delete")
        await self._invalidate(ctx.section)
        return CrudResult(status_code=200, body=body)

    # ── bulk ──────────────────────────────────────────────────────────────

    def _bulk_rows(self, ctx: HookContext) -> tuple[builtins.list[dict[str, Any]], dict[str, Any]]:
        creq = ctx.crud_request
        opts: dict[str, Any] = dict(ctx.query)
        is_csv = "csv" in creq.content_type or "csv" in creq.headers.get("x-content-type", "").lower()
        if is_csv:
            text = (creq.raw_body or b"").decode("utf-8-sig")
            rows: builtins.list[dict[str, Any]] = [
                {k: v for k, v in r.items() if v != ""} for r in parse_csv(text)
            ]
            return rows, opts
        payload = creq.payload
        if isinstance(payload, Mapping):
            items = payload.get("items", payload.get("rows", payload.get("ids")))
            opts.update({k: v for k, v in payload.items() if k not in ("items", "rows", "ids")})
            payload = items
        if not isinstance(payload, list):
            return [], opts
        return [r if isinstance(r, dict) else {"id": r} for r in payload], opts

    async def _bulk_import(self, entry: SectionEntry, cfg: ActionConfig, ctx: HookContext) -> CrudResult:
        model = entry.model
        rows, opts = self._bulk_rows(ctx)
        policy = str(opts.get("policy") or "upsert")
        if policy not in BULK_POLICIES:
            return self._error("save", 400, [_err("policy", f"Unknown policy '{policy}'. Use one of "
                                                            f"{', '.join(sorted(BULK_POLICIES))}.")])
        field = str(opts.get("record_selection_field") or opts.get("recordSelectionField") or cfg.selection_field())
        dry_run = _truthy(opts.get("dry_run", opts.get("dryRun", False)))
        stop_on_error = _truthy(opts.get("stop_on_error", opts.get("stopOnError", False)))
        batch_size = int(opts.get("batch_size") or opts.get("batchSize") or 0)
        sel_cfg = cfg.model_copy(update={"record_selection_field": field})
        summary = {"inserted": 0, "updated": 0, "deleted": 0, "skipped": 0, "errorsCount": 0}
        row_errors: builtins.list[dict[str, Any]] = []

        if policy == "replace":
            stmt = self.adapter.build_list_statement(model, ListQuery(
                filters=[], sorting=[], keyword=None, keyword_paths=[], keyword_case_sensitive=False,
                offset=None, limit=None, relations=[], where=await self._where(model, cfg, ctx)))
            for obj in (await self.session.execute(stmt)).scalars().all():
                await self.session.delete(obj)
                summary["deleted"] += 1
            await self.session.flush()

        done = 0
        raw_row: dict[str, Any]
        for index, raw_row in enumerate(rows, start=1):
            row = self._unalias(model, raw_row)
            value = row.get(field)
            existing = None
            if value not in (None, "") and policy != "replace":
                existing = await self._find_existing(model, sel_cfg, ctx, value)
            if existing is not None and policy in ("insert_only",):
                row_errors.append({"row": index, "errors": [_err("exists", f"A record with {field}={value} exists",
                                                                  field)]})
            elif existing is not None and policy == "ignore_on_conflict":
                summary["skipped"] += 1
                continue
            elif existing is None and policy == "update_only":
                row_errors.append({"row": index, "errors": [_err("notFound", f"No record with {field}={value}",
                                                                  field)]})
            else:
                is_update = existing is not None
                if is_update:
                    row.pop(field, None)
                data, errors, _ = await self._validate(model, cfg, ctx, row, is_update=is_update,
                                                       existing=existing, run_hooks=False)
                if errors:
                    row_errors.append({"row": index, "errors": errors})
                else:
                    if cfg.ownership:
                        data[cfg.ownership["field"]] = self._owner_id(cfg, ctx)
                    if is_update:
                        await self.adapter.update(self.session, existing, data)
                        summary["updated"] += 1
                    else:
                        await self.adapter.create(self.session, model, data)
                        summary["inserted"] += 1
                    done += 1
                    if batch_size and not dry_run and not ctx.crud_request.nested and done % batch_size == 0:
                        await self.session.commit()
                    continue
            if stop_on_error:
                break

        summary["errorsCount"] = len(row_errors)
        if dry_run:
            self._rollback_only = True
        else:
            await self._invalidate(ctx.section)
        body = {
            "data": {**summary, "dryRun": dry_run, "policy": policy, "rowErrors": row_errors},
            "errors": [],
            "success": not row_errors,
        }
        return CrudResult(status_code=200, body=body)

    async def _bulk_delete(self, entry: SectionEntry, cfg: ActionConfig, ctx: HookContext) -> CrudResult:
        model = entry.model
        creq = ctx.crud_request
        field = cfg.selection_field()
        ids: builtins.list[Any]
        if "csv" in creq.content_type or "csv" in creq.headers.get("x-content-type", "").lower():
            text = (creq.raw_body or b"").decode("utf-8-sig")
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            if lines and lines[0] == field:
                lines = lines[1:]
            ids = [ln.split(",")[0].strip() for ln in lines]
        else:
            payload = creq.payload
            if isinstance(payload, Mapping):
                payload = payload.get("ids", [])
            ids = list(payload or []) if isinstance(payload, list) else []
        deleted, missing = 0, []
        where = await self._where(model, cfg, ctx)
        for ident in ids:
            stmt = self.adapter.build_one_statement(model, field, ident, [], where)
            obj = await self.adapter.run_one(self.session, stmt)
            if obj is None:
                missing.append(ident)
                continue
            await self.session.delete(obj)
            deleted += 1
        await self.session.flush()
        await self._invalidate(ctx.section)
        body = {"data": {"deleted": deleted, "notFound": missing}, "errors": [], "success": True}
        return CrudResult(status_code=200, body=body)

__all__ = ["CrudmanService", "read_request"]
