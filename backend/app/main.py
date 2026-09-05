from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.auth import router as auth_router
from app.api.v1.explain import router as explain_router
from app.api.v1.predict import router as predict_router
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

app.include_router(auth_router, prefix="/api/v1")
app.include_router(predict_router, prefix="/api/v1")
app.include_router(explain_router, prefix="/api/v1")


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "gnn_ready": gnn_engine.is_ready(),
        "gnn_degraded_mode": gnn_engine.Z_DRUG_CACHE_DEGRADED,
    }
