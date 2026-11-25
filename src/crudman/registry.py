"""App-wide registry of options and sections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .cache import CacheAdapter, MemoryCache
from .errors import CrudmanConfigError
from .options import ActionConfig, CrudmanOptions, Section, effective_config


@dataclass
class SectionEntry:
    name: str
    model: Any
    config: Section

    def action_config(self, defaults: ActionConfig | None, action: str) -> ActionConfig:
        return effective_config(defaults, self.config, action)


class Registry:
    def __init__(self) -> None:
        self.options = CrudmanOptions()
        self.sections: dict[str, SectionEntry] = {}
        self._cache: CacheAdapter | None = None

    # options ---------------------------------------------------------------

    def set_options(self, options: CrudmanOptions) -> None:
        self.options = options
        self._cache = None
        cache_opts = options.cache
        if cache_opts and cache_opts.enabled:
            self._cache = cache_opts.backend or MemoryCache(ttl=cache_opts.ttl, max_keys=cache_opts.max_keys)

    @property
    def cache(self) -> CacheAdapter | None:
        return self._cache

    # sections --------------------------------------------------------------

    def register(self, name: str, model: Any, config: Section) -> SectionEntry:
        if config.model is not None and config.model is not model:
            raise CrudmanConfigError(
                f"Section '{name}': config.model ({getattr(config.model, '__name__', config.model)}) differs "
                f"from the model passed in ({getattr(model, '__name__', model)})."
            )
        existing = self.sections.get(name)
        if existing is not None:
            if existing.model is model and existing.config == config:
                return existing
            raise CrudmanConfigError(
                f"Section '{name}' is already registered with a different model or settings. "
                f"Pass an explicit section name, e.g. crud_router({getattr(model, '__name__', 'Model')}, "
                f"'{name}_2')."
            )
        entry = SectionEntry(name=name, model=model, config=config)
        self.sections[name] = entry
        return entry

    def get(self, name: str) -> SectionEntry:
        try:
            return self.sections[name]
        except KeyError:
            known = ", ".join(sorted(self.sections)) or "none"
            raise CrudmanConfigError(f"Unknown section '{name}'. Registered sections: {known}.") from None

    def reset(self) -> None:
        self.__init__()  # type: ignore[misc]


registry = Registry()

__all__ = ["Registry", "SectionEntry", "registry"]
