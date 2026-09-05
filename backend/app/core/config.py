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
    # Precomputed encoder output for all drugs, saved alongside a fingerprint of
    # the state_dict + edge file it was built from. If present and the
    # fingerprint still matches, startup skips the ~25min CPU forward pass
    # entirely. Regenerate with `python -m app.scripts.precompute_z_drug_cache`.
    Z_DRUG_CACHE_FILENAME: str = "z_drug_cache.pt"

    # Calibrated loss weight for curated female-biased ADRs (relation_meta.json's
    # `female_weighted` flag), and the ceiling a scaled score is clamped to.
    FEMALE_ADR_RISK_MULTIPLIER: float = 3.0
    RISK_SCORE_CLAMP: float = 99.9

    # Phase 2's predict/regimen endpoint flags a pair as "high risk" above this.
    HIGH_RISK_THRESHOLD: float = 75.0

    # --- Phase 3: substitution search ---
    # How many nearest-by-cosine-similarity candidates to re-score before picking
    # the top N by risk reduction; keep this well above SUBSTITUTION_TOP_N since
    # most similar drugs won't actually reduce risk against the fixed partner.
    SUBSTITUTION_CANDIDATE_POOL_SIZE: int = 20
    SUBSTITUTION_TOP_N: int = 3

    # --- Phase 3: OpenRouter LLM explainer ---
    # Empty by default so Phases 1/2 keep working without it configured;
    # llm_explainer raises a clear error at call time if this is unset.
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_MODEL: str = "anthropic/claude-3.5-sonnet"
    OPENROUTER_TIMEOUT_SECONDS: float = 30.0

    # --- Phase 4: drug-disease contraindication screening ---
    # No file ships with this repo by default -- see app/services/drug_disease.py
    # for the exact expected format. Populating it requires a real, clinically-
    # reviewed reference (e.g. sourced from DrugBank/FDA labeling); this codebase
    # will not fabricate contraindication rules, so screening returns [] until
    # a real file is placed at WEIGHTS_DIR / this filename.
    DRUG_DISEASE_REFERENCE_FILENAME: str = "drug_disease_contraindications.json"

    # --- CORS ---
    # Comma-separated allow-list (not a JSON list) so a plain .env/docker-compose
    # env var is easy to edit: CORS_ORIGINS=http://localhost:3000,http://localhost:5173
    # Includes the frontend's actual local dev port (live-server, see
    # frontend/package.json) alongside the originally planned one.
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:8420,http://127.0.0.1:8420"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
