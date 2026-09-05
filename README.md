# PharmacoGNN
An inductive graph neural network engine for female-stratified polypharmacy side-effect prediction making an opaque, sex-blind risk surface auditable at the point of prescribing.

## Running with Docker

```bash
cp .env.example .env   # fill in JWT_SECRET_KEY and FIELD_ENCRYPTION_KEY (generation commands are in the file)
docker compose up --build
```

This starts Postgres and the FastAPI backend (`http://localhost:8000`), running migrations automatically on startup. `backend/weights` is bind-mounted read-only, so dropping in an updated model checkpoint or graph file doesn't require a rebuild. See `backend/.env.example` instead if you're running the backend directly with `uvicorn`/`alembic` against your own Postgres, outside Docker.
