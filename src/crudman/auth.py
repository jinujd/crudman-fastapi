"""Per-route authentication: ``@Private``, ``@Public`` and ``@Roles``.

Routes are **public by default**. Mark a controller class, a controller method or any FastAPI route function with
``@Private()`` to require a signed-in user, or ``@Roles("admin")`` to also require a role. ``@Public()`` exempts a
route inside a ``@Private`` controller. The nearest decorator wins: method, then class, then section/router settings,
then ``AuthOptions.default``.

How users are authenticated is up to you: ``AuthOptions(dependency=current_user)`` takes any FastAPI dependency that
returns the user (a dict or an object with ``id`` / ``role``) or raises ``HTTPException(401)``.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, TypeVar

from fastapi import Depends, HTTPException, Request

from .context import maybe_await
from .errors import CrudmanConfigError

T = TypeVar("T")
Mode = Literal["public", "private"]

AUTH_ATTR = "__crudman_auth__"
ORIGINAL_ATTR = "__crudman_original__"


@dataclass(frozen=True)
class AuthPolicy:
    """What a decorator or setting asks for. ``mode=None`` means "not specified here"."""

    mode: Mode | None = None
    roles: tuple[str, ...] = field(default_factory=tuple)

    @property
    def specified(self) -> bool:
        return self.mode is not None or bool(self.roles)


@dataclass(frozen=True)
class ResolvedAuth:
    """The final decision for one route.

    ``private=False`` means "follow ``AuthOptions.default``": used for routes without a decorator that were built
    before ``Crudman.init`` configured auth. Their dependency is a placeholder that ``Crudman.init`` connects.
    """

    private: bool
    roles: tuple[str, ...]
    dependency: Callable[..., Any]


async def crudman_auth() -> Any:
    """Placeholder dependency. ``Crudman.init`` points it at ``AuthOptions.dependency``."""
    raise RuntimeError(
        "A route is marked @Private but no authentication is configured. "
        "Use Crudman.init(app, CrudmanOptions(auth=AuthOptions(dependency=current_user)))."
    )


async def crudman_default_auth() -> Any:
    """Placeholder for routes that follow ``AuthOptions.default`` (public until ``Crudman.init`` says otherwise)."""
    return None


def unauthorized() -> HTTPException:
    return HTTPException(401, {"data": None, "success": False, "errors": [
        {"type": "unauthorized", "message": "Sign in to access this resource"}]})


def forbidden() -> HTTPException:
    return HTTPException(403, {"data": None, "success": False, "errors": [
        {"type": "forbidden", "message": "You do not have access to this resource"}]})


def normalize_identity(value: Any) -> dict[str, Any] | None:
    """The auth dependency's return value as an identity dict (``None`` if not signed in)."""
    if value is None or value is False:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    identity = {k: getattr(value, k) for k in ("id", "role", "roles", "email", "tenant_id") if hasattr(value, k)}
    identity["user"] = value
    return identity


async def check_roles(identity: Mapping[str, Any], roles: tuple[str, ...]) -> bool:
    if not roles:
        return True
    from .registry import registry

    checker = registry.options.role_checker
    if checker is None:
        user_roles = identity.get("roles")
        if isinstance(user_roles, (list, tuple, set)):
            return bool(set(user_roles) & set(roles))
        return identity.get("role") in roles
    return bool(await maybe_await(checker(identity, list(roles))))


def current_dependency() -> Callable[..., Any]:
    """The configured auth dependency, or the placeholder (overridden by ``Crudman.init``)."""
    from .registry import registry

    auth = registry.options.auth
    if auth is not None and auth.dependency is not None:
        return auth.dependency
    return crudman_auth


def default_mode() -> Mode:
    from .registry import registry

    auth = registry.options.auth
    return auth.default if auth is not None else "public"


def resolve(*levels: AuthPolicy | None) -> ResolvedAuth | None:
    """Decide a route's auth from policies, nearest first. ``None`` means the route is public."""
    from .registry import registry

    chosen: AuthPolicy | None = next((p for p in levels if p is not None and p.specified), None)
    if chosen is None:
        if registry.options.auth is None:
            # auth not configured yet: follow whatever Crudman.init sets later
            return ResolvedAuth(private=False, roles=(), dependency=crudman_default_auth)
        chosen = AuthPolicy(mode=default_mode())
    private = chosen.mode == "private" or bool(chosen.roles)
    if not private:
        return None
    return ResolvedAuth(private=True, roles=tuple(chosen.roles), dependency=current_dependency())


async def enforce(auth: ResolvedAuth, raw: Any) -> dict[str, Any] | None:
    """Run the route's auth decision on the dependency's value. Raises 401 / 403."""
    identity = normalize_identity(raw)
    if auth.private:
        if identity is None:
            raise unauthorized()
        if not await check_roles(identity, auth.roles):
            raise forbidden()
    elif identity is None and default_mode() == "private":
        raise unauthorized()
    return identity


