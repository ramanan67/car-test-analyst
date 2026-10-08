"""
app/api/v1/routers/analytics.py
Analytics endpoints: run comparison matrix, criteria scoring, sign-off export.
"""
from __future__ import annotations

import os
import uuid
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.dependencies import get_current_user, require_role
from app.core.database import get_db
from app.models.enums import UserRole
from app.models.orm_models import (
    PerformanceCriteriaDefinition,
    TestResultMetric,
    TestRun,
)
from app.schemas.schemas import (
    RunComparisonRequest,
    RunComparisonResponse,
    RunComparisonRow,
)

router = APIRouter(prefix="/analytics", tags=["Analytics & Reporting"])


@router.post("/compare-runs", response_model=RunComparisonResponse)
async def compare_runs(
    payload: RunComparisonRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """
    Side-by-side variance comparison across 2-10 test runs.
    Returns a matrix of criteria -> measured values per run.
    """
    # Load runs
    runs_result = await db.execute(
        select(TestRun).where(TestRun.test_run_id.in_(payload.test_run_ids))
    )
    runs = {r.test_run_id: r for r in runs_result.scalars().all()}
    if len(runs) != len(payload.test_run_ids):
        raise HTTPException(status_code=404, detail="One or more test run IDs not found.")

    # Load metrics for all specified runs
    metrics_q = select(TestResultMetric).where(
        TestResultMetric.test_run_id.in_(payload.test_run_ids)
    )
    if payload.criteria_codes:
        # Join to filter by criteria_code
        metrics_q = metrics_q.join(PerformanceCriteriaDefinition).where(
            PerformanceCriteriaDefinition.criteria_code.in_(payload.criteria_codes)
        )
    metrics_result = await db.execute(
        metrics_q.options(selectinload(TestResultMetric.criteria))
    )
    all_metrics = metrics_result.scalars().all()

    # Build a map: criteria_code -> {run_number -> value}
    criteria_map: Dict[str, Dict[str, Optional[float]]] = {}
    criteria_meta: Dict[str, dict] = {}

    for m in all_metrics:
        code = m.criteria.criteria_code
        run_number = runs[m.test_run_id].run_number
        if code not in criteria_map:
            criteria_map[code] = {}
            criteria_meta[code] = {
                "metric_name": m.criteria.metric_name,
                "unit": m.criteria.unit_of_measure,
            }
        criteria_map[code][run_number] = float(m.measured_value)

    run_numbers = [runs[rid].run_number for rid in payload.test_run_ids]

    rows = [
        RunComparisonRow(
            criteria_code=code,
            metric_name=meta["metric_name"],
            unit=meta["unit"],
            values={rn: criteria_map[code].get(rn) for rn in run_numbers},
        )
        for code, meta in criteria_meta.items()
    ]

    return RunComparisonResponse(runs=run_numbers, rows=rows)


@router.get("/runs/{test_run_id}/export/pdf")
async def export_run_pdf(
    test_run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role(UserRole.TEST_ANALYST)),
):
    """
    Generate and download a PDF engineering sign-off sheet for a test run.
    Includes a cryptographic SHA-256 digest of all metric results.
    """
    run_result = await db.execute(
        select(TestRun)
        .where(TestRun.test_run_id == test_run_id)
        .options(
            selectinload(TestRun.vehicle),
            selectinload(TestRun.facility),
            selectinload(TestRun.executed_by_user),
        )
    )
    run = run_result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Test run not found.")

    metrics_result = await db.execute(
        select(TestResultMetric)
        .where(TestResultMetric.test_run_id == test_run_id)
        .options(selectinload(TestResultMetric.criteria))
    )
    metrics = metrics_result.scalars().all()

    run_data = {
        "run_number": run.run_number,
        "prototype_code": run.vehicle.prototype_code,
        "category": run.category,
        "facility": run.facility.name,
        "start_time": run.start_time,
        "end_time": run.end_time,
        "overall_evaluation": run.overall_evaluation,
        "ambient_temp_c": str(run.ambient_temp_c) if run.ambient_temp_c else None,
        "track_condition": run.track_condition,
        "executed_by": f"{run.executed_by_user.first_name} {run.executed_by_user.last_name}",
        "reviewed_by": None,
    }
    metrics_data = [
        {
            "criteria_code": m.criteria.criteria_code,
            "metric_name": m.criteria.metric_name,
            "measured_value": float(m.measured_value),
            "applied_target": float(m.applied_target),
            "upper_limit": float(m.upper_limit) if m.upper_limit else None,
            "lower_limit": float(m.lower_limit) if m.lower_limit else None,
            "variance_pct": float(m.variance_pct) if m.variance_pct else None,
            "status": m.status,
            "engineer_override_status": m.engineer_override_status,
            "override_reason": m.override_reason,
        }
        for m in metrics
    ]

    import tempfile
    from app.analytics.report_generator import PDFReportGenerator

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        output_path = tmp.name

    gen = PDFReportGenerator()
    digest = gen.generate(run_data, metrics_data, output_path)

    filename = f"signoff_{run.run_number}_{digest[:8]}.pdf"
    return FileResponse(
        path=output_path,
        media_type="application/pdf",
        filename=filename,
        background=None,  # Temp file cleanup handled post-response
    )


@router.get("/runs/{test_run_id}/export/excel")
async def export_run_excel(
    test_run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role(UserRole.TEST_ANALYST)),
):
    """
    Generate and download an Excel engineering workbook for a test run.
    """
    run_result = await db.execute(
        select(TestRun)
        .where(TestRun.test_run_id == test_run_id)
        .options(
            selectinload(TestRun.vehicle),
            selectinload(TestRun.facility),
            selectinload(TestRun.executed_by_user),
        )
    )
    run = run_result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Test run not found.")

    metrics_result = await db.execute(
        select(TestResultMetric)
        .where(TestResultMetric.test_run_id == test_run_id)
        .options(selectinload(TestResultMetric.criteria))
    )
    metrics = metrics_result.scalars().all()

    run_data = {
        "run_number": run.run_number,
        "prototype_code": run.vehicle.prototype_code,
        "category": run.category,
        "facility": run.facility.name,
        "start_time": run.start_time,
        "end_time": run.end_time,
        "overall_evaluation": run.overall_evaluation,
        "ambient_temp_c": str(run.ambient_temp_c) if run.ambient_temp_c else None,
        "track_condition": run.track_condition,
        "executed_by": f"{run.executed_by_user.first_name} {run.executed_by_user.last_name}",
        "reviewed_by": None,
    }
    metrics_data = [
        {
            "criteria_code": m.criteria.criteria_code,
            "metric_name": m.criteria.metric_name,
            "measured_value": float(m.measured_value),
            "applied_target": float(m.applied_target),
            "upper_limit": float(m.upper_limit) if m.upper_limit else None,
            "lower_limit": float(m.lower_limit) if m.lower_limit else None,
            "variance_pct": float(m.variance_pct) if m.variance_pct else None,
            "status": m.status,
            "engineer_override_status": m.engineer_override_status,
            "override_reason": m.override_reason,
        }
        for m in metrics
    ]

    import tempfile
    from app.analytics.report_generator import ExcelReportGenerator

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        output_path = tmp.name

    gen = ExcelReportGenerator()
    digest = gen.generate(run_data, metrics_data, output_path)

    filename = f"signoff_{run.run_number}_{digest[:8]}.xlsx"
    return FileResponse(
        path=output_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
    )
