"""
Standalone smoke test for the PharmacoGNN inference engine.

Run from your backend project root, e.g.:
    python -m app.services.test_predictions
or:
    python test_predictions.py    (after adjusting the import below)

WHAT THIS CHECKS, IN ORDER:
  1. initialize() succeeds and Z_DRUG_CACHE_DEGRADED is False. Degraded mode
     means graph_edge_index.pt wasn't found and the encoder never ran --
     predictions would come from raw, untrained-looking node embeddings.
  2. Z_DRUG_CACHE actually has per-drug VARIATION. If a vocabulary mismatch
     or a stale cache slipped through, drug embeddings can end up nearly
     identical to each other -- which is exactly what "predictions all look
     vague" looks like numerically (every pair scores close to the same
     value regardless of which drugs you ask about).
  3. Five real drug-pair predictions, with human-readable names.

Steps 1-2 are the actual diagnosis; step 3 is just confirmation once 1-2
pass. If this script reports a problem, fix that BEFORE trusting any number
Step 3 prints.
"""

# --- Adjust this import to wherever gnn_engine.py actually lives in your
#     project (e.g. app.services.gnn_engine, app.ml.gnn_engine, app.gnn_engine). ---
from app.services import gnn_engine

import torch


CANDIDATE_PAIRS = [
    ("Warfarin", "Aspirin"),           # bleeding risk
    ("Citalopram", "Azithromycin"),    # QT prolongation
    ("Simvastatin", "Amiodarone"),     # myopathy / rhabdomyolysis risk (CYP3A4)
    ("Lisinopril", "Spironolactone"),  # hyperkalemia
    ("Ibuprofen", "Aspirin"),          # GI bleeding / reduced antiplatelet effect
]


def _find_cid(name_query: str) -> str | None:
    """Substring match against CID_TO_NAME -- same pattern the training
    notebook already uses to locate drugs by name."""
    name_query_l = name_query.lower()
    for cid, name in gnn_engine.CID_TO_NAME.items():
        if name_query_l in name.lower():
            return cid
    return None


def run_diagnostics() -> bool:
    """Returns True if it's safe to trust predict_pairwise's output."""
    print("=" * 70)
    print("STEP 1 -- initialize()")
    print("=" * 70)
    gnn_engine.initialize()
    print(f"is_ready(): {gnn_engine.is_ready()}")
    print(f"Z_DRUG_CACHE_DEGRADED: {gnn_engine.Z_DRUG_CACHE_DEGRADED}")

    ok = True
    if gnn_engine.Z_DRUG_CACHE_DEGRADED:
        print(
            "\n  FAIL -- degraded mode. graph_edge_index.pt was not found (or not "
            "loadable) in the weights directory. Predictions below are running "
            "on raw node embeddings with NO message passing through the graph "
            "at all -- this is the 'vague predictions' symptom, diagnosed."
        )
        ok = False

    print(f"\nDrugs in vocabulary:     {len(gnn_engine.DRUG2IDX):,}")
    print(f"Proteins in vocabulary:  {len(gnn_engine.PROTEIN2IDX):,}")
    print(f"Relations loaded:        {len(gnn_engine.IDX_TO_RELATION_META):,}")

    print("\n" + "=" * 70)
    print("STEP 2 -- Z_DRUG_CACHE variation check")
    print("=" * 70)
    z = gnn_engine.Z_DRUG_CACHE
    if z is None:
        print("  FAIL -- Z_DRUG_CACHE is None.")
        return False

    # Pairwise cosine similarity across a small random sample of drugs.
    # Real, message-passed embeddings should be clearly differentiated
    # (typical cosine similarities well below ~0.99); embeddings that
    # collapsed to near-identical vectors are the numerical signature of
    # every prediction looking the same regardless of which drugs you ask
    # about.
    sample_n = min(20, z.shape[0])
    sample_idx = torch.randperm(z.shape[0])[:sample_n]
    sample = z[sample_idx]
    sample_norm = torch.nn.functional.normalize(sample, dim=1)
    sim_matrix = sample_norm @ sample_norm.T
    off_diag = sim_matrix[~torch.eye(sample_n, dtype=torch.bool)]
    mean_sim = off_diag.mean().item()
    max_sim = off_diag.max().item()

    print(f"Sampled {sample_n} drugs -- mean pairwise cosine similarity: {mean_sim:.4f}, max: {max_sim:.4f}")
    if mean_sim > 0.98:
        print(
            "\n  FAIL -- drug embeddings are nearly identical to each other "
            "(mean cosine similarity > 0.98). This will produce near-uniform "
            "predictions regardless of which drug pair you query -- likely a "
            "vocabulary/index mismatch between drug2idx.json and whatever "
            "actually produced graph_edge_index.pt / the checkpoint. See the "
            "artifact-fingerprint note in gnn_engine.py's _source_fingerprint."
        )
        ok = False
    else:
        print("  OK -- embeddings are meaningfully differentiated across drugs.")

    return ok


def run_sample_predictions() -> None:
    print("\n" + "=" * 70)
    print("STEP 3 -- Five sample drug-pair predictions")
    print("=" * 70)

    n_run = 0
    for name_a, name_b in CANDIDATE_PAIRS:
        cid_a, cid_b = _find_cid(name_a), _find_cid(name_b)
        if cid_a is None or cid_b is None:
            missing = name_a if cid_a is None else name_b
            print(f"\n[{name_a} + {name_b}] SKIPPED -- '{missing}' not found in this vocabulary.")
            continue

        try:
            results = gnn_engine.predict_pairwise(cid_a, cid_b, apply_female_bias=True)
        except KeyError as e:
            print(f"\n[{name_a} + {name_b}] SKIPPED -- {e}")
            continue

        n_run += 1
        real_name_a = gnn_engine.drug_name(cid_a)
        real_name_b = gnn_engine.drug_name(cid_b)
        print(f"\n[{n_run}] {real_name_a} ({cid_a}) + {real_name_b} ({cid_b})")
        print(f"    {'Side effect':45s} {'Risk':>8s}  Type")
        print("    " + "-" * 66)
        for r in results[:5]:
            tag = "FEMALE-ADR" if r["female_weighted"] else "standard"
            print(f"    {r['name'][:45]:45s} {r['risk_score']:8.2f}  {tag}")

    if n_run == 0:
        print(
            "\nNone of the 5 candidate pairs were found in this vocabulary. "
            "Edit CANDIDATE_PAIRS above to names you know are in your "
            "drug2idx.json / cid_to_name.json."
        )
    elif n_run < 5:
        print(f"\n({n_run}/5 candidate pairs found and run -- the rest were skipped, see above.)")


if __name__ == "__main__":
    diagnostics_passed = run_diagnostics()
    run_sample_predictions()

    print("\n" + "=" * 70)
    if diagnostics_passed:
        print("DIAGNOSTICS PASSED -- the scores above reflect a properly loaded,")
        print("message-passed model.")
    else:
        print("DIAGNOSTICS FAILED -- see STEP 1/2 output above. The scores in")
        print("STEP 3 are NOT trustworthy until the failure(s) above are fixed.")
    print("=" * 70)