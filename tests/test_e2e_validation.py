"""Validation generated from the model, rule overrides and uniqueness checks."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from crudman import WriteAction, crud_router, generate_rules

from .conftest import Env
from .models import Company, Post, User


def test_generated_rules_for_create_and_update() -> None:
    create = generate_rules(Company, is_update=False)
    assert create["name"] == {"type": "string", "max": 150, "optional": False, "min": 1}
    assert create["email"]["optional"] is True and create["email"]["nullable"] is True
    assert create["is_active"]["optional"] is True  # has a default
    assert create["plan"]["type"] == "enum" and create["plan"]["values"] == ["free", "pro"]
    assert create["founded_on"] == {"type": "date", "dateOnly": True, "optional": True, "nullable": True}
    assert "id" not in create and "created_at" not in create
    update = generate_rules(Company, is_update=True)
    assert all(rule["optional"] for rule in update.values())
    assert generate_rules(Company, False, {"include": ["name", "email"]}).keys() == {"name", "email"}


async def test_required_types_and_lengths(env: Env) -> None:
    env.app_with(crud_router(Company))
    async with env.client() as c:
        r = await c.post("/companies", json={"name": "", "employees": "many", "plan": "gold", "extra": 1})
    assert r.status_code == 400
    errors = {e["field"]: e["type"] for e in r.json()["errors"]}
    assert errors == {"name": "stringMin", "employees": "number", "plan": "enumValue", "extra": "forbidden"}
    async with env.client() as c:
        r = await c.post("/companies", json={"name": "x" * 151})
    assert r.json()["errors"][0]["type"] == "stringMax"


async def test_update_drops_unknown_fields_and_allows_partial(env: Env) -> None:
    env.app_with(crud_router(Company))
    async with env.client() as c:
        cid = (await c.post("/companies", json={"name": "A"})).json()["data"]["id"]
        r = await c.patch(f"/companies/{cid}", json={"employees": 5, "unknown": True, "id": 999})
    assert r.status_code == 200
    assert r.json()["data"]["employees"] == 5 and r.json()["data"]["id"] == cid


async def test_explicit_null_on_non_nullable_is_rejected(env: Env) -> None:
    env.app_with(crud_router(Company))
    async with env.client() as c:
        cid = (await c.post("/companies", json={"name": "A"})).json()["data"]["id"]
        r = await c.patch(f"/companies/{cid}", json={"name": None})
    assert r.status_code == 400


async def test_form_encoded_values_are_coerced(env: Env) -> None:
    env.app_with(crud_router(Company))
    async with env.client() as c:
        r = await c.post("/companies", data={"name": "Form Co", "is_active": "false", "employees": "12",
                                             "founded_on": "2020-02-02"})
    data = r.json()["data"]
    assert (data["is_active"], data["employees"], data["founded_on"]) == (False, 12, "2020-02-02")


async def test_write_attributes(env: Env) -> None:
    env.app_with(crud_router(Company, config={"attributes": {"write": {"exclude": ["secret"]}}}))
    async with env.client() as c:
        r = await c.post("/companies", json={"name": "A", "secret": "s"})
    assert r.status_code == 400 and r.json()["errors"][0]["field"] == "secret"


async def test_final_rules_as_dict(env: Env) -> None:
    def final(rules: dict[str, Any], ctx: Any) -> dict[str, Any]:
        return {**rules, "name": {"type": "string", "min": 3, "max": 10},
                "employees": {"type": "number", "integer": True, "min": 1}, "email": {"type": "email"}}

    env.app_with(crud_router(Company, config={"create": {"get_final_validation_rules": final}}))
    async with env.client() as c:
        r = await c.post("/companies", json={"name": "ab", "employees": 0, "email": "nope"})
        assert {e["field"] for e in r.json()["errors"]} == {"name", "employees", "email"}
        r = await c.post("/companies", json={"name": "abc", "employees": 1, "email": "a@b.co"})
        assert r.status_code == 200


async def test_final_rules_as_pydantic_model(env: Env) -> None:
    class CompanyIn(BaseModel):
        name: str = Field(min_length=2)
        employees: int = Field(ge=1)

    env.app_with(crud_router(Company, config={"create": {"get_final_validation_rules": lambda r, c: CompanyIn}}))
    async with env.client() as c:
        r = await c.post("/companies", json={"name": "Acme"})
        assert r.status_code == 400 and r.json()["errors"][0] == {
            "type": "required", "field": "employees", "message": "The 'employees' field is required."}
        assert (await c.post("/companies", json={"name": "Acme", "employees": 3})).status_code == 200


async def test_before_and_after_validate_hooks(env: Env) -> None:
    def after(errors: list[dict[str, Any]], ctx: Any) -> None:
        if ctx.body.get("name") == "forbidden":
            errors.append({"type": "custom", "field": "name", "message": "Name not allowed"})

    env.app_with(
        crud_router(Company, config={"create": {"on_after_validate": after}}),
        crud_router(Company, "locked", {"on_before_validate": lambda rules, ctx: False}),
    )
    async with env.client() as c:
        r = await c.post("/companies", json={"name": "forbidden"})
        assert r.status_code == 400 and r.json()["errors"][0]["type"] == "custom"
        assert (await c.post("/companies", json={"name": "fine"})).status_code == 200
        r = await c.post("/locked", json={"name": "fine"})
        assert r.status_code == 400 and "on_before_validate" in r.json()["errors"][0]["message"]


async def test_uniqueness_or(env: Env) -> None:
    env.app_with(crud_router(User, config={"create": {"fields_for_uniqueness_validation": ["email", "phone"]},
                                           "update": WriteAction(fields_for_uniqueness_validation=["email", "phone"])}))
    async with env.client() as c:
        a = (await c.post("/users", json={"name": "A", "email": "a@x.io", "phone": "1"})).json()["data"]
        b = (await c.post("/users", json={"name": "B", "email": "b@x.io", "phone": "2"})).json()["data"]
        r = await c.post("/users", json={"name": "C", "email": "a@x.io", "phone": "3"})
        assert r.status_code == 400
        assert r.json()["errors"] == [{"type": "unique", "message": "email must be unique", "field": "email"}]
        # keeping your own values is fine; PATCH without the field does not trigger a false error
        assert (await c.patch(f"/users/{a['id']}", json={"email": "a@x.io"})).status_code == 200
        assert (await c.patch(f"/users/{a['id']}", json={"name": "A2"})).status_code == 200
        r = await c.patch(f"/users/{b['id']}", json={"phone": "1"})
        assert r.status_code == 400 and r.json()["errors"][0]["field"] == "phone"


async def test_uniqueness_and(env: Env) -> None:
    rule = {"fields_for_uniqueness_validation": ["tenant_id", "slug"],
            "condition_type_for_uniqueness_validation": "and"}
    env.app_with(crud_router(Post, config={"create": rule, "update": rule}))
    async with env.client() as c:
        await c.post("/posts", json={"slug": "a", "title": "t", "tenant_id": 1})
        other = (await c.post("/posts", json={"slug": "b", "title": "t", "tenant_id": 1})).json()["data"]
        # slug "a" is unique in the DB too, so test the pair rule with a different tenant first
        assert (await c.patch(f"/posts/{other['id']}", json={"tenant_id": 2})).status_code == 200
        r = await c.patch(f"/posts/{other['id']}", json={"tenant_id": 1, "slug": "a"})
        assert r.status_code == 400
        assert {e["field"] for e in r.json()["errors"]} == {"tenant_id", "slug"}


async def test_uniqueness_set_at_section_level(env: Env) -> None:
    env.app_with(crud_router(User, config={"fields_for_uniqueness_validation": ["email"]}))
    async with env.client() as c:
        await c.post("/users", json={"name": "A", "email": "a@x.io"})
        assert (await c.post("/users", json={"name": "B", "email": "a@x.io"})).status_code == 400


async def test_custom_validator_adapter(env: Env) -> None:
    class UpperValidator:
        """Minimal validator adapter: names must be upper case."""

        def generate_rules(self, model: Any, is_update: bool, write_attributes: Any) -> dict[str, Any]:
            return {"name": "required"}

        def build(self, name: str, rules: Any, is_update: bool) -> Any:
            return rules

        def validate(self, schema: Any, data: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
            value = str(data.get("name", ""))
            if not value.isupper():
                return {}, [{"type": "upper", "field": "name", "message": "Name must be upper case"}]
            return {"name": value}, []

    env.app_with(crud_router(Company, config={"validator": UpperValidator()}))
    async with env.client() as c:
        assert (await c.post("/companies", json={"name": "acme"})).json()["errors"][0]["type"] == "upper"
        assert (await c.post("/companies", json={"name": "ACME"})).json()["data"]["name"] == "ACME"
