---
title: Roadmap
---

# Roadmap

| Phase | Scope | Status |
| --- | --- | --- |
| 0 | Project setup: packaging, lint, type checks, CI, docs site | ✅ |
| 1 | Query parsing, response envelope, section naming, config models | ✅ |
| 2 | SQLAlchemy adapter: list/details/create/update/delete/save, relations, attributes, keyword, uniqueness | ✅ |
| 3 | Validation: Pydantic models from SQLAlchemy columns, rule dicts | ✅ |
| 4 | Routing + OpenAPI: `crud_router`, `crud.register`, decorators, `CrudController` | ✅ |
| 5 | Hooks, context, `call_action`, error modes, transactions | ✅ |
| 6 | Access control: roles, ownership | ✅ |
| 7 | Cache: TTL, per-section invalidation | ✅ (Redis adapter built, not tested against a live server) |
| 8 | Uploads: presets, storage modes, local disk | ✅ (S3 storage built, not tested against S3) |
| 9 | CSV/Excel export, bulk import/delete | ✅ |
| 10 | Example app, guides | ✅ |
| **0.1.0** | **first PyPI release** | next |
| later | Sync sessions, model specs without an ORM class, other ORMs, `video-short` checks, per-row CSV results for bulk import | |
