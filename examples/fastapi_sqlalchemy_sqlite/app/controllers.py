"""Companies as a decorator controller, with per-route auth."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from crudman import Controller, Crud, CrudDelete, CrudDetails, CrudList, CrudResult, Get, Private, Public, Roles

from .crud.companies import companies
from .models import Company


@Controller("/api/companies", tags=["companies"])
@Private()                                   # every route needs a signed-in user...
@Crud(Company, config=companies)
class CompaniesController:
    @Public()                                # ...except listing and viewing
    @CrudList()
    async def list(self) -> None: ...

    @Public()
    @CrudDetails()
    async def details(self, result: CrudResult) -> CrudResult:
        if result.ok:
            result.body["data"]["contactsCount"] = len(result.body["data"].get("contacts", []))
        return result

    @Roles("admin")                          # only admins delete
    @CrudDelete()
    async def remove(self) -> None: ...

    @Get("/{id}/summary")                    # custom route (signed-in users)
    async def summary(self, id: int, request: Request) -> dict[str, Any]:
        r = await self.crud.details("companies", request)
        if not r.ok:
            return r.body
        return {"name": r.body["data"]["name"], "requestedBy": request.state.identity["id"]}
