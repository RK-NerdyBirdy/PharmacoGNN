from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    PROJECT_NAME: str = "PharmacoGNN"
    ENVIRONMENT: str = "development"

    DATABASE_URL: str

    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Raw 32-byte AES-256 key, base64-encoded (see .env.example for generation).
    FIELD_ENCRYPTION_KEY: str

    # --- Phase 2: GNN inference engine ---
    # Repo ships this as backend/weights (not backend/artifacts) — kept as-is
    # rather than introducing a duplicate directory.
    WEIGHTS_DIR: Path = BACKEND_DIR / "weights"
    MODEL_STATE_DICT_FILENAME: str = "pharmacognn_deep_state_dict.pth"
    GNN_DEVICE: str = "cpu"

    # Calibrated loss weight for curated female-biased ADRs (relation_meta.json's
    # `female_weighted` flag), and the ceiling a scaled score is clamped to.
    FEMALE_ADR_RISK_MULTIPLIER: float = 3.0
    RISK_SCORE_CLAMP: float = 99.9

    # Phase 2's predict/regimen endpoint flags a pair as "high risk" above this.
    HIGH_RISK_THRESHOLD: float = 75.0

    # Origins allowed to call this API from the browser (the static frontend in
    # frontend/, served on its own origin during local dev via live-server).
    FRONTEND_ORIGINS: list[str] = ["http://localhost:8420", "http://127.0.0.1:8420"]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
