# Example: FastAPI + SQLAlchemy + SQLite

A runnable app that uses most crudman features. It mirrors `examples/nest-typeorm-sqlite` in crudman-nestjs.

```bash
cd examples/fastapi_sqlalchemy_sqlite
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python seed.py                    # optional sample data
uvicorn app.main:app --reload     # http://localhost:8000/docs
```

It uses `./example.db` (SQLite) by default. Any SQLAlchemy async URL works, for example PostgreSQL:

```bash
pip install asyncpg
createdb crudman_example
DATABASE_URL=postgresql+asyncpg://localhost/crudman_example python seed.py
DATABASE_URL=postgresql+asyncpg://localhost/crudman_example uvicorn app.main:app --reload
```

Auth in this example uses **demo tokens** (`Authorization: Bearer <role>:<id>`, see `app/auth.py`). Never use them
in production.

Try it:

```bash
curl 'localhost:8000/api/companies?keyword=air&sort.name=asc'
curl 'localhost:8000/api/companies?is_active=true&revenue.min=1000'
curl -H 'x-content-type: csv' localhost:8000/api/countries
curl -X POST localhost:8000/api/companies -H 'content-type: application/json' -d '{"name": "Delta"}'   # 401
curl -X POST localhost:8000/api/companies -H 'authorization: Bearer user:1' \
  -H 'content-type: application/json' -d '{"name": "Delta"}'                                          # 200
curl -X DELETE localhost:8000/api/companies/4 -H 'authorization: Bearer user:1'                        # 403
curl -X DELETE localhost:8000/api/companies/4 -H 'authorization: Bearer admin:2'                       # 200
curl -X POST localhost:8000/api/profiles -F name=Ann -F avatar=@me.png
curl -X POST localhost:8000/api/custom/countries/1/states -H 'content-type: application/json' -d '{"name": "Goa"}'
curl -X POST 'localhost:8000/api/countries/bulk/import?policy=upsert' -H 'content-type: application/json' \
  -d '[{"name": "Nepal"}, {"id": 1, "name": "Bharat"}]'
```

| Path | Shows |
| --- | --- |
| `/api/countries` | defaults, save, bulk import/delete |
| `/api/states` | relations, list cache |
| `/api/companies` | decorator controller with `@Private` / `@Public` / `@Roles`, a custom route, section file, keyword over relations, uniqueness, hooks |
| `/api/users` | `crud_router(..., private=[...])`, whitelists, uniqueness on two fields |
| `/api/profiles` | image uploads served from `/uploads` |
| `/api/shorthand/tags`, `/api/shorthand/categories` | several models in one router |
| `/api/custom/...` | decorators and `call_action` in your own routes |
