# PharmacoGNN

**An inductive graph neural network engine for female-stratified polypharmacy side-effect prediction, making an opaque, sex-blind risk surface auditable at the point of prescribing.**

🏆 Built at **We Hack 5.0** (organized by IEEE WIE), where it won the **Best Track** award.

---

## The problem

Most drug-safety tooling is sex-blind. Many adverse drug reactions (ADRs) affect women disproportionately, yet the risk scores clinicians see rarely account for it. The gap is widest for **polypharmacy** (patients taking several drugs at once), where the dangerous signal lives in drug *combinations*, not single drugs.

## What PharmacoGNN does

- 🔬 **Pairwise and regimen risk prediction.** A heterogeneous Graph Neural Network scores **50 adverse side-effect types** for any drug pair, and for every pair across a full regimen.
- ♀️ **Female-stratified scoring.** Side effects known to disproportionately affect women are flagged and weighted when the patient's biological sex is female.
- 💊 **Safer substitution engine.** When a pair crosses the high-risk threshold, it searches for up to **3 alternative drugs** that actually reduce risk.
- 🧾 **Graph-grounded LLM explanations.** Each flagged risk gets a structured explanation for clinicians (mechanism, severity, actionable guidance) and a plain-language summary for patients, constrained not to invent mechanisms, proteins, or citations.
- 📄 **Interaction reports.** A full analysis renders to a PDF with a mandatory disclaimer banner, accessible via QR code.
- 🌐 **Interactive dashboard.** A 3D drug-interaction graph, a 3D molecule viewer (structures from PubChem), a demographic lens, a pathway inspector, and a regimen simulator.

## Built for health data

Patient data is protected health information, so the backend treats it that way:

| Concern | How it's handled |
| --- | --- |
| Authentication | JWT access tokens, bcrypt password hashing |
| Authorization | Role-based access (`CLINICIAN` / `PATIENT`) with per-patient assignment checks |
| Data at rest | Identifying fields (name, DOB, MRN, emergency contact) encrypted with **AES-256-GCM** |
| Accountability | Every read/write of patient data writes an audit-log row |
| Onboarding | Single-use, expiring email invites; passwords are never sent |
| Care handoffs | OTP-verified patient transfers between clinicians |
| Abuse protection | Rate limiting on auth and OTP endpoints |

---

## Architecture

```
┌──────────────────────────┐      REST / JSON      ┌─────────────────────────────────────┐
│  Frontend                │ ────────────────────▶ │  FastAPI backend                    │
│  HTML · CSS · JavaScript │                       │                                     │
│  Three.js force graph    │                       │  ├─ GNN inference engine (PyTorch)  │
│  3Dmol.js viewer         │ ◀──────────────────── │  ├─ Substitution search             │
└──────────────────────────┘                       │  ├─ LLM explainer (OpenRouter)      │
                                                   │  ├─ PDF + QR report generation      │
                                                   │  └─ Auth, RBAC, encryption, audit   │
                                                   └──────────────┬──────────────────────┘
                                                                  │ async SQLAlchemy
                                                         ┌────────▼────────┐
                                                         │  PostgreSQL     │
                                                         │  (Neon)         │
                                                         └─────────────────┘
```

### The model

| | |
| --- | --- |
| Architecture | Heterogeneous Graph Transformer (HGT) encoder with residual connections, plus a neural bilinear decoder (one learned embedding per side-effect relation) |
| Graph | **645 drugs** and **19,089 proteins**; protein–protein interactions, drug–protein targets, and 50 drug–drug side-effect relation types (Decagon-derived) |
| Hyperparameters | 128 hidden dims, 3 layers, 4 attention heads, 0.3 dropout |
| Female weighting | Female-weighted relations scaled by `FEMALE_ADR_RISK_MULTIPLIER` (default `1.15`), clamped at `99.9` |
| High-risk threshold | Risk score `> 75.0` triggers substitution search and LLM explanation in reports |

