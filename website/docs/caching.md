---
title: Caching
---

# Caching

:::info Planned (phase 7)
:::

```python
CrudmanOptions(cache=CacheOptions(enabled=True, ttl=60, invalidate_lists_on_write=True))

Section(
    list=ListAction(enable_cache={"ttl": 30}),
    details=DetailsAction(enable_cache=True),
)
```

- The default cache is an in-process TTL cache. Install the `redis` extra and pass
  `cache=RedisCache(url=...)` to share it between workers.
- Default key: section, action, path params, query and relations. Override with
  `enable_cache={"key": lambda ctx: ...}`.
- A cache hit goes through the same output step as a fresh result, so `meta` and export formats are
  consistent.
- Writes invalidate only the written section's entries (crudman-nestjs flushes the whole cache).
