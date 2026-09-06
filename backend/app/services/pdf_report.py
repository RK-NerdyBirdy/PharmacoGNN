"""Renders a COMPLETE InteractionReport's payload to a PDF on local disk.

Deliberately takes only report.payload (already-computed, durable JSON) as
input, never re-runs any GNN/LLM call -- this is what lets api/v1/reports.py
regenerate a missing-on-disk PDF cheaply on demand instead of treating a
wiped container disk as an error requiring a whole new analysis.
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.config import settings
from app.models.patient import PatientProfile
from app.models.report import InteractionReport
from app.schemas.report import DISCLAIMER

_STYLES = getSampleStyleSheet()
_DISCLAIMER_STYLE = ParagraphStyle(
    "Disclaimer", parent=_STYLES["Normal"], textColor=colors.white, backColor=colors.HexColor("#B00020"),
    borderPadding=8, fontSize=11, leading=14, spaceAfter=6,
)
_WARNING_STYLE = ParagraphStyle(
    "ModelWarning", parent=_STYLES["Normal"], textColor=colors.HexColor("#7A4B00"),
    backColor=colors.HexColor("#FFF3CD"), borderPadding=6, fontSize=9, leading=12, spaceAfter=12,
)
_SECTION_STYLE = ParagraphStyle("Section", parent=_STYLES["Heading2"], spaceBefore=14, spaceAfter=6)
_BODY = _STYLES["BodyText"]

_TABLE_HEADER_STYLE = TableStyle(
    [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2E3A59")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F6FA")]),
    ]
)


def _output_path(report_id) -> Path:
    settings.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return settings.REPORTS_DIR / f"{report_id}.pdf"


def render(report: InteractionReport, patient: PatientProfile) -> Path:
    if report.payload is None:
        raise ValueError(f"Report {report.id} has no payload to render")

    payload = report.payload
    path = _output_path(report.id)

    doc = SimpleDocTemplate(
        str(path), pagesize=LETTER,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch, leftMargin=0.6 * inch, rightMargin=0.6 * inch,
    )
    story: list = []

    story.append(Paragraph("PharmacoGNN Interaction Report", _STYLES["Title"]))
    story.append(Paragraph(DISCLAIMER, _DISCLAIMER_STYLE))

    model_status = payload.get("model_status") or {}
    if model_status.get("warning"):
        warning_text = model_status["warning"]
        if model_status.get("degraded_mode"):
            warning_text += " Predictions were computed in degraded mode (no graph edge data available)."
        story.append(Paragraph(warning_text, _WARNING_STYLE))

    story.append(Paragraph("Patient", _SECTION_STYLE))
    story.append(
        Paragraph(
            f"{patient.legal_name} &nbsp;&middot;&nbsp; Age {patient.age} "
            f"&nbsp;&middot;&nbsp; {patient.biological_sex.value.title()}",
            _BODY,
        )
    )
    story.append(
        Paragraph(
            f"Report generated {report.completed_at or report.created_at:%Y-%m-%d %H:%M UTC}", _BODY
        )
    )

    story.append(Paragraph("Active Regimen", _SECTION_STYLE))
    regimen_rows = [["Drug", "PubChem CID", "Dosage"]]
    for item in payload.get("regimen_snapshot", []):
        regimen_rows.append([item["drug_name"], item["pubchem_cid"], item.get("dosage") or "—"])
    story.append(Table(regimen_rows, style=_TABLE_HEADER_STYLE, hAlign="LEFT"))

    unresolved = payload.get("unresolved_drugs") or []
    if unresolved:
        story.append(Paragraph("Excluded From Analysis (Not In Model Vocabulary)", _SECTION_STYLE))
        for item in unresolved:
            story.append(Paragraph(f"• {item['drug_name']} ({item['reason']})", _BODY))

    summary = payload.get("summary") or {}
    story.append(Paragraph("Summary", _SECTION_STYLE))
    story.append(
        Paragraph(
            f"Drugs analyzed: {summary.get('drug_count', 0)} &nbsp;&middot;&nbsp; "
            f"High-risk pairs: {summary.get('high_risk_pair_count', 0)} &nbsp;&middot;&nbsp; "
            f"Regimen toxicity index: {summary.get('regimen_toxicity_index', 0):.1f} / 100",
            _BODY,
        )
    )

    story.append(Paragraph("Pairwise Interactions", _SECTION_STYLE))
    pairwise_rows = [["Drug A", "Drug B", "Top Adverse Effect", "Risk Score", "High Risk"]]
    for pair in payload.get("pairwise", []):
        pairwise_rows.append(
            [
                pair["drug_a_cid"],
                pair["drug_b_cid"],
                pair["top_adverse_effect"],
                f"{pair['top_risk_score']:.1f}",
                "Yes" if pair["is_high_risk"] else "No",
            ]
        )
    story.append(Table(pairwise_rows, style=_TABLE_HEADER_STYLE, hAlign="LEFT"))

    substitutions = payload.get("substitutions") or []
    if substitutions:
        story.append(Paragraph("Suggested Substitutions", _SECTION_STYLE))
        for sub in substitutions:
            story.append(Paragraph(f"For {sub['for_drug_cid']}:", _BODY))
            for alt in sub.get("alternatives", []):
                story.append(
                    Paragraph(
                        f"&nbsp;&nbsp;• {alt['name']} ({alt['cid']}) — new risk score "
                        f"{alt['new_top_risk_score']:.1f} (−{alt['risk_reduction']:.1f})",
                        _BODY,
                    )
                )

    explanations = payload.get("explanations") or []
    if explanations:
        story.append(Paragraph("Clinical Explanations", _SECTION_STYLE))
        for exp in explanations:
            story.append(
                Paragraph(
                    f"<b>{exp['drug_a_cid']} + {exp['drug_b_cid']}</b> — "
                    f"{exp['severity_classification']}",
                    _BODY,
                )
            )
            story.append(Paragraph(exp["clinical_mechanism"], _BODY))
            story.append(Paragraph(f"<i>{exp['patient_summary']}</i>", _BODY))
            story.append(Paragraph(f"Guidance: {exp['actionable_guidance']}", _BODY))
            story.append(Spacer(1, 8))

    doc.build(story)
    return path
