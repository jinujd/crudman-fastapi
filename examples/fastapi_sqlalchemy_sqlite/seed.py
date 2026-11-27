"""Fill the example database with sample data: python seed.py"""

import asyncio

from app.db import DATABASE_URL, SessionLocal, engine
from app.models import Base, Company, Contact, Country, State, Tag, User


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as session:
        session.add_all([
            Country(name="India", code="IN", states=[State(name="Kerala"), State(name="Goa")]),
            Country(name="Japan", code="JP", states=[State(name="Tokyo")]),
            Company(name="Acme Air", email="air@acme.test", revenue=1200, secret="s1",
                    contacts=[Contact(email="ceo@acme.test")]),
            Company(name="Beta Bikes", email="hello@beta.test", is_active=False, revenue=300),
            Company(name="Gamma Airlines", revenue=9000, contacts=[Contact(email="ops@gamma.test")]),
            User(name="Alice", email="alice@example.test", phone="111"),
            User(name="Bob", email="bob@example.test"),
            Tag(name="new"), Tag(name="featured"),
        ])
        await session.commit()
    await engine.dispose()
    print(f"Seeded {DATABASE_URL}")


if __name__ == "__main__":
    asyncio.run(main())