Drug embeddings are precomputed and cached (`z_drug_cache.pt`, fingerprinted by content hash), so inference is a fast decoder pass instead of a full message-passing run on every request.

> ⚠️ **Scores are statistical signals, not clinical fact.** PharmacoGNN is a decision-*support* research prototype and is not a substitute for professional medical judgment.

---

## Tech stack

**Backend:** Python 3.11 · FastAPI · Pydantic v2 · SQLAlchemy 2 (async) · asyncpg · Alembic · PyTorch · PyTorch Geometric · httpx · ReportLab · qrcode · slowapi · PyJWT · passlib/bcrypt · cryptography

**Frontend:** vanilla HTML/CSS/JavaScript · Three.js (3D force graph) · 3Dmol.js · Node's built-in test runner

**Infrastructure:** PostgreSQL (Neon) · Docker / Docker Compose · MailHog (dev email) · Hugging Face Spaces · GitHub Actions CI · Git LFS for model weights

---

## Project structure

```
PharmacoGNN/
├── backend/
│   ├── app/
│   │   ├── api/v1/        # auth, patients, predict, explain, reports, transfers, vocab, pubchem
│   │   ├── core/          # config, security (JWT, AES-GCM), rate limiting
│   │   ├── db/            # async engine & session
│   │   ├── models/        # SQLAlchemy models
│   │   ├── schemas/       # Pydantic request/response schemas
│   │   └── services/      # gnn_engine, substitution, llm_explainer, report_generation, ...
│   ├── alembic/           # database migrations
│   ├── weights/           # model checkpoint, graph, vocab & embedding caches (Git LFS)
│   ├── tests/             # pytest suite
│   └── Dockerfile
├── frontend/
│   ├── pages/             # workspace, patients, reports, transfers, substitution engine, ...
│   ├── js/                # api client, 3D graph, molecule viewer, page logic
│   ├── css/
│   └── tests/
├── docs/
├── docker-compose.yml
├── API_REFERENCE.md
├── FRONTEND_GUIDE.md
└── HUGGINGFACE_DEPLOYMENT.md
```

---

## Getting started

### Prerequisites

