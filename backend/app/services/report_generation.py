"""Builds the frozen interaction-analysis payload for one InteractionReport row.

Runs as a FastAPI BackgroundTask (see api/v1/reports.py), which means it
executes after the 202 response has already gone out and cannot reuse the
request's DB session (that's closed by then) -- it opens its own via
AsyncSessionLocal instead.

Failure handling is deliberately layered, not all-or-nothing:
  - No resolvable drugs left in the active regimen -> the report fails
    outright (there's nothing to analyze).
  - The GNN scoring itself failing -> the report fails (this is the core
    analysis; a report without it isn't a degraded report, it's not a
    report).
  - One high-risk pair's LLM explanation failing (no OPENROUTER_API_KEY
    configured, a timeout, a schema-validation miss) -> that pair is just
    skipped from `explanations`, logged, and generation continues. A report
    missing one pair's narrative is still useful; failing the whole report
    over a third-party LLM call would throw out real, already-computed GNN
    analysis.
  - PDF rendering failing -> logged, `file_path` stays unset
    (`file_available: false`), but the report itself is still COMPLETE --
    the JSON analysis is the source of truth, the PDF is a rendering of it.
"""
from __future__ import annotations

import datetime as dt
import logging
from uuid import UUID

from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.patient import BiologicalSex, PatientProfile, PatientRegimen
from app.models.report import InteractionReport, ReportStatus
from app.services import gnn_engine, llm_explainer, pdf_report, substitution

logger = logging.getLogger(__name__)

_MODEL_WARNING = (
    "This model's absolute risk scores have not been clinically validated. "
    "Treat them as a decision-support signal, not a diagnosis."
)


async def generate_report(report_id: UUID) -> None:
    async with AsyncSessionLocal() as db:
        report = await db.get(InteractionReport, report_id)
        if report is None:
            logger.error("generate_report: report %s vanished before generation started", report_id)
            return

        try:
            await _run_generation(report, db)
        except Exception:
            logger.exception("Report %s generation failed", report_id)
            report.status = ReportStatus.FAILED
            report.error_message = "Report generation failed unexpectedly."
            report.completed_at = dt.datetime.now(dt.timezone.utc)
            await db.commit()


