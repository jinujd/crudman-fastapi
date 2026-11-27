# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

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
- `perPage` is capped at 100 by default (`pagination={"max_per_page": None}` removes the cap).
- `?paginate=false` / `perPage=0` are ignored unless a section sets `pagination={"is_disable_allowed": True}`.
- Filters/sorting on hidden columns need an explicit `filters_whitelist` / `sorting_whitelist` entry.
- File columns can only be changed by uploading a file (or cleared with `null`).

### Added
- `crudman.uploads.safe_key`, `sniff_image`, `UnsafeFileKey`; `crudman.export.escape_formula`.
- Security docs page.

## [0.1.0] - 2026-11-27

First release.
