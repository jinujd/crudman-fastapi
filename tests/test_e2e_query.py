"""List querying on SQLite: filters, keyword, sorting, pagination, relations and attributes."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Select

from crudman import ListAction, crud_router

from .conftest import Env
from .models import Address, Company, Contact, Country, Plan, State


async def seed_companies(env: Env) -> None:
    hq = Address(city="Kochi")
    await env.add(
        Company(name="Acme Air", email="air@acme.test", is_active=True, revenue=Decimal("100.50"), employees=10,
                founded_on=date(2020, 1, 10), plan=Plan.pro, created_at=datetime(2024, 1, 5), tenant_id=1,
                contacts=[Contact(email="ceo@acme.test", address=hq)]),
        Company(name="Beta Bikes", email="hello@beta.test", is_active=False, revenue=Decimal("20"), employees=3,
                founded_on=date(2021, 6, 1), created_at=datetime(2024, 3, 1), tenant_id=2),
        Company(name="Gamma Airlines", email=None, is_active=True, revenue=Decimal("999"), employees=250,
                founded_on=date(2019, 12, 31), created_at=datetime(2024, 12, 31, 18, 0), tenant_id=1,
                contacts=[Contact(email="ops@gamma.test", address=Address(city="Mumbai"))]),
    )


def names(body: dict) -> list[str]:
    return [row["name"] for row in body["data"]]


async def test_default_sort_is_newest_first(env: Env) -> None:
    await seed_companies(env)
    env.app_with(crud_router(Company))
    async with env.client() as c:
        body = (await c.get("/companies")).json()
    assert names(body) == ["Gamma Airlines", "Beta Bikes", "Acme Air"]
    assert body["sorting"] == [{"field": "created_at", "order": "DESC"}, {"field": "id", "order": "DESC"}]


async def test_equality_like_and_bool_filters(env: Env) -> None:
    await seed_companies(env)
    env.app_with(crud_router(Company))
    async with env.client() as c:
        assert names((await c.get("/companies?is_active=false")).json()) == ["Beta Bikes"]
        assert names((await c.get("/companies?name.like=AIR&sort.name=asc")).json()) == ["Acme Air", "Gamma Airlines"]
        assert names((await c.get("/companies?plan=pro")).json()) == ["Acme Air"]
        body = (await c.get("/companies?name.like=air&is_active=true")).json()
        assert body["filters"] == [
            {"field": "name", "op": "like", "value": "air", "param": "name.like"},
            {"field": "is_active", "op": "eq", "value": "true", "param": "is_active"},
        ]


async def test_like_escapes_wildcards(env: Env) -> None:
    await seed_companies(env)
    env.app_with(crud_router(Company))
    async with env.client() as c:
        assert names((await c.get("/companies?name.like=%25")).json()) == []


async def test_numeric_and_decimal_ranges(env: Env) -> None:
    await seed_companies(env)
    env.app_with(crud_router(Company))
    async with env.client() as c:
        assert names((await c.get("/companies?employees.min=10&sort.employees=asc")).json()) == [
            "Acme Air", "Gamma Airlines"]
        assert names((await c.get("/companies?employees.gt=10")).json()) == ["Gamma Airlines"]
        assert names((await c.get("/companies?employees.lt=10")).json()) == ["Beta Bikes"]
        assert names((await c.get("/companies?revenue.max=100.5&sort.revenue=asc")).json()) == [
            "Beta Bikes", "Acme Air"]
        assert names((await c.get("/companies?employees.between=3,10&sort.employees=asc")).json()) == [
            "Beta Bikes", "Acme Air"]


async def test_date_ranges_work(env: Env) -> None:
    await seed_companies(env)
    env.app_with(crud_router(Company))
    async with env.client() as c:
        # end date is inclusive for the whole day (Gamma was created at 18:00 on Dec 31)
        r = await c.get("/companies?created_at.between=2024-03-01,2024-12-31&sort.created_at=asc")
        assert names(r.json()) == ["Beta Bikes", "Gamma Airlines"]
        assert names((await c.get("/companies?createdAt.min=2024-03-01&sort.name=asc")).json()) == [
            "Beta Bikes", "Gamma Airlines"]
        assert names((await c.get("/companies?founded_on.max=2020-01-10&sort.name=asc")).json()) == [
            "Acme Air", "Gamma Airlines"]


async def test_bad_filter_value_is_400(env: Env) -> None:
    env.app_with(crud_router(Company))
    async with env.client() as c:
        r = await c.get("/companies?employees.min=lots")
    assert r.status_code == 400
    assert r.json()["errors"][0]["type"] == "filter"
    assert r.json()["errors"][0]["field"] == "employees"


async def test_filter_and_sort_whitelists(env: Env) -> None:
    await seed_companies(env)
    env.app_with(crud_router(Company, config={"list": {"filters_whitelist": ["name"], "sorting_whitelist": ["name"]}}))
    async with env.client() as c:
        body = (await c.get("/companies?is_active=false&sort.employees=asc")).json()
    assert len(body["data"]) == 3  # is_active ignored
    assert body["filters"] == []
    assert body["sorting"][0]["field"] == "created_at"  # sort.employees ignored → default


async def test_order_by_setting(env: Env) -> None:
    await seed_companies(env)
    env.app_with(crud_router(Company, config={"list": {"order_by": [("name", "ASC")]}}))
    async with env.client() as c:
        assert names((await c.get("/companies")).json()) == ["Acme Air", "Beta Bikes", "Gamma Airlines"]


async def test_multi_sort_camel_case(env: Env) -> None:
    await seed_companies(env)
    env.app_with(crud_router(Company))
    async with env.client() as c:
        body = (await c.get("/companies?sort.isActive=desc&sort.name=desc")).json()
    assert names(body) == ["Gamma Airlines", "Acme Air", "Beta Bikes"]


async def test_pagination(env: Env) -> None:
    await env.add(*[Country(name=f"C{i:02d}") for i in range(1, 26)])
    pagination = {"max_per_page": 20, "is_disable_allowed": True}
    env.app_with(crud_router(Country, config={"list": {"pagination": pagination}}))
    async with env.client() as c:
        body = (await c.get("/countries?page=2&perPage=10&sort.name=asc")).json()
        assert [r["name"] for r in body["data"]] == [f"C{i:02d}" for i in range(11, 21)]
        assert body["pagination"] == {"page": 2, "perPage": 10, "totalItemsCount": 25, "totalPagesCount": 3,
                                      "isHavingNextPage": True, "isHavingPreviousPage": True}
        body = (await c.get("/countries?per_page=100")).json()
        assert body["pagination"]["perPage"] == 20 and len(body["data"]) == 20
        body = (await c.get("/countries?paginate=false")).json()
        assert len(body["data"]) == 25
        assert body["pagination"]["totalPagesCount"] == 1 and body["pagination"]["perPage"] == 25


async def test_keyword_search_root_and_relations(env: Env) -> None:
    await seed_companies(env)
    env.app_with(crud_router(Company, config={"list": {"keyword": {
        "searchable_fields": ["name", "contacts.email", "contacts.address.city"], "max_relation_depth": 2}}}))
    async with env.client() as c:
        assert names((await c.get("/companies?keyword=bikes")).json()) == ["Beta Bikes"]
        assert names((await c.get("/companies?keyword=ops@gamma")).json()) == ["Gamma Airlines"]
        assert names((await c.get("/companies?keyword=kochi")).json()) == ["Acme Air"]
        assert names((await c.get("/companies?keyword=a")).json()) == names(
            (await c.get("/companies")).json())  # below min_length → ignored


async def test_keyword_is_anded_with_filters(env: Env) -> None:
    # crudman-nestjs combined these with OR; here both must match.
    await seed_companies(env)
    env.app_with(crud_router(Company))
    async with env.client() as c:
        assert names((await c.get("/companies?keyword=air&is_active=false")).json()) == []
        assert names((await c.get("/companies?keyword=air&tenant_id=1&sort.name=asc")).json()) == [
            "Acme Air", "Gamma Airlines"]


async def test_keyword_default_searches_root_columns(env: Env) -> None:
    await seed_companies(env)
    env.app_with(crud_router(Company))
    async with env.client() as c:
        assert names((await c.get("/companies?keyword=hello@beta")).json()) == ["Beta Bikes"]
        assert names((await c.get("/companies?keyword=250")).json()) == ["Gamma Airlines"]


async def test_renamed_query_params(env: Env) -> None:
    await seed_companies(env)
    env.app_with(crud_router(Company, config={"list": {"query_param_names": {
        "page": "p", "per_page": "pp", "keyword": "q", "sort_prefix": "order.", "like_op": "contains"}}}))
    async with env.client() as c:
        body = (await c.get("/companies?q=air&order.name=asc&pp=1&p=2")).json()
        assert names(body) == ["Gamma Airlines"]
        assert names((await c.get("/companies?name.contains=bike")).json()) == ["Beta Bikes"]


async def test_conditions_and_on_before_query(env: Env) -> None:
    await seed_companies(env)

    def only_active(stmt: Select, ctx: object) -> Select:
        return stmt.where(Company.is_active.is_(True))

    env.app_with(
        crud_router(Company, "tenant_one", {"conditions": {"tenant_id": 1}}),
        crud_router(Company, "active", {"list": {"on_before_query": only_active}}),
        crud_router(Company, "dynamic", {"conditions": lambda ctx: [Company.employees > int(ctx.query.get("min", 0))]}),
    )
    async with env.client() as c:
        assert sorted(names((await c.get("/tenant_one")).json())) == ["Acme Air", "Gamma Airlines"]
        assert sorted(names((await c.get("/active")).json())) == ["Acme Air", "Gamma Airlines"]
        assert names((await c.get("/dynamic?min=100")).json()) == ["Gamma Airlines"]
        # conditions also guard details/update/delete
        beta = (await c.get("/dynamic?min=0&name=Beta Bikes")).json()["data"][0]["id"]
        assert (await c.get(f"/tenant_one/{beta}")).status_code == 404
        assert (await c.delete(f"/tenant_one/{beta}")).status_code == 404


async def test_relations_settings(env: Env) -> None:
    await env.add(Country(name="India", states=[State(name="Kerala")]))
    env.app_with(
        crud_router(State),
        crud_router(Country, "bare", {"relations": []}),
        crud_router(Country, "nested", {"relations": ["states.country"]}),
        crud_router(Country, "dynamic",
                    {"get_relations": lambda ctx: ["states"] if ctx.query.get("withStates") else []}),
    )
    async with env.client() as c:
        state = (await c.get("/states")).json()["data"][0]
        assert state["country"]["name"] == "India"
        assert "states" not in (await c.get("/bare")).json()["data"][0]
        nested = (await c.get("/nested/1")).json()["data"]
        assert nested["states"][0]["name"] == "Kerala"
        assert "states" not in (await c.get("/dynamic")).json()["data"][0]
        assert (await c.get("/dynamic?withStates=1")).json()["data"][0]["states"][0]["name"] == "Kerala"


async def test_read_attributes(env: Env) -> None:
    await seed_companies(env)
    env.app_with(
        crud_router(Company, config={"relations": [], "attributes": {"read": {"exclude": ["secret", "tenant_id"]}}}),
        crud_router(Company, "slim", {"relations": [], "list": ListAction(attributes=["id", "name"])}),
    )
    async with env.client() as c:
        row = (await c.get("/companies")).json()["data"][0]
        assert "secret" not in row and "tenant_id" not in row and "name" in row
        assert set((await c.get("/slim")).json()["data"][0]) == {"id", "name"}
        assert "email" in (await c.get("/slim/1")).json()["data"]  # list-only setting


async def test_camel_case_field_alias(env: Env) -> None:
    await seed_companies(env)
    env.app_with(crud_router(Company, config={"relations": []}), field_alias="camel")
    async with env.client() as c:
        row = (await c.get("/companies?isActive=false")).json()["data"][0]
        assert row["isActive"] is False and "createdAt" in row and "is_active" not in row
        created = (await c.post("/companies", json={"name": "Delta", "isActive": False})).json()
        assert created["data"]["isActive"] is False
