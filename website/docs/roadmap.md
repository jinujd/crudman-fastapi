---
title: Roadmap
---

# Roadmap

| Phase | Scope | Status |
| --- | --- | --- |
| 0 | Project setup: packaging, lint, type checks, CI, docs site | ✅ |
| 1 | Query parsing, response envelope, section naming | ✅ unit-tested |
| 2 | SQLAlchemy adapter: list/details/create/update/delete/save, relations, attributes, keyword, uniqueness | ⏳ |
| 3 | Validation: Pydantic models from SQLAlchemy columns, rule dicts | ⏳ |
| 4 | Routing + OpenAPI: `crud_router`, `crud.register`, decorators, `CrudController` | ⏳ |
| 5 | Hooks, context, `call_action`, error modes, transactions | ⏳ |
| 6 | Access control: roles, ownership | ⏳ |
| **0.1.0** | **first PyPI release** | |
| 7 | Cache: TTL, Redis, per-section invalidation | ⏳ |
| 8 | Uploads: presets, storage modes, Local + S3 | ⏳ |
| 9 | CSV/Excel export, bulk import/delete | ⏳ |
| 10 | Shorthand polish, example app, guides | ⏳ |
| later | Sync sessions, model specs without an ORM class, other ORMs | |
