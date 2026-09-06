# PharmacoGNN
An inductive graph neural network engine for female-stratified polypharmacy side-effect prediction making an opaque, sex-blind risk surface auditable at the point of prescribing.

## Running with Docker

The database is [Neon](https://neon.tech) (managed Postgres) — Docker Compose no longer runs a local Postgres container.

```bash
cp .env.example .env   # fill in DATABASE_URL (your Neon connection string), JWT_SECRET_KEY, FIELD_ENCRYPTION_KEY
docker compose up --build
```

This starts the FastAPI backend (`http://localhost:8000`), running migrations against Neon automatically on startup. `backend/weights` is bind-mounted read-only, so dropping in an updated model checkpoint, graph file, or `z_drug_cache.pt` doesn't require a rebuild. See `backend/.env.example` instead if you're running the backend directly with `uvicorn`/`alembic` outside Docker (against Neon or a local Postgres — see `DATABASE_SSL_REQUIRE` there).
