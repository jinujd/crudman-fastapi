# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `tests/test_e2e_readme_tour.py`: a README feature tour that mounts every documented feature in one app at the same
  time (two sections on one model, roles + cache + hooks on one section, uploads, bulk, export, custom routes and
  `call_action`), so interactions between features are covered. 15 tests; passes on SQLite and PostgreSQL.

## [0.2.0] - 2026-11-27

### Added
- **Decorator controllers (NestJS style):** `@Controller(prefix)`, `@Crud(Model, ...)` on a class, method decorators
  `@CrudList`, `@CrudDetails`, `@CrudCreate`, `@CrudUpdate`, `@CrudDelete`, `@CrudSave`, `@CrudBulkImport`,
  `@CrudBulkDelete` (place or override generated routes, optional `result: CrudResult` post-processing), and custom
  routes with `@Get`, `@Post`, `@Put`, `@Patch`, `@Delete`. Constructor injection via `Depends` in `__init__`;
  `self.crud` service; routers built lazily; `CrudmanOptions(controllers=[...])` and `include_controllers()`.
  Lowercase aliases for every decorator.
- **Per-route authentication, public by default:** `@Private()`, `@Roles(...)`, `@Public()` on controller classes,
  methods and plain FastAPI routes. `AuthOptions(dependency=..., default="public" | "private")`: any FastAPI
  dependency that returns the user; it becomes `ctx.identity`. Also `crud_router(auth=, private=, public=, roles=)`
  and section config `auth`. 401 when not signed in, 403 for a missing role; Swagger shows the lock on private routes.

### Fixed
- Custom route and plain-route wrappers resolve string annotations (`from __future__ import annotations`) in the
  user's module, so body models and injected types work.

## [0.1.1] - 2026-11-27

Security release. **Everyone using 0.1.0 should upgrade.**

### Security
- **Path traversal / arbitrary file deletion:** `LocalStorage` now refuses keys that leave its folder, and clients can no
  longer set file columns (`avatar`, `avatarKey`, …) to arbitrary values. Previously, with `delete_on_replace`, a client
  could make the server delete any file it could reach.
- **Hidden-column oracle:** filters, sorting and keyword search default to readable columns only. Previously
  `?password_hash.like=...` could reveal values hidden with `attributes.read`.
- **Related-record exposure:** related records now follow the read attributes of their own section (or global defaults).
  Previously `GET /posts/1` returned every column of `owner`, including hidden ones.
- **Cache leak between users:** cache keys now include the caller's identity. Previously results scoped by `conditions`
  or hooks could be served to another user or tenant.
- **Spreadsheet formula injection:** CSV cells starting with `=`, `+`, `-`, `@`, tab or CR are escaped; Excel cells are
  stored as text.
- **Uploads:** image presets verify file signatures; `.html`, `.svg`, `.js`, `.php` and similar extensions are rejected
  unless explicitly allowed; extensions from client filenames are sanitised.
- **Resource limits:** new `max_body_mb` (10), `max_file_mb` (25) and `max_bulk_rows` (1000) options; files are read in
  chunks and oversized requests get HTTP 413.
- **Dependencies:** minimums raised to versions without known vulnerabilities: `starlette>=1.3.1`, `fastapi>=0.136.3`,
  `pydantic>=2.9`, `python-multipart>=0.0.31` (`[uploads]`), `Pillow>=13.0.0` (`[images]`).
- CI and publish workflows run with read-only repository permissions; docs-site npm dependencies patched.

### Changed (may need action)
- **Python 3.11+ is required.** Python 3.10 reached end-of-life in October 2026, and the first Pillow release without
  known advisories (13.0) and current FastAPI releases no longer support it.
- `perPage` is capped at 100 by default (`pagination={"max_per_page": None}` removes the cap).
- `?paginate=false` / `perPage=0` are ignored unless a section sets `pagination={"is_disable_allowed": True}`.
- Filters/sorting on hidden columns need an explicit `filters_whitelist` / `sorting_whitelist` entry.
- File columns can only be changed by uploading a file (or cleared with `null`).

### Added
- `crudman.uploads.safe_key`, `sniff_image`, `UnsafeFileKey`; `crudman.export.escape_formula`.
- Security docs page.

## [0.1.0] - 2026-11-27

First release.
