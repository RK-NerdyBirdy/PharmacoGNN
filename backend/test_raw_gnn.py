"""
Standalone smoke test for the PharmacoGNN inference engine.

Run from your backend project root, e.g.:
    python -m app.services.test_raw_gnn
or:
    python test_raw_gnn.py    (after adjusting the import below)

Flags:
    --fresh       Ignore any existing Z_DRUG_CACHE.pt and re-run the HGTConv
                  encoder from scratch. Does NOT overwrite the cache file --
                  a pure "prove it works with zero cache involvement" pass.
    --recompute   Same fresh encoder pass, but DOES overwrite Z_DRUG_CACHE.pt
                  afterward with the new result. Use this once you've fixed
                  something and want the on-disk cache updated to match.
    (neither)     Default/previous behavior: use the cache if its fingerprint
                  matches the current state_dict/edge/vocab files.

WHAT THIS CHECKS, IN ORDER:
  1. initialize() succeeds and Z_DRUG_CACHE_DEGRADED is False. Degraded mode
     means graph_edge_index.pt wasn't found and the encoder never ran --
     predictions would come from raw, untrained-looking node embeddings.
  2. Z_DRUG_CACHE actually has per-drug VARIATION. If a vocabulary mismatch
     or a stale cache slipped through, drug embeddings can end up nearly
     identical to each other -- which is exactly what "predictions all look
     vague" looks like numerically (every pair scores close to the same
     value regardless of which drugs you ask about).
  3. A dump of the first few vocab entries, so you can see with your own eyes
     whether CID_TO_NAME holds real drug names, technical/IUPAC names, or a
     CID echoed back as a failed-lookup fallback -- the single most common
     reason "well-known drug X not found" happens with a byte-for-byte
     correctly loaded model.
  4. Real drug-pair predictions, resolved via a forgiving name lookup that
     shows near-miss suggestions instead of silently skipping.

Steps 1-2 are the actual model/inference diagnosis; step 3 tells you *why*
step 4 will or won't find your drugs. If step 1 or 2 reports a problem, fix
that BEFORE trusting any number step 4 prints.
"""

from __future__ import annotations

import argparse

import torch

# --- Adjust this import to wherever gnn_engine.py actually lives in your
#     project (e.g. app.services.gnn_engine, app.ml.gnn_engine, app.gnn_engine). ---
from app.services import gnn_engine


# Human-readable names to look up. If your vocab's names don't resolve these
# (see STEP 3 below for why), add known CIDs straight from your own
# drug2idx.json / cid_to_name.json here instead -- gnn_engine.find_drug()
# also accepts a raw CID and will use it directly, no name matching involved.
CANDIDATE_PAIRS = [
    ("Minoxidil", "Aspirin"),           # bleeding risk
    ("Citalopram", "Azithromycin"),    # QT prolongation -- hackathon anchor case
    ("Simvastatin", "Amiodarone"),     # myopathy / rhabdomyolysis risk (CYP3A4)
    ("Lisinopril", "Spironolactone"),  # hyperkalemia
    ("Ibuprofen", "Aspirin"),          # GI bleeding / reduced antiplatelet effect
]

# Drop confirmed (cid_a, cid_b) pairs here once you know the exact CID keys
# your vocab uses (see STEP 3's dump) -- these run in addition to the
# name-based CANDIDATE_PAIRS above and never depend on name matching at all.
CID_PAIRS: list[tuple[str, str]] = []


def run_diagnostics(force_recompute: bool, skip_cache_write: bool) -> bool:
    """Returns True if it's safe to trust predict_pairwise's output."""
    print("=" * 70)
    print("STEP 1 -- initialize()", end="")
    if force_recompute:
        print(f"  (force_recompute=True, skip_cache_write={skip_cache_write})")
    else:
        print()
    print("=" * 70)
    gnn_engine.initialize(force_recompute=force_recompute, skip_cache_write=skip_cache_write)
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

    print("\n" + "=" * 70)
    print("STEP 3 -- vocabulary sample (why name lookups do or don't resolve)")
    print("=" * 70)
    sample_entries = gnn_engine.vocab_sample(15)
    for entry in sample_entries:
        print(f"    idx={entry['idx']:>5}  cid={entry['cid']:<20}  name={entry['name']}")
    print(
        "\nLook at the 'name' column above. If these read as common drug names "
        "(e.g. 'Aspirin'), name lookup should work fine. If they read as "
        "technical/IUPAC chemical names, or as the CID echoed back as its own "
        "name, that -- not the model -- is why CANDIDATE_PAIRS below won't "
        "resolve by common name. In that case use CID_PAIRS instead."
    )

    return ok