def policy_of(obj: Any) -> AuthPolicy | None:
    return getattr(obj, AUTH_ATTR, None)


# ── decorators ────────────────────────────────────────────────────────────────


def _mark(obj: Any, policy: AuthPolicy) -> None:
    existing = policy_of(obj)
    if existing is not None and existing.specified and existing != policy:
        name = getattr(obj, "__qualname__", repr(obj))
        raise CrudmanConfigError(
            f"{name} has conflicting auth decorators ({_describe(existing)} and {_describe(policy)}). "
            "Use one of @Public(), @Private() or @Roles(...)."
        )
    setattr(obj, AUTH_ATTR, policy)


def _describe(policy: AuthPolicy) -> str:
    if policy.roles:
        return f"@Roles({', '.join(repr(r) for r in policy.roles)})"
    return "@Public()" if policy.mode == "public" else "@Private()"


def _decorator(policy: AuthPolicy) -> Callable[[T], T]:
    def apply(obj: T) -> T:
        if inspect.isclass(obj):
            _mark(obj, policy)
            return obj
        if not callable(obj):
            raise CrudmanConfigError("Auth decorators apply to classes and functions")
        _mark(obj, policy)
        if policy.mode == "public" and not policy.roles:
            return obj
        return _guard(obj, policy)  # type: ignore[return-value]

    return apply


def Private(roles: list[str] | tuple[str, ...] | None = None) -> Callable[[T], T]:  # noqa: N802 - NestJS-style name
    """Require a signed-in user (and optionally one of ``roles``)."""
    return _decorator(AuthPolicy(mode="private", roles=tuple(roles or ())))


def Public() -> Callable[[T], T]:  # noqa: N802
    """No authentication for this route (used inside a ``@Private`` controller)."""
    return _decorator(AuthPolicy(mode="public"))


def Roles(*roles: str) -> Callable[[T], T]:  # noqa: N802
    """Require a signed-in user with one of ``roles``. Implies ``@Private()``."""
    if not roles:
        raise CrudmanConfigError("@Roles() needs at least one role")
    return _decorator(AuthPolicy(mode="private", roles=tuple(roles)))


# Lowercase aliases for people who prefer Python naming.
private = Private
public = Public
roles = Roles


def resolved_signature(fn: Callable[..., Any]) -> inspect.Signature:
    """``fn``'s signature with string annotations (``from __future__ import annotations``) evaluated in ``fn``'s own
    module. A wrapper's signature is otherwise evaluated by FastAPI in the wrapper's module, where the user's types
    don't exist."""
    try:
        return inspect.signature(fn, eval_str=True)
    except (NameError, TypeError, SyntaxError):
        return inspect.signature(fn)


def _guard(fn: Callable[..., Any], policy: AuthPolicy) -> Callable[..., Any]:
    """Wrap a plain FastAPI route function so it runs the auth dependency first.

    Controllers ignore this wrapper (they call the original method and add auth themselves), so the same decorator
    works on both.
    """
    original = getattr(fn, ORIGINAL_ATTR, fn)
    sig = resolved_signature(fn)
    params = list(sig.parameters.values())
    has_request = any(p.annotation in (Request, "Request") for p in params)
    extra = [inspect.Parameter("crudman_identity_", inspect.Parameter.KEYWORD_ONLY,
                               default=Depends(current_dependency()), annotation=Any)]
    if not has_request:
        extra.append(inspect.Parameter("crudman_request_", inspect.Parameter.KEYWORD_ONLY, annotation=Request))
    new_params = [p for p in params if p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)]
    positional = [p for p in new_params if p.kind != p.KEYWORD_ONLY]
    keyword_only = [p for p in new_params if p.kind == p.KEYWORD_ONLY]

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        raw = kwargs.pop("crudman_identity_", None)
        request: Request | None = kwargs.pop("crudman_request_", None)
        if request is None:
            request = next((v for v in [*args, *kwargs.values()] if isinstance(v, Request)), None)
        identity = normalize_identity(raw)
        if identity is None:
            raise unauthorized()
        if not await check_roles(identity, policy.roles):
            raise forbidden()
        if request is not None:
            request.state.identity = identity
        return await maybe_await(fn(*args, **kwargs))

    wrapper.__signature__ = sig.replace(parameters=[*positional, *keyword_only, *extra])  # type: ignore[attr-defined]
    setattr(wrapper, ORIGINAL_ATTR, original)
    setattr(wrapper, AUTH_ATTR, policy)
    return wrapper


__all__ = [
    "AuthPolicy",
    "Private",
    "Public",
    "ResolvedAuth",
    "Roles",
    "check_roles",
    "crudman_auth",
    "crudman_default_auth",
    "enforce",
    "normalize_identity",
    "private",
    "public",
    "resolve",
    "roles",
]
