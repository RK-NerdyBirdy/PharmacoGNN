# Deploying the PharmacoGNN Backend to Hugging Face Spaces

A detailed, repo-specific guide for deploying `backend/` as a **Docker Space** on Hugging Face. This assumes you've already read [README.md](README.md) and [API_REFERENCE.md](API_REFERENCE.md), and that you have a Neon Postgres database ready (see the "Running with Docker" section of the README for the Neon connection string format).

This is written from what's actually in this repo today — exact file sizes, exact env vars, exact Dockerfile behavior — not a generic HF Spaces tutorial. Where something depends on HF's own current UI/limits (which change independently of this repo), that's called out explicitly so you can double-check against [HF's own docs](https://huggingface.co/docs/hub/spaces) if it doesn't match what you see.

---

## 1. Why this needs a bit of restructuring, not just a push

Two things about this repo don't match a Docker Space's default expectations out of the box:

1. **HF Spaces (Docker SDK) looks for a `Dockerfile` at the *root* of the Space's repository.** Ours lives at `backend/Dockerfile` with build context `backend/`, because `backend/` is a subdirectory of this monorepo. Pushing the whole monorepo as-is won't build.
2. **Three of the model artifacts in `backend/weights/` are too large for plain git** and need Git LFS:

   | File | Size |
   |---|---|
   | `graph_edge_index.pt` | ~37.3 MB |
   | `pharmacognn_deep_state_dict.pth` | ~17.0 MB |
   | `z_protein.pt` | ~9.3 MB |

   (Everything else in `weights/` is under 400 KB and needs no special handling — including `z_drug_cache.pt`, which matters a lot here; see step 6.)

Both are solved by treating the **Space as its own repository containing only `backend/`'s contents at its root**, with LFS tracking set up for the `.pt`/`.pth` files. That's what this guide walks through. Your GitHub monorepo (`main`/`Changes_Prakhar`/etc.) is untouched — this is an additional, separate git remote pointed at Hugging Face.

---

## 2. Prerequisites

- A Hugging Face account: https://huggingface.co/join
- `git` and **Git LFS** installed locally:
  ```bash
  git lfs install
  ```
  (One-time per machine. If `git lfs` isn't found, install it first — https://git-lfs.com.)
- A Hugging Face access token with **write** access: https://huggingface.co/settings/tokens
- Your Neon `DATABASE_URL` (the same format documented in the root `.env.example` — asyncpg scheme, no `?sslmode=` suffix).
- A generated `FIELD_ENCRYPTION_KEY` and `JWT_SECRET_KEY` — reuse the ones from your existing `.env` if this is meant to be the same running instance and data (re-encrypting existing PHI rows with a *different* key than what created them will make them permanently undecryptable), or generate fresh ones for a new deployment:
  ```bash
  python -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"  # FIELD_ENCRYPTION_KEY
  python -c "import secrets; print(secrets.token_urlsafe(48))"                              # JWT_SECRET_KEY
  ```

---

## 3. Create the Space

1. Go to https://huggingface.co/new-space.
2. Pick an owner (your account or an org), a Space name (e.g. `pharmacognn-backend`), and a license.
3. **SDK: Docker.** Pick the blank "Docker" template (not one of the pre-built Gradio/Streamlit-flavored Docker templates).
4. **Hardware:** the free `CPU basic` tier is enough to start — this model is small (645 drugs, 128-dim embeddings, ~18 MB checkpoint) and, thanks to `z_drug_cache.pt` (see step 6), doesn't need to run the encoder at boot. Upgrade later only if you see out-of-memory errors during the `pip install torch` build step.
5. **Visibility:** Private, unless you specifically want this API publicly reachable — this backend handles PHI-adjacent data and has no reason to be public by default.
6. Click **Create Space**. HF gives you a git remote URL like `https://huggingface.co/spaces/<owner>/<space-name>`.

---

## 4. Build a deployment repo from `backend/`

Do this from a **fresh local clone**, separate from your normal working copy, so you don't disturb your GitHub-tracked history:

```bash
# From anywhere outside your existing PharmacoGNN working copy:
git clone https://huggingface.co/spaces/<owner>/<space-name> pharmacognn-space
cd pharmacognn-space

# Copy backend/'s contents (not the backend/ folder itself) to the Space repo's root.
# Adjust the source path to wherever your PharmacoGNN checkout actually is.
cp -r /path/to/PharmacoGNN/backend/. .

# Remove backend/'s own venv/caches if you copied them by accident -- they
# shouldn't be committed regardless of which repo they're in.
rm -rf .venv __pycache__ .pytest_cache
find . -name "__pycache__" -exec rm -rf {} +
```

You should now have, at the root of `pharmacognn-space/`: `Dockerfile`, `docker-entrypoint.sh`, `.dockerignore`, `requirements.txt`, `alembic.ini`, `alembic/`, `app/`, `tests/`, `pytest.ini`, `weights/`, and `.env.example`.

### Set up Git LFS for the large weight files

```bash
git lfs track "*.pt" "*.pth"
git add .gitattributes
```

This tracks `graph_edge_index.pt`, `z_drug_cache.pt`, `z_protein.pt` (all `.pt`) and `pharmacognn_deep_state_dict.pth` (`.pth`) via LFS. The small `.json` files in `weights/` are unaffected and commit normally.

### Add the Space-specific `README.md` frontmatter

HF Spaces reads a YAML block at the very top of the Space's `README.md` to configure it. **This repo's own `README.md` (the one you copied in from `backend/` — actually, note `backend/` doesn't have its own README, so you're creating this fresh) needs this block added, or HF won't know how to run the Space:**

```markdown
---
title: PharmacoGNN Backend
emoji: 💊
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 8000
pinned: false
---

# PharmacoGNN Backend

FastAPI backend for polypharmacy risk stratification. See the main repo's
API_REFERENCE.md for the full API contract. This Space is API-only — there
is no UI at `/`; use `/docs` for interactive Swagger UI, or `/health`.
```

`app_port: 8000` is the important line — it tells HF's proxy to forward to port 8000 (what our Dockerfile's `uvicorn` already binds to and `EXPOSE`s), instead of the Docker Spaces default of 7860. **This means the existing Dockerfile needs zero changes** — no port remapping, no new entrypoint logic.

(One more compatibility note worth knowing, not something you need to act on: HF's Docker Spaces documentation recommends containers run as a non-root user with UID 1000. This Dockerfile already does exactly that — `useradd --create-home --uid 1000 appuser` — for unrelated security reasons from earlier in this project. That happens to already match what HF expects.)

Commit everything:

```bash
git add .
git commit -m "Initial Space deployment from backend/"
```

---

## 5. Configure secrets and variables

**Do not commit a `.env` file to the Space.** Set these in the Space's **Settings → Variables and secrets** tab instead (this is exactly what `.env` would otherwise supply — see root `.env.example` / `backend/.env.example` for the full reference on each of these).

**As Secrets** (encrypted, never shown in build logs):

| Name | Value |
|---|---|
| `DATABASE_URL` | Your Neon connection string, asyncpg scheme, e.g. `postgresql+asyncpg://user:password@ep-xxxx.neon.tech/pharmacognn` |
| `JWT_SECRET_KEY` | Generated above |
| `FIELD_ENCRYPTION_KEY` | Generated above (or reused — see the warning in step 2) |
| `OPENROUTER_API_KEY` | Only if you want `/api/v1/explain/interaction` to work; leave unset otherwise (it degrades to a clean `502`, not a crash) |

**As Variables** (plain, non-sensitive config):

| Name | Value |
|---|---|
| `DATABASE_SSL_REQUIRE` | `true` (Neon requires TLS; see `app/core/config.py`) |
| `CORS_ORIGINS` | Your deployed frontend's origin(s), comma-separated — **not** `http://localhost:3000` once this is live |
| `RATE_LIMIT_ENABLED` | `true` |
| `OPENROUTER_MODEL` | `anthropic/claude-3.5-sonnet` (or whatever you're using) |

You do **not** need to set `WEIGHTS_DIR`, `MODEL_STATE_DICT_FILENAME`, `Z_DRUG_CACHE_FILENAME`, or any of the other artifact-path settings in `app/core/config.py` — their defaults already match what's baked into the image via the Dockerfile's `COPY weights ./weights`.

---

## 6. Push and watch it build

```bash
git push
```

Open the Space's page — it switches to a **Building** tab showing live Docker build logs. Watch for:

- The `pip install --index-url https://download.pytorch.org/whl/cpu torch` step — this is the slow part locally (a 196 MB download); on HF's own infrastructure it's typically much faster than it was in local development for this project, but give it a few minutes.
- After the image is built, the container starts and runs `docker-entrypoint.sh`, which runs `alembic upgrade head` against your Neon `DATABASE_URL` before starting uvicorn. **Watch this step specifically** — if `DATABASE_URL`/`DATABASE_SSL_REQUIRE` are wrong, this is where it'll fail loudly (not silently).
- Then: `INFO: Application startup complete.` — this should appear **within a few seconds**, not 25 minutes. That's the payoff of `z_drug_cache.pt` being baked into the image and fingerprinted by content hash (not mtime) — a fresh Space build is, from the app's perspective, exactly the same situation as the `git checkout` scenario this caching mechanism was specifically hardened against. If you instead see `PharmacoGNN: no valid z_drug_cache.pt found -- running the 3-layer HGTConv encoder now`, the cache didn't survive the copy/LFS/build pipeline intact (see Troubleshooting below) — the Space will still work, just very slowly on that first boot.

Once it says **Running** with a green dot, hit the Space's URL directly:

```bash
curl https://<owner>-<space-name>.hf.space/health
```

Expect: `{"status":"ok","gnn_ready":true,"gnn_degraded_mode":false}`. `gnn_degraded_mode: false` confirms the real graph-aware embeddings loaded, not the fallback.

Then a real end-to-end check (mirrors the curl walkthrough in API_REFERENCE.md, just against the Space's URL instead of `localhost:8000`):

```bash
BASE=https://<owner>-<space-name>.hf.space

curl -s -X POST $BASE/api/v1/auth/register -H "Content-Type: application/json" \
  -d '{"email":"doc@example.com","password":"supersecret1","role":"CLINICIAN"}'

TOKEN=$(curl -s -X POST $BASE/api/v1/auth/login -H "Content-Type: application/json" \
  -d '{"email":"doc@example.com","password":"supersecret1"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -s -X POST $BASE/api/v1/predict/pairwise -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" \
  -d '{"drug_a_cid":"CID000000085","drug_b_cid":"CID000000119"}'
```

---

## 7. Updating the deployment later

This Space repo is now a **separate git history** from your GitHub monorepo — there's no auto-sync. To ship a change (code or new weights):

```bash
cd pharmacognn-space
cp -r /path/to/PharmacoGNN/backend/. .     # re-sync from your working copy
git add .
git commit -m "Update: <what changed>"
git push
```

Every push triggers a full rebuild. If you only changed `weights/z_drug_cache.pt` (e.g. after retraining or re-running `precompute_z_drug_cache.py`), the same content-hash fingerprint check applies — a valid, matching cache still means a fast boot; a genuinely new/incompatible cache means it'll recompute once (and re-save) on first boot after the deploy, same as any local restart would.

If you'd rather not maintain a second local clone, `git subtree` can push directly from your existing monorepo checkout instead of steps 4 onward:

```bash
# From your PharmacoGNN monorepo root, one-time setup:
git remote add space https://huggingface.co/spaces/<owner>/<space-name>
git subtree push --prefix=backend space main
```

This still requires the `.gitattributes` (LFS tracking) and Space-specific `README.md` frontmatter to exist *inside* `backend/` in your monorepo for the subtree push to carry them along — which means adding a second, Spaces-flavored `README.md` inside `backend/` specifically (it would conflict with this repo's own root `README.md` conventions if placed there instead). Most people find the separate-clone approach in step 4 less confusing to reason about; use whichever you're more comfortable maintaining.

---

## 8. Troubleshooting

**Build fails immediately with a file-size / LFS-related error.**
You pushed `.pt`/`.pth` files without LFS tracking. Confirm `.gitattributes` exists and was committed *before* the large files, run `git lfs ls-files` to confirm they're tracked, and if not, you'll need to re-add and re-commit them after fixing `.gitattributes` (a file already committed as a plain blob doesn't retroactively become LFS just by adding a tracking rule afterward).

**Container starts but `alembic upgrade head` fails / hangs.**
Almost always `DATABASE_URL` or `DATABASE_SSL_REQUIRE`. Confirm the connection string uses `postgresql+asyncpg://` (not bare `postgresql://` or `postgres://` — those resolve to psycopg2, which isn't installed here), that it does **not** have a trailing `?sslmode=require` (asyncpg doesn't parse that; `DATABASE_SSL_REQUIRE=true` handles TLS instead — see `app/core/config.py`), and that `DATABASE_SSL_REQUIRE` is actually set to `true` in the Space's Variables tab.

**`/health` returns `gnn_degraded_mode: true` when you expected `false`.**
Either the graph edge file didn't make it into the image (check the build log's `COPY weights ./weights` step lists a reasonable total size, not just a few KB — if LFS pointer files got committed instead of actual content, `weights/` will look tiny), or `z_drug_cache.pt`'s fingerprint didn't match (see below) and it fell all the way back to no-edges mode rather than just recomputing. Check the container logs for the exact `PharmacoGNN: ...` warning — it says specifically what went wrong.

**Cache exists but startup still takes a long time (recomputing rather than loading `z_drug_cache.pt`).**
The fingerprint is a content hash of `pharmacognn_deep_state_dict.pth` and whichever edge file was found — if either differs by even one byte from what produced the cache (e.g. you regenerated one but not the other, or LFS delivered a different version than expected), it's correctly treated as stale and recomputed. This is working as intended, not a bug — see the note in `app/services/gnn_engine.py`'s `_fingerprint()`. Once it finishes, it re-saves a matching cache, so the *next* restart is fast again.

**`403`/CORS errors from your frontend, not from the API's own RBAC.**
`CORS_ORIGINS` still says `http://localhost:3000`. Update it to your deployed frontend's real origin in the Space's Variables tab and restart the Space (Settings → Factory reboot, or just push any commit to trigger a rebuild).

**Space goes idle / cold-starts slowly after inactivity.**
Free-tier CPU Spaces sleep after a period of no traffic and cold-start on the next request. The cold start itself should still be fast (same `z_drug_cache.pt` fast path applies) — what you're seeing is normal container boot + Python/torch import time (a few seconds), not the encoder recomputing. If this matters for your use case, look at HF's paid "always-on" Space option.