def run_sample_predictions() -> int:
    """Returns the number of pairs actually scored."""
    print("\n" + "=" * 70)
    print("STEP 4 -- sample drug-pair predictions")
    print("=" * 70)

    n_run = 0

    for name_a, name_b in CANDIDATE_PAIRS:
        matches_a = gnn_engine.find_drug(name_a)
        matches_b = gnn_engine.find_drug(name_b)

        if not matches_a or not matches_b:
            missing = name_a if not matches_a else name_b
            print(f"\n[{name_a} + {name_b}] SKIPPED -- '{missing}' not found in this vocabulary.")
            continue

        cid_a, resolved_a = matches_a[0]
        cid_b, resolved_b = matches_b[0]
        is_exact_a = resolved_a.lower() == name_a.lower() or name_a.lower() in resolved_a.lower()
        is_exact_b = resolved_b.lower() == name_b.lower() or name_b.lower() in resolved_b.lower()

        if not (is_exact_a and is_exact_b):
            print(
                f"\n[{name_a} + {name_b}] no exact match -- closest names found: "
                f"'{resolved_a}' (for {name_a}), '{resolved_b}' (for {name_b}). "
                "Skipping rather than guessing; re-run with the exact CID in "
                "CID_PAIRS if one of these is actually the right drug."
            )
            continue

        try:
            results = gnn_engine.predict_pairwise(cid_a, cid_b, apply_female_bias=True)
        except KeyError as e:
            print(f"\n[{name_a} + {name_b}] SKIPPED -- {e}")
            continue

        n_run += 1
        _print_prediction(n_run, gnn_engine.drug_name(cid_a), cid_a, gnn_engine.drug_name(cid_b), cid_b, results)

    for cid_a, cid_b in CID_PAIRS:
        try:
            results = gnn_engine.predict_pairwise(cid_a, cid_b, apply_female_bias=True)
        except KeyError as e:
            print(f"\n[CID pair {cid_a} + {cid_b}] SKIPPED -- {e}")
            continue
        n_run += 1
        _print_prediction(n_run, gnn_engine.drug_name(cid_a), cid_a, gnn_engine.drug_name(cid_b), cid_b, results)

    if n_run == 0:
        print(
            "\nNo pairs were found and scored. Check the STEP 3 vocab dump above, "
            "then either fix CANDIDATE_PAIRS' names to match what's actually in "
            "cid_to_name.json, or fill in CID_PAIRS with exact CID keys."
        )

    return n_run


def _print_prediction(n: int, name_a: str, cid_a: str, name_b: str, cid_b: str, results: list[dict]) -> None:
    print(f"\n[{n}] {name_a} ({cid_a}) + {name_b} ({cid_b})")
    print(f"    {'Side effect':45s} {'Risk':>8s}  Type")
    print("    " + "-" * 66)
    for r in results[:5]:
        tag = "FEMALE-ADR" if r["female_weighted"] else "standard"
        print(f"    {r['name'][:45]:45s} {r['risk_score']:8.2f}  {tag}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fresh", action="store_true",
        help="Recompute Z_DRUG_CACHE from the encoder, ignoring any existing cache file, "
             "without writing the result back to disk.",
    )
    parser.add_argument(
        "--recompute", action="store_true",
        help="Recompute Z_DRUG_CACHE from the encoder, ignoring any existing cache file, "
             "AND overwrite the cache file on disk with the new result.",
    )
    args = parser.parse_args()

    if args.fresh and args.recompute:
        parser.error("pass only one of --fresh / --recompute")

    force_recompute = args.fresh or args.recompute
    skip_cache_write = args.fresh  # --recompute persists; --fresh does not

    diagnostics_passed = run_diagnostics(force_recompute=force_recompute, skip_cache_write=skip_cache_write)
    n_run = run_sample_predictions()

    print("\n" + "=" * 70)
    if diagnostics_passed and n_run > 0:
        print(f"PASSED -- model/inference checks OK and {n_run} prediction(s) verified above.")
    elif diagnostics_passed and n_run == 0:
        print(
            "MODEL LOADING OK, BUT ZERO PREDICTIONS VERIFIED. Loading, the encoder pass, and "
            "embedding variation all check out (STEP 1-2) -- nothing here points to a bug in "
            "gnn_engine.py's inference path. The failure is entirely in name resolution "
            "(STEP 3-4): fix CANDIDATE_PAIRS/CID_PAIRS and re-run before drawing any "
            "conclusion about the model itself."
        )
    else:
        print("DIAGNOSTICS FAILED -- see STEP 1/2 output above. Any scores printed in")
        print("STEP 4 are NOT trustworthy until the failure(s) above are fixed.")
    print("=" * 70)