---
title: Caching
---

# Caching

```python
CrudmanOptions(cache=CacheOptions(enabled=True, ttl=60, invalidate_lists_on_write=True))

Section(
    list=ListAction(enable_cache={"ttl": 30}),
    details=DetailsAction(enable_cache=True),
)
```

- The default cache is an in-process TTL cache (`MemoryCache`). To share it between workers, install the
  `redis` extra and pass `CacheOptions(enabled=True, backend=RedisCache(url="redis://..."))`. The Redis
  adapter is not yet tested against a live server.
- Default key: section, action, path params, query, relations and the caller's identity (so per-user and
  per-tenant results are never shared). Override with
  `enable_cache={"key": lambda ctx: ...}`.
- A cache hit goes through the same output step as a fresh result, so `meta` and export formats are
  consistent.
- Writes invalidate only the written section's entries (crudman-nestjs flushes the whole cache).
