from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.auth import router as auth_router
from app.api.v1.explain import router as explain_router
from app.api.v1.patients import router as patients_router
from app.api.v1.predict import router as predict_router
from app.api.v1.pubchem import router as pubchem_router
from app.api.v1.vocab import router as vocab_router
from app.core.config import settings
from app.services import gnn_engine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    gnn_engine.initialize()
    if gnn_engine.Z_DRUG_CACHE_DEGRADED:
        logger.warning(
            "Starting in DEGRADED prediction mode: Z_DRUG_CACHE was built without running the "
            "HGTConv encoder (no graph edge data found). See app/services/gnn_engine.py."
        )
    yield


app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)

# Explicit origin allow-list (never "*") since allow_credentials=True is needed
# for the Authorization: Bearer header the frontend will send on every
# authenticated request. Configure via CORS_ORIGINS (see core/config.py) —
# includes the static frontend's live-server dev origin by default, needed for
# browser-side fetch() calls (e.g. MoleculeViewer, the pubchem proxy) to work.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api/v1")
app.include_router(patients_router, prefix="/api/v1")
app.include_router(predict_router, prefix="/api/v1")
app.include_router(pubchem_router, prefix="/api/v1")
app.include_router(explain_router, prefix="/api/v1")
app.include_router(vocab_router, prefix="/api/v1")


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "gnn_ready": gnn_engine.is_ready(),
        "gnn_degraded_mode": gnn_engine.Z_DRUG_CACHE_DEGRADED,
    }
