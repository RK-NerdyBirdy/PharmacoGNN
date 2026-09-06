from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_role
from app.core.http import client_ip
from app.models.audit import AuditActionType, AuditLog
from app.models.patient import PatientProfile, PatientRegimen
from app.models.report import InteractionReport, ReportStatus
from app.models.user import User, UserRole
from app.schemas.report import (
    ReportAccepted,
    ReportListItem,
    ReportRead,
    ReportSummary,
)
from app.services import pdf_report, report_generation
from app.services.patient_access import load_accessible_patient

router = APIRouter(tags=["reports"])


def _audit(current_user: User, patient_id: UUID, action: AuditActionType, request: Request) -> AuditLog:
    return AuditLog(
        accessor_user_id=current_user.id,
        target_patient_id=patient_id,
        action_type=action,
        resource_type="InteractionReport",
        ip_address=client_ip(request),
    )


async def _load_report_or_404(report_id: UUID, db: AsyncSession) -> InteractionReport:
    report = await db.get(InteractionReport, report_id)
    if report is None or report.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    return report


def _file_available(report: InteractionReport) -> bool:
    return bool(report.file_path) and Path(report.file_path).exists()


def _build_report_read(report: InteractionReport) -> ReportRead:
    payload = report.payload or {}
    summary = payload.get("summary")
    return ReportRead(
        id=report.id,
        patient_id=report.patient_id,
        status=report.status.value.lower(),
        created_at=report.created_at,
        generated_by=report.generated_by,
        model_status=payload.get("model_status"),
        regimen_snapshot=payload.get("regimen_snapshot", []),
        unresolved_drugs=payload.get("unresolved_drugs", []),
        summary=ReportSummary(**summary) if summary else None,
        interaction_matrix=payload.get("interaction_matrix", []),
        pairwise=payload.get("pairwise", []),
        substitutions=payload.get("substitutions", []),
        explanations=payload.get("explanations", []),
        file_available=_file_available(report),
        error_message=report.error_message,
    )


def _build_list_item(report: InteractionReport) -> ReportListItem:
    payload = report.payload or {}
    summary = payload.get("summary")
    return ReportListItem(
        id=report.id,
        status=report.status.value.lower(),
        created_at=report.created_at,
        generated_by=report.generated_by,
        summary=ReportSummary(**summary) if summary else None,
        file_available=_file_available(report),
    )


@router.post(
    "/patients/{patient_id}/reports",
    response_model=ReportAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_report(
    patient_id: UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(require_role(UserRole.CLINICIAN))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReportAccepted:
    """Kicks off async generation of a frozen interaction analysis of the patient's active regimen.

    Returns 202 immediately with a PENDING row; poll GET /reports/{id} for
    the result. Generation can involve several LLM calls (one per high-risk
    pair) so it isn't done synchronously in this request.
    """
    await load_accessible_patient(patient_id, current_user, db)

    active_rows = (
        await db.scalars(
            select(PatientRegimen.id)
            .where(PatientRegimen.patient_id == patient_id, PatientRegimen.end_date.is_(None))
            .limit(2)
        )
    ).all()
    if len(active_rows) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least two active medications are required to generate an interaction report",
        )

    report = InteractionReport(patient_id=patient_id, generated_by=current_user.id, status=ReportStatus.PENDING)
    db.add(report)
    await db.flush()
    db.add(_audit(current_user, patient_id, AuditActionType.CREATE, request))
    await db.commit()
    await db.refresh(report)

    background_tasks.add_task(report_generation.generate_report, report.id)

    return ReportAccepted(id=report.id, status=report.status.value.lower())


@router.get("/patients/{patient_id}/reports", response_model=list[ReportListItem])
async def list_reports(
    patient_id: UUID,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ReportListItem]:
    await load_accessible_patient(patient_id, current_user, db)

    stmt = (
        select(InteractionReport)
        .where(InteractionReport.patient_id == patient_id, InteractionReport.deleted_at.is_(None))
        .order_by(InteractionReport.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    reports = (await db.scalars(stmt)).all()
    db.add(_audit(current_user, patient_id, AuditActionType.VIEW, request))
    await db.commit()
    return [_build_list_item(r) for r in reports]


@router.get("/reports/{report_id}", response_model=ReportRead)
async def get_report(
    report_id: UUID,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReportRead:
    report = await _load_report_or_404(report_id, db)
    await load_accessible_patient(report.patient_id, current_user, db)
    db.add(_audit(current_user, report.patient_id, AuditActionType.VIEW, request))
    await db.commit()
    return _build_report_read(report)


@router.get("/reports/{report_id}/pdf")
async def download_report_pdf(
    report_id: UUID,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FileResponse:
    report = await _load_report_or_404(report_id, db)
    await load_accessible_patient(report.patient_id, current_user, db)

    if report.status != ReportStatus.COMPLETE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Report is {report.status.value.lower()}, not ready for download",
        )

    path = Path(report.file_path) if report.file_path else None
    if path is None or not path.exists():
        # The PDF lives on ephemeral disk and can be wiped by a
        # restart/redeploy -- that's routine, not an error. The full
        # analysis is durable in `payload`, so re-rendering costs nothing
        # (no GNN/LLM calls), unlike regenerating the report itself.
        patient = await db.get(PatientProfile, report.patient_id)
        path = pdf_report.render(report, patient)
        report.file_path = str(path)
        await db.commit()

    db.add(_audit(current_user, report.patient_id, AuditActionType.EXPORT, request))
    await db.commit()

    return FileResponse(path, media_type="application/pdf", filename=f"interaction_report_{report.id}.pdf")


@router.delete("/reports/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_report(
    report_id: UUID,
    request: Request,
    current_user: Annotated[User, Depends(require_role(UserRole.CLINICIAN))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Soft-delete: the row (and its audit trail) stays; QR/link access is revoked."""
    report = await _load_report_or_404(report_id, db)
    await load_accessible_patient(report.patient_id, current_user, db)

    report.deleted_at = dt.datetime.now(dt.timezone.utc)
    db.add(_audit(current_user, report.patient_id, AuditActionType.DELETE, request))
    await db.commit()

    if report.file_path:
        Path(report.file_path).unlink(missing_ok=True)
