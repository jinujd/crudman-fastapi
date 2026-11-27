"""Configuration models: sections, per-action settings and global options.

Settings resolve in three layers, the later one winning::

    CrudmanOptions.defaults  →  section top-level keys (and ``common``)  →  section.<action>

Every model accepts snake_case keys and, for people porting from crudman-nestjs, camelCase keys
(``filtersWhitelist``). Unknown keys are rejected, so typos fail at startup.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from .errors import CrudmanConfigError
from .query import KeywordOptions, PaginationOptions, QueryParamNames

ActionName = Literal["list", "details", "create", "update", "save", "delete", "bulk_import", "bulk_delete"]
ACTIONS: tuple[str, ...] = ("list", "details", "create", "update", "save", "delete")
DEFAULT_ACTIONS: tuple[str, ...] = ("list", "details", "create", "update", "delete")
ALL_ACTIONS: tuple[str, ...] = (*ACTIONS, "bulk_import", "bulk_delete")

_MODEL_CONFIG = ConfigDict(
    extra="forbid",
    alias_generator=to_camel,
    populate_by_name=True,
    arbitrary_types_allowed=True,
)


def _default_sources() -> list[Literal["multipart", "base64"]]:
    return ["multipart", "base64"]


def _default_body_types() -> list[Literal["json", "form", "multipart"]]:
    return ["json", "form", "multipart"]


def _default_export_types() -> list[Literal["json", "csv", "excel"]]:
    return ["json", "csv", "excel"]


class _Base(BaseModel):
    model_config = _MODEL_CONFIG


class Keyword(_Base):
    """Keyword search settings for list."""

    is_enabled: bool = True
    is_case_sensitive: bool = False
    min_length: int = 2
    searchable_fields: list[str] = Field(default_factory=list)
    max_relation_depth: Literal[1, 2, 3] = 1

    def to_options(self) -> KeywordOptions:
        return KeywordOptions(
            is_enabled=self.is_enabled,
            is_case_sensitive=self.is_case_sensitive,
            min_length=self.min_length,
            searchable_fields=tuple(self.searchable_fields),
            max_relation_depth=self.max_relation_depth,
        )


class Pagination(_Base):
    """Pagination behaviour for list."""

    is_pagination_enabled: bool = True
    is_disable_allowed: bool = False  # True honours ?paginate=false / perPage=0 (returns the whole table)
    is_default_enabled: bool = True
    max_per_page: int | None = 100  # None removes the cap
    default_per_page: int = 30

    def to_options(self) -> PaginationOptions:
        return PaginationOptions(
            is_pagination_enabled=self.is_pagination_enabled,
            is_disable_allowed=self.is_disable_allowed,
            is_default_enabled=self.is_default_enabled,
            max_per_page=self.max_per_page,
            default_per_page=self.default_per_page,
        )


class UploadMap(_Base):
    """One upload rule: where a file comes from and where it is stored."""

    source_field: str
    target_field: str | dict[str, str] | None = None
    storage_mode: Literal["filename", "filename_in_field", "base64", "blob"] = "filename_in_field"
    storage: str | None = None
    is_array: bool = False
    type_hint: str | None = None
    validators: dict[str, Any] = Field(default_factory=dict)
    sources: list[Literal["multipart", "base64"]] = Field(default_factory=_default_sources)
    delete_on_replace: bool = False
    mode: Literal["replace", "append"] = "replace"
    key_pattern: Callable[..., str] | None = None


class UploadConfig(_Base):
    sources: list[Literal["multipart", "base64"]] = Field(default_factory=_default_sources)
    map: list[UploadMap] = Field(default_factory=list)


class ActionConfig(_Base):
    """Settings that may appear at section level or inside an action block."""

    relations: Any = None
    get_relations: Callable[..., Any] | None = None
    attributes: Any = None
    filters_whitelist: list[str] | None = None
    sorting_whitelist: list[str] | None = None
    order_by: list[tuple[str, Literal["ASC", "DESC", "asc", "desc"]]] | None = None
    conditions: Any = None
    keyword: Keyword | None = None
    keyword_param_name: str | None = None
    query_param_names: dict[str, str] | None = None
    pagination: Pagination | None = None
    record_selection_field: str | None = None
    fields_for_uniqueness_validation: list[str] | None = None
    condition_type_for_uniqueness_validation: Literal["or", "and"] | None = None
    required_roles: list[str] | None = None
    ownership: dict[str, str] | None = None

    on_before_action: Callable[..., Any] | None = None
    on_before_query: Callable[..., Any] | None = None
    on_after_fetch: Callable[..., Any] | None = None
    on_before_validate: Callable[..., Any] | None = None
    get_final_validation_rules: Callable[..., Any] | None = None
    on_after_validate: Callable[..., Any] | None = None
    on_after_action: Callable[..., Any] | None = None

    context: Any = None
    additional_response: Any = None
    get_additional_response: Callable[..., Any] | None = None
    response_handler: Callable[..., Any] | None = None
    custom_implementation: Callable[..., Any] | None = None
    enable_cache: bool | dict[str, Any] | None = None

    uploadable: dict[str, str] | None = None
    upload: UploadConfig | None = None
    upload_defaults: dict[str, Any] | None = None

    session: Callable[..., Any] | None = None
    validator: Any = None
    orm: Any = None

    @field_validator("keyword", mode="before")
    @classmethod
    def _keyword_bool(cls, value: Any) -> Any:
        if value is True:
            return {}
        if value is False:
            return {"is_enabled": False}
        return value

    @field_validator("query_param_names")
    @classmethod
    def _check_param_names(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is not None:
            QueryParamNames.from_mapping(value)  # raises on unknown keys
        return value

    # ── derived helpers ────────────────────────────────────────────────────

    def param_names(self) -> QueryParamNames:
        names = dict(self.query_param_names or {})
        if self.keyword_param_name and "keyword" not in names:
            names["keyword"] = self.keyword_param_name
        return QueryParamNames.from_mapping(names)

    def selection_field(self) -> str:
        return self.record_selection_field or "id"

    def read_attributes(self) -> Any:
        attrs = self.attributes
        if isinstance(attrs, Mapping) and ("read" in attrs or "write" in attrs):
            return attrs.get("read", "*")
        return attrs if attrs is not None else "*"

    def write_attributes(self) -> Any:
        attrs = self.attributes
        if isinstance(attrs, Mapping) and ("read" in attrs or "write" in attrs):
            return attrs.get("write", "*")
        return "*"


# Readable aliases for action blocks; they all accept the same keys.
class ListAction(ActionConfig):
    pass


class DetailsAction(ActionConfig):
    pass


class WriteAction(ActionConfig):
    pass


class DeleteAction(ActionConfig):
    pass


class Section(ActionConfig):
    """A CRUD resource: a model plus settings."""

    model: Any = None
    title: str | None = None
    description: str | None = None
    openapi: dict[str, Any] | None = None
    common: ActionConfig | None = None
    list: ActionConfig | None = None
    details: ActionConfig | None = None
    create: ActionConfig | None = None
    update: ActionConfig | None = None
    save: ActionConfig | None = None
    delete: ActionConfig | None = None
    bulk_import: ActionConfig | None = None
    bulk_delete: ActionConfig | None = None


class CacheOptions(_Base):
    enabled: bool = False
    ttl: int = 60
    max_keys: int = 10_000
    invalidate_lists_on_write: bool = True
    backend: Any = None


class UploadResponseOptions(_Base):
    file_field_mode: Literal["filename_in_field", "key_url_fields"] = "filename_in_field"
    include_base_urls_on: list[str] = Field(default_factory=lambda: ["list", "details"])


class OpenApiOptions(_Base):
    enabled: bool = True
    request_body_content_types: list[Literal["json", "form", "multipart"]] = Field(
        default_factory=_default_body_types
    )


class CrudmanOptions(_Base):
    """Global options, passed to ``Crudman.init``."""

    session_dependency: Callable[..., Any] | None = None
    update_method: Literal["patch", "put"] = "patch"
    throw_on_error: bool = False
    strict_status: bool = False
    defaults: ActionConfig | None = None
    cache: CacheOptions | None = None
    identity_accessor: Callable[..., Any] | None = None
    role_checker: Callable[..., Any] | None = None
    response_formatter: Callable[..., Any] | None = None
    export_content_types: list[Literal["json", "csv", "excel"]] = Field(default_factory=_default_export_types)
    default_file_storage: str | None = None
    file_storages: dict[str, Any] = Field(default_factory=dict)
    upload_limits: dict[str, Any] = Field(default_factory=dict)
    upload_response: UploadResponseOptions = Field(default_factory=UploadResponseOptions)
    max_body_mb: float = 10  # JSON / CSV / form bodies; larger requests get 413
    max_file_mb: float = 25  # each uploaded file, before upload presets apply
    max_bulk_rows: int = 1000  # rows per bulk import / ids per bulk delete
    route_prefix: str | None = None
    path_style: Literal["as_is", "kebab", "snake", "camel", "pascal"] | None = None
    field_alias: Literal["camel"] | None = None
    openapi: OpenApiOptions = Field(default_factory=OpenApiOptions)


# ── coercion and merging ──────────────────────────────────────────────────────


def to_section(config: Section | ActionConfig | Mapping[str, Any] | None) -> Section:
    """Accept a ``Section``, a plain dict or ``None``."""
    if config is None:
        return Section()
    if isinstance(config, Section):
        return config
    if isinstance(config, ActionConfig):
        return Section.model_validate(config.model_dump(exclude_unset=True))
    if isinstance(config, Mapping):
        try:
            return Section.model_validate(dict(config))
        except Exception as exc:
            raise CrudmanConfigError(f"Invalid section config: {exc}") from exc
    raise CrudmanConfigError(f"Section config must be a Section or dict, got {type(config).__name__}")


_SECTION_ONLY = {"model", "title", "description", "openapi", "common", *ALL_ACTIONS}


def _layer(cfg: BaseModel | None, skip: set[str] | None = None) -> dict[str, Any]:
    if cfg is None:
        return {}
    out: dict[str, Any] = {}
    for name in cfg.model_fields_set:
        if skip and name in skip:
            continue
        out[name] = getattr(cfg, name)
    return out


def effective_config(defaults: ActionConfig | None, section: Section, action: str) -> ActionConfig:
    """Merge the three layers into the settings for one action."""
    merged: dict[str, Any] = {}
    merged.update(_layer(defaults))
    merged.update(_layer(section, skip=_SECTION_ONLY))
    merged.update(_layer(section.common))
    if action == "save":
        # save behaves like create/update unless it has its own block
        merged.update(_layer(section.create))
    if action in ("bulk_import",):
        merged.update(_layer(section.create))
    if action in ("bulk_delete",):
        merged.update(_layer(section.delete))
    merged.update(_layer(getattr(section, action, None)))
    return ActionConfig.model_construct(_fields_set=set(merged), **merged)


__all__ = [
    "ACTIONS",
    "ALL_ACTIONS",
    "DEFAULT_ACTIONS",
    "ActionConfig",
    "CacheOptions",
    "CrudmanOptions",
    "DeleteAction",
    "DetailsAction",
    "Keyword",
    "ListAction",
    "OpenApiOptions",
    "Pagination",
    "Section",
    "UploadConfig",
    "UploadMap",
    "UploadResponseOptions",
    "WriteAction",
    "effective_config",
    "to_section",
]
