"""crudman-fastapi: zero-boilerplate CRUD for FastAPI and SQLAlchemy.

    from crudman import Crudman, CrudmanOptions, crud_router

    Crudman.init(app, CrudmanOptions(session_dependency=get_session))
    app.include_router(crud_router(Company))
"""

from .adapters.sqlalchemy import FilterValueError, SqlAlchemyAdapter
from .cache import CacheAdapter, MemoryCache, RedisCache
from .context import CrudAbort, CrudRequest, CrudResult, HookContext, Repository, UploadedFile
from .errors import CrudmanConfigError, CrudmanError
from .naming import (
    apply_path_style,
    default_path,
    normalize_path,
    resolve_path,
    section_name_for,
    table_name_of,
)
from .options import (
    ActionConfig,
    CacheOptions,
    CrudmanOptions,
    DeleteAction,
    DetailsAction,
    Keyword,
    ListAction,
    OpenApiOptions,
    Pagination,
    Section,
    UploadConfig,
    UploadMap,
    UploadResponseOptions,
    WriteAction,
)
from .query import (
    FilterItem,
    KeywordOptions,
    PaginationInfo,
    PaginationOptions,
    PaginationResult,
    QueryParamNames,
    SortItem,
    finalize_pagination,
    keyword_paths,
    parse_filters,
    parse_keyword,
    parse_pagination,
    parse_sorting,
)
from .response import (
    DELETE_PAYLOAD,
    FormatInput,
    default_response_formatter,
    empty_pagination,
    error_body,
)
from .routing import CrudController, Crudman, crud, crud_router, crudman_session, get_crud
from .schemas import PydanticValidator, generate_rules, rules_to_model, serialize
from .service import CrudmanService
from .uploads import PRESETS, LocalStorage, S3Storage

__version__ = "0.1.0"

__all__ = [
    "DELETE_PAYLOAD",
    "PRESETS",
    "ActionConfig",
    "CacheAdapter",
    "CacheOptions",
    "CrudAbort",
    "CrudController",
    "CrudRequest",
    "CrudResult",
    "Crudman",
    "CrudmanConfigError",
    "CrudmanError",
    "CrudmanOptions",
    "CrudmanService",
    "DeleteAction",
    "DetailsAction",
    "FilterItem",
    "FilterValueError",
    "FormatInput",
    "HookContext",
    "Keyword",
    "KeywordOptions",
    "ListAction",
    "LocalStorage",
    "MemoryCache",
    "OpenApiOptions",
    "Pagination",
    "PaginationInfo",
    "PaginationOptions",
    "PaginationResult",
    "PydanticValidator",
    "QueryParamNames",
    "RedisCache",
    "Repository",
    "S3Storage",
    "Section",
    "SortItem",
    "SqlAlchemyAdapter",
    "UploadConfig",
    "UploadMap",
    "UploadResponseOptions",
    "UploadedFile",
    "WriteAction",
    "__version__",
    "apply_path_style",
    "crud",
    "crud_router",
    "crudman_session",
    "default_path",
    "default_response_formatter",
    "empty_pagination",
    "error_body",
    "finalize_pagination",
    "generate_rules",
    "get_crud",
    "keyword_paths",
    "normalize_path",
    "parse_filters",
    "parse_keyword",
    "parse_pagination",
    "parse_sorting",
    "resolve_path",
    "rules_to_model",
    "section_name_for",
    "serialize",
    "table_name_of",
]
