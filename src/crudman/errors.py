"""Exceptions raised by crudman."""

from __future__ import annotations


class CrudmanError(Exception):
    """Base class for all crudman errors."""


class CrudmanConfigError(CrudmanError):
    """A section, router or option is configured incorrectly. Raised at startup, not per request."""
