from crudman import DetailsAction, HookContext, Keyword, ListAction, Pagination, Section, WriteAction

from ..models import AuditLog, Company


async def audit(result: dict, ctx: HookContext) -> None:
    tenant = ctx.request.headers.get("x-tenant") if ctx.request else None
    await ctx.repositories["audit"].add(type=f"COMPANY_{ctx.action.upper()}", notes=tenant)


companies = Section(
    title="Company",
    description="Companies CRUD",
    attributes={"read": {"exclude": ["secret"]}},
    context={"repositories": {"audit": AuditLog}},
    list=ListAction(
        filters_whitelist=["name", "is_active", "created_at", "revenue"],
        keyword=Keyword(searchable_fields=["name", "contacts.email"]),
        pagination=Pagination(max_per_page=100),
        additional_response={"source": "crudman-fastapi example"},
    ),
    details=DetailsAction(relations=["contacts"]),
    create=WriteAction(fields_for_uniqueness_validation=["name"], on_after_action=audit),
    update=WriteAction(fields_for_uniqueness_validation=["name"], on_after_action=audit),
)

__all__ = ["Company", "companies"]
