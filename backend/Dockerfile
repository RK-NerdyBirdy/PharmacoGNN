# syntax=docker/dockerfile:1

# --- Builder: compile/install Python deps into an isolated venv -------------
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# build-essential is only needed if pip has to build a wheel for this exact
# platform/interpreter; it stays in this stage and never reaches the final image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
# CPU-only torch: the default PyPI wheel resolves to a CUDA-enabled build with
# ~1GB+ of bundled GPU runtime libs this project never uses. Installed first so
# requirements.txt's own `torch>=2.3` line is already satisfied and left alone.
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch \
    && pip install -r requirements.txt

# --- Runtime: slim image, no compilers, non-root user ------------------------
FROM python:3.11-slim AS runtime

# libgomp1: PyTorch's CPU wheels dynamically link OpenMP at runtime; without it
# `import torch` fails on a bare slim image with "libgomp.so.1: cannot open
# shared object file".
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 appuser

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY alembic.ini .
COPY alembic ./alembic
COPY app ./app
COPY weights ./weights
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
    && chown -R appuser:appuser /app

USER appuser
EXPOSE 8000

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
