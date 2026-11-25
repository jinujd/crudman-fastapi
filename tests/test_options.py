"""Settings layering and config validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from crudman import ActionConfig, CrudmanConfigError, ListAction, Section
from crudman.options import effective_config, to_section


def test_three_layers_later_wins() -> None:
    defaults = ActionConfig(filters_whitelist=["a"], record_selection_field="id", required_roles=["user"])
    section = Section(filters_whitelist=["b"], required_roles=["admin"], list=ListAction(filters_whitelist=["c"]))
    list_cfg = effective_config(defaults, section, "list")
    details_cfg = effective_config(defaults, section, "details")
    assert list_cfg.filters_whitelist == ["c"]
    assert details_cfg.filters_whitelist == ["b"]
    assert list_cfg.required_roles == ["admin"] and list_cfg.record_selection_field == "id"


def test_common_alias_and_save_inherits_create() -> None:
    section = to_section({"common": {"required_roles": ["x"]}, "create": {"fields_for_uniqueness_validation": ["n"]}})
    assert effective_config(None, section, "update").required_roles == ["x"]
    assert effective_config(None, section, "save").fields_for_uniqueness_validation == ["n"]


def test_camel_case_keys_are_accepted() -> None:
    section = to_section({"list": {"filtersWhitelist": ["name"], "keyword": {"searchableFields": ["name"]}},
                          "recordSelectionField": "slug"})
    cfg = effective_config(None, section, "list")
    assert cfg.filters_whitelist == ["name"] and cfg.keyword is not None
    assert cfg.keyword.searchable_fields == ["name"] and cfg.selection_field() == "slug"


def test_unknown_keys_are_rejected() -> None:
    with pytest.raises(CrudmanConfigError):
        to_section({"filter_whitelist": ["x"]})
    with pytest.raises(ValidationError):
        Section(list=ListAction(query_param_names={"pageSize": "ps"}))


def test_attributes_read_write_split() -> None:
    cfg = ActionConfig(attributes={"read": {"exclude": ["secret"]}, "write": ["name"]})
    assert cfg.read_attributes() == {"exclude": ["secret"]} and cfg.write_attributes() == ["name"]
    plain = ActionConfig(attributes=["id", "name"])
    assert plain.read_attributes() == ["id", "name"] and plain.write_attributes() == "*"


def test_keyword_bool_shorthand() -> None:
    assert ActionConfig(keyword=False).keyword.is_enabled is False  # type: ignore[union-attr]
    assert ActionConfig(keyword=True).keyword.is_enabled is True  # type: ignore[union-attr]


def test_param_names_include_keyword_param_name() -> None:
    assert ActionConfig(keyword_param_name="q").param_names().keyword == "q"