- [Git LFS](https://git-lfs.com). The model weights are stored with LFS; without it you get tiny pointer files and the engine fails to load.
- Docker and Docker Compose, **or** Python 3.11+
- A PostgreSQL database: [Neon](https://neon.tech) or a local instance
- Node.js (only to run the frontend dev server and tests)

```bash
git lfs install
git clone https://github.com/RK-NerdyBirdy/PharmacoGNN.git
cd PharmacoGNN
```

### Option A: Docker (recommended)

Docker Compose runs the backend and MailHog; the database is your Neon instance.

```bash
cp .env.example .env
```

Fill in `DATABASE_URL`, `JWT_SECRET_KEY`, and `FIELD_ENCRYPTION_KEY` (see [Configuration](#configuration)), then:

```bash
docker compose up --build
```

- API: http://localhost:8000 (interactive docs at http://localhost:8000/docs)
- MailHog inbox (invite links, OTP codes): http://localhost:8025

Migrations run automatically on startup. `backend/weights` is bind-mounted read-only, so you can swap in a new checkpoint without rebuilding.

### Option B: Run the backend directly

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install --index-url https://download.pytorch.org/whl/cpu torch
pip install -r requirements.txt
cp .env.example .env               # set DATABASE_URL etc.
alembic upgrade head
uvicorn app.main:app --reload
```

For Neon, set `DATABASE_SSL_REQUIRE=true`; leave it `false` for a local Postgres.

### Run the frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend is served at http://localhost:8420 and talks to the API at `http://localhost:8000` by default (override with `window.PHARMAGNN_API_BASE`). Add the frontend origin to the backend's CORS list:

```env
CORS_ORIGINS=http://localhost:8420
APP_BASE_URL=http://localhost:8420
```

---

## Configuration

| Variable | Required | Description |
| --- | :---: | --- |
| `DATABASE_URL` | ✅ | Postgres DSN using the asyncpg scheme, e.g. `postgresql+asyncpg://user:pass@host/db` (drop any `?sslmode=` suffix) |
| `DATABASE_SSL_REQUIRE` | | `true` for Neon / managed Postgres |
| `JWT_SECRET_KEY` | ✅ | Long random secret for signing tokens |
| `FIELD_ENCRYPTION_KEY` | ✅ | Base64 32-byte AES key: `python -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"` |
| `OPENROUTER_API_KEY` | | Enables LLM explanations. Without it, `/explain` returns `502` and reports skip explanations; everything else still works |
| `OPENROUTER_MODEL` | | Defaults to `anthropic/claude-3.5-sonnet` |
| `CORS_ORIGINS` | | Comma-separated allowed browser origins |
| `APP_BASE_URL` | | Frontend origin used in invite and QR links |
| `RATE_LIMIT_ENABLED` | | `true` by default |
| `EMAIL_BACKEND` | | `smtp`, `memory`, or `console` |
| `SMTP_HOST` / `SMTP_PORT` / ... | | Mail settings (defaults target MailHog) |

See [`.env.example`](.env.example) (Docker) and [`backend/.env.example`](backend/.env.example) (bare metal) for the full list.

---

## API overview

| Area | Endpoints |
| --- | --- |
| Auth | `POST /api/v1/auth/register`, `/login`, `/refresh`, `/activate` |
| Patients | CRUD, conditions, regimens, prescriptions, invites: `/api/v1/patients/...` |
| Prediction | `POST /api/v1/predict/pairwise`, `/predict/regimen`, `/predict/substitute` |
| Explanation | `POST /api/v1/explain/interaction` |
| Reports | `POST /api/v1/patients/{id}/reports`, `GET /api/v1/reports/{id}`, `GET /api/v1/reports/{id}/pdf` |
| Transfers | OTP-verified patient transfers: `/api/v1/transfers/...` |
| Vocabulary | `GET /api/v1/vocab/drugs`, `/vocab/adverse-effects` |
| Health | `GET /health` |

Quick example:

```bash
curl -X POST http://localhost:8000/api/v1/predict/pairwise \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"drug_a_cid": "...", "drug_b_cid": "...", "patient_sex": "FEMALE"}'
```

📘 Full request/response shapes, error codes and RBAC rules: **[API_REFERENCE.md](API_REFERENCE.md)**
🧭 Frontend integration notes: **[FRONTEND_GUIDE.md](FRONTEND_GUIDE.md)**

---

## Testing

```bash
# Backend (needs a reachable Postgres via DATABASE_URL)
cd backend
pytest -v

# Frontend
cd frontend
npm test
```

GitHub Actions runs the backend suite against Postgres 16 on every push and pull request ([`backend-ci.yml`](.github/workflows/backend-ci.yml)).

## Deployment

The backend deploys as a Docker Space on Hugging Face with a Neon database. Step-by-step guide: **[HUGGINGFACE_DEPLOYMENT.md](HUGGINGFACE_DEPLOYMENT.md)**.

---

## Made with ❤️ by

| | Name | GitHub |
| :---: | --- | --- |
| <img src="https://github.com/RK-NerdyBirdy.png" width="60" alt="Maneet Gupta"> | **Maneet Gupta** | [@RK-NerdyBirdy](https://github.com/RK-NerdyBirdy) |
| <img src="https://github.com/Vani-06.png" width="60" alt="Vani Singh"> | **Vani Singh** | [@Vani-06](https://github.com/Vani-06) |
| <img src="https://github.com/shriyapsawant21-wq.png" width="60" alt="Shriya Sawant"> | **Shriya Sawant** | [@shriyapsawant21-wq](https://github.com/shriyapsawant21-wq) |
| <img src="https://github.com/Prakhar-Sethi012.png" width="60" alt="Prakhar Sethi"> | **Prakhar Sethi** | [@Prakhar-Sethi012](https://github.com/Prakhar-Sethi012) |

## License

Released under the [MIT License](LICENSE).
