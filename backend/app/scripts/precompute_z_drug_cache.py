"""One-time (or one-time-per-checkpoint-update) precompute of Z_DRUG_CACHE.

Runs the full 3-layer HGTConv encoder over the real graph and writes the
result to `weights/z_drug_cache.pt` alongside a fingerprint of the exact
state_dict + edge file it was built from. `gnn_engine.initialize()` checks
this fingerprint on every startup and reuses the cached tensor whenever it
still matches, skipping the encoder forward pass entirely -- this script
exists so that expensive run can happen deliberately, ahead of time, rather
than blocking a server's (or a container's) first request.

This is CPU-bound and, for a graph this size (~1.5M edges), took roughly
25 minutes on the reference dev machine. Run it whenever
pharmacognn_deep_state_dict.pth or the graph edge file changes; otherwise
the fingerprint check will simply reuse the existing cache and this script
is a no-op that returns almost instantly.

Usage (from backend/):
    python -m app.scripts.precompute_z_drug_cache
"""

from __future__ import annotations

import logging
import time

from app.core.config import settings
from app.services import gnn_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> None:
    start = time.monotonic()
    gnn_engine.initialize()
    elapsed = time.monotonic() - start

    if gnn_engine.Z_DRUG_CACHE_DEGRADED:
        print(
            f"Done in {elapsed:.1f}s, but Z_DRUG_CACHE_DEGRADED=True -- no graph edge file was "
            "found, so there was nothing to cache. See gnn_engine.py's _GRAPH_EDGE_FILENAMES."
        )
        return

    cache_path = settings.WEIGHTS_DIR / settings.Z_DRUG_CACHE_FILENAME
    print(
        f"Done in {elapsed:.1f}s. Z_DRUG_CACHE is now cached at {cache_path}. "
        "Future app startups will load it directly instead of re-running the encoder."
    )


if __name__ == "__main__":
    main()