async def _run_generation(report: InteractionReport, db) -> None:
    patient = await db.get(PatientProfile, report.patient_id)
    if patient is None:
        report.status = ReportStatus.FAILED
        report.error_message = "Patient record no longer exists."
        report.completed_at = dt.datetime.now(dt.timezone.utc)
        await db.commit()
        return

    regimen_rows = list(
        (
            await db.scalars(
                select(PatientRegimen).where(
                    PatientRegimen.patient_id == report.patient_id,
                    PatientRegimen.end_date.is_(None),
                )
            )
        ).all()
    )

    snapshot = [
        {"pubchem_cid": row.pubchem_cid, "drug_name": row.drug_name, "dosage": row.dosage}
        for row in regimen_rows
    ]

    # Regimen writes are already validated against the vocabulary at write
    # time (see services/drug_resolution.py) -- this re-check only catches
    # the model/vocabulary itself changing out from under an existing regimen
    # between when a drug was added and when this report runs.
    resolved_cids: list[str] = []
    unresolved: list[dict[str, str]] = []
    for row in regimen_rows:
        if row.pubchem_cid in gnn_engine.DRUG2IDX:
            resolved_cids.append(row.pubchem_cid)
        else:
            unresolved.append({"drug_name": row.drug_name, "reason": "not_in_vocabulary"})

    if len(resolved_cids) < 2:
        report.status = ReportStatus.FAILED
        report.error_message = (
            "Fewer than two resolvable active medications -- an interaction report needs at least two."
        )
        report.completed_at = dt.datetime.now(dt.timezone.utc)
        await db.commit()
        return

    apply_female_bias = patient.biological_sex == BiologicalSex.FEMALE

    matrix, pair_flags, toxicity_index = gnn_engine.predict_regimen_matrix(resolved_cids, apply_female_bias)

    pairwise_results = []
    substitutions = []
    explanations = []
    explanations_used = 0

    for flag in pair_flags:
        cid_a = resolved_cids[flag["i"]]
        cid_b = resolved_cids[flag["j"]]

        adverse_effects = gnn_engine.predict_pairwise(cid_a, cid_b, apply_female_bias)
        pairwise_results.append(
            {
                "drug_a_cid": cid_a,
                "drug_b_cid": cid_b,
                "top_risk_score": flag["top_risk_score"],
                "top_adverse_effect": flag["top_adverse_effect"],
                "is_high_risk": flag["is_high_risk"],
                "female_weighted": flag["female_weighted"],
                "adverse_effects": adverse_effects,
            }
        )

        if not flag["is_high_risk"]:
            continue

        try:
            _original, alternatives = substitution.find_safe_substitutes(cid_a, cid_b, apply_female_bias)
            if alternatives:
                substitutions.append({"for_drug_cid": cid_b, "alternatives": alternatives})
        except Exception:
            logger.exception("Substitution search failed for %s/%s in report %s", cid_a, cid_b, report.id)

        if explanations_used >= settings.REPORT_MAX_EXPLANATIONS:
            continue

        try:
            pathway = gnn_engine.find_bridging_proteins(cid_a, cid_b)
            context = {
                "drug_a_cid": cid_a,
                "drug_a_name": gnn_engine.drug_name(cid_a),
                "drug_b_cid": cid_b,
                "drug_b_name": gnn_engine.drug_name(cid_b),
                "adverse_effect": flag["top_adverse_effect"],
                "risk_score": flag["top_risk_score"],
                "female_adjustment_applied": apply_female_bias and flag["female_weighted"],
                "pathway": {"nodes": pathway["nodes"], "edges": pathway["edges"]},
            }
            explanation = await llm_explainer.explain_interaction(context)
            explanations.append(
                {
                    "drug_a_cid": cid_a,
                    "drug_b_cid": cid_b,
                    "clinical_mechanism": explanation.clinical_mechanism,
                    "severity_classification": explanation.severity_classification.value,
                    "patient_summary": explanation.patient_summary,
                    "actionable_guidance": explanation.actionable_guidance,
                    "xai_pathway": {
                        "nodes": [n.model_dump() for n in explanation.xai_pathway.nodes],
                        "edges": [e.model_dump() for e in explanation.xai_pathway.edges],
                        "data_available": pathway["data_available"],
                    },
                }
            )
            explanations_used += 1
        except RuntimeError as exc:
            logger.warning(
                "LLM explanation skipped for %s/%s in report %s: %s", cid_a, cid_b, report.id, exc
            )

    high_risk_count = sum(1 for f in pair_flags if f["is_high_risk"])

    report.payload = {
        "model_status": {
            "degraded_mode": gnn_engine.Z_DRUG_CACHE_DEGRADED,
            "verified": False,
            "warning": _MODEL_WARNING,
        },
        "regimen_snapshot": snapshot,
        "unresolved_drugs": unresolved,
        "summary": {
            "drug_count": len(resolved_cids),
            "high_risk_pair_count": high_risk_count,
            "regimen_toxicity_index": toxicity_index,
        },
        "interaction_matrix": matrix,
        "pairwise": pairwise_results,
        "substitutions": substitutions,
        "explanations": explanations,
    }
    report.status = ReportStatus.COMPLETE
    report.completed_at = dt.datetime.now(dt.timezone.utc)
    await db.commit()
    await db.refresh(report)

    try:
        file_path = pdf_report.render(report, patient)
        report.file_path = str(file_path)
        await db.commit()
    except Exception:
        logger.exception("PDF rendering failed for report %s (analysis is still COMPLETE)", report.id)
