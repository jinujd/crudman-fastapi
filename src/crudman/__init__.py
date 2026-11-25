"""crudman-fastapi: zero-boilerplate CRUD for FastAPI.

Pre-release. Implemented so far: query parsing, response envelopes and section naming.
See https://github.com/jinujd/crudman-fastapi for the roadmap.
"""

from .errors import CrudmanConfigError, CrudmanError
from .naming import (
    apply_path_style,
    default_path,
    normalize_path,
    resolve_path,
    section_name_for,
    table_name_of,
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

__version__ = "0.0.1"

__all__ = [
    "DELETE_PAYLOAD",
    "CrudmanConfigError",
    "CrudmanError",
    "FilterItem",
    "FormatInput",
    "KeywordOptions",
    "PaginationInfo",
    "PaginationOptions",
    "PaginationResult",
    "QueryParamNames",
    "SortItem",
    "__version__",
    "apply_path_style",
    "default_path",
    "default_response_formatter",
    "empty_pagination",
    "error_body",
    "finalize_pagination",
    "keyword_paths",
    "normalize_path",
    "parse_filters",
    "parse_keyword",
    "parse_pagination",
    "parse_sorting",
    "resolve_path",
    "section_name_for",
    "table_name_of",
]
