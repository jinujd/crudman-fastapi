---
title: Security
---

# Security

crudman-fastapi 0.1.1 fixed several issues found in a security review of 0.1.0. **Upgrade if you use 0.1.0.**
This page lists the protections and the settings that affect them.

## What crudman does for you

| Area | Protection |
| --- | --- |
| SQL | Values are always bound parameters; field names are checked against the model's columns; LIKE wildcards are escaped. |
| Hidden fields | Columns hidden with `attributes.read` cannot be filtered, sorted or keyword-searched unless you list them explicitly in a whitelist. |
| Related records | Records loaded through relations follow the read attributes of their own section (or `CrudmanOptions.defaults`), so a field hidden on `users` stays hidden in `posts.owner`. When a model has several sections, the most restrictive one wins. |
| Cache | Cache keys include the caller's identity, so per-user or per-tenant results are never shared. |
| Uploads | Storage keys can never leave the storage folder (`..`, absolute paths and backslashes are rejected, and deletes outside the folder are ignored). File columns can only change through an upload: clients may send back the current value or `null`, nothing else. Image presets check the file's real content, not just the claimed MIME type. Executable or HTML-like extensions (`.html`, `.svg`, `.js`, `.php`, …) are rejected unless a rule lists them in `allowed_extensions`. |
| Exports | Cells starting with `=`, `+`, `-`, `@`, tab or carriage return are escaped in CSV and stored as plain text in Excel, so they never run as formulas. |
| Size limits | `max_body_mb` (10), `max_file_mb` (25) and `max_bulk_rows` (1000) in `CrudmanOptions`; larger requests get HTTP 413. |
| Page size | `perPage` is capped at 100 and `?paginate=false` is ignored unless a section sets `is_disable_allowed=True`. |
| Database errors | Constraint violations roll back and return 409 without exposing SQL. |

## Things you still need to decide

- **Writable fields.** By default every column except the primary key and timestamps can be written by clients. Restrict
  sensitive columns such as `role`, `is_admin` or `tenant_id`:

  ```python
  crud_router(User, config={"attributes": {"write": {"exclude": ["role", "is_admin"]}}})
  # or set ownership={"field": "tenant_id"} so crudman fills it from the identity
  ```

- **Authentication.** Routes are public by default. Configure `AuthOptions(dependency=current_user)` and mark
  routes with `@Private()` / `@Roles(...)` (or `crud_router(auth="private")`), or use
  `AuthOptions(..., default="private")` so everything is protected unless marked `@Public()`. See
  [Authentication](./authentication.md). Use `ownership` for per-row access.
- **Serving uploads.** Serve uploaded files from a separate domain or with `Content-Disposition: attachment` if users
  can upload documents.

## Reporting a vulnerability

Please open a private security advisory on [GitHub](https://github.com/jinujd/crudman-fastapi/security/advisories/new)
instead of a public issue.
