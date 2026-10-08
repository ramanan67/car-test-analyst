"""
app/api/v1/routers/test_runs.py
REST endpoints for Test Run management (Module B & C).
Handles run registration, telemetry file ingestion, and evaluation sign-off.
"""
from __future__ import annotations

import hashlib
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.dependencies import get_current_user, require_role
from app.core.config import get_settings
from app.core.database import get_db
from app.models.enums import EvaluationStatus, TestExecutionStatus, UserRole
from app.models.orm_models import TestImportFile, TestRun
from app.schemas.schemas import (
    ImportFileResponse,
    MetricOverrideRequest,
    TestResultMetricResponse,
    TestRunCreate,
    TestRunResponse,
    TestRunUpdate,
)
from app.worker.tasks import process_telemetry_file_task

router = APIRouter(prefix="/test-runs", tags=["Test Runs"])
settings = get_settings()


# ============================================================
# TEST RUN CRUD
# ============================================================

@router.get("", response_model=List[TestRunResponse])
async def list_test_runs(
    vehicle_id: Optional[uuid.UUID] = None,
    facility_id: Optional[uuid.UUID] = None,
    category: Optional[str] = None,
    overall_evaluation: Optional[EvaluationStatus] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """List test runs with optional filters. Results are paginated."""
    q = select(TestRun)
    if vehicle_id:
        q = q.where(TestRun.vehicle_id == vehicle_id)
    if facility_id:
        q = q.where(TestRun.facility_id == facility_id)
    if category:
        q = q.where(TestRun.category == category)
    if overall_evaluation:
        q = q.where(TestRun.overall_evaluation == overall_evaluation)
    q = q.order_by(TestRun.start_time.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    return result.scalars().all()


@router.post("", response_model=TestRunResponse, status_code=status.HTTP_201_CREATED)
async def create_test_run(
    payload: TestRunCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role(UserRole.TECHNICIAN)),
):
    """Register a new test run (pre-test intake)."""
    existing = await db.execute(
        select(TestRun).where(TestRun.run_number == payload.run_number)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Run number '{payload.run_number}' already exists.",
        )
    run = TestRun(**payload.model_dump(), executed_by=current_user.user_id)
    db.add(run)
    await db.flush()
    await db.refresh(run)
    return run


@router.get("/{test_run_id}", response_model=TestRunResponse)
async def get_test_run(
    test_run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Retrieve a single test run by ID."""
    result = await db.execute(
        select(TestRun).where(TestRun.test_run_id == test_run_id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Test run not found.")
    return run


@router.patch("/{test_run_id}", response_model=TestRunResponse)
async def update_test_run(
    test_run_id: uuid.UUID,
    payload: TestRunUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role(UserRole.TEST_ANALYST)),
):
    """Update test run status or review fields."""
    result = await db.execute(
        select(TestRun).where(TestRun.test_run_id == test_run_id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Test run not found.")

    for field, val in payload.model_dump(exclude_unset=True).items():
        setattr(run, field, val)

    # Auto-set reviewer if review_comments added
    if payload.review_comments and not run.reviewed_by:
        run.reviewed_by = current_user.user_id
        from datetime import datetime, timezone
        run.reviewed_at = datetime.now(timezone.utc)

    await db.flush()
    await db.refresh(run)
    return run


# ============================================================
# TELEMETRY FILE INGESTION
# ============================================================

@router.post(
    "/{test_run_id}/files",
    response_model=ImportFileResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_telemetry_file(
    test_run_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role(UserRole.TEST_ANALYST)),
):
    """
    Upload a telemetry file (CSV, Parquet, XLSX, MDF4).
    - SHA-256 hash checked for duplicate ingestion prevention.
    - Files > LARGE_FILE_THRESHOLD_MB are dispatched to async Celery queue.
    - Returns immediately with processing_status=QUEUED.
    """
    # Verify test run exists
    result = await db.execute(
        select(TestRun).where(TestRun.test_run_id == test_run_id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Test run not found.")

    ALLOWED_FORMATS = {"csv", "parquet", "xlsx", "xls", "mf4", "mdf"}
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_FORMATS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file format: .{ext}",
        )

    # Read file and compute SHA-256
    content = await file.read()
    file_hash = hashlib.sha256(content).hexdigest()
    file_size = len(content)

    # Duplicate check
    dup = await db.execute(
        select(TestImportFile).where(TestImportFile.file_hash_sha256 == file_hash)
    )
    if dup.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Identical file already ingested (SHA-256 collision detected).",
        )

    # Persist file record
    format_map = {"mf4": "MDF4", "mdf": "MDF4", "xls": "XLSX"}
    file_format = format_map.get(ext, ext.upper())

    # In production, file content would be uploaded to object storage here
    storage_uri = f"s3://{settings.STORAGE_BUCKET}/{test_run_id}/{file_hash[:8]}_{file.filename}"

    import_file = TestImportFile(
        test_run_id=test_run_id,
        file_name=file.filename,
        file_format=file_format,
        file_hash_sha256=file_hash,
        file_size_bytes=file_size,
        raw_storage_uri=storage_uri,
        processing_status="QUEUED",
        uploaded_by=current_user.user_id,
    )
    db.add(import_file)
    await db.flush()
    await db.refresh(import_file)

    # Dispatch processing task
    process_telemetry_file_task.delay(
        str(import_file.file_id),
        str(test_run_id),
        storage_uri,
        file_format,
    )

    # Update run status to IN_PROGRESS
    if run.execution_status == TestExecutionStatus.SCHEDULED:
        run.execution_status = TestExecutionStatus.IN_PROGRESS
        await db.flush()

    return import_file


@router.get("/{test_run_id}/files", response_model=List[ImportFileResponse])
async def list_test_run_files(
    test_run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """List all telemetry files uploaded for a test run."""
    result = await db.execute(
        select(TestImportFile)
        .where(TestImportFile.test_run_id == test_run_id)
        .order_by(TestImportFile.uploaded_at.desc())
    )
    return result.scalars().all()


# ============================================================
# RESULT METRICS & OVERRIDES
# ============================================================

@router.get("/{test_run_id}/metrics", response_model=List[TestResultMetricResponse])
async def list_run_metrics(
    test_run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Retrieve all evaluated performance metrics for a test run."""
    from app.models.orm_models import TestResultMetric
    result = await db.execute(
        select(TestResultMetric)
        .where(TestResultMetric.test_run_id == test_run_id)
        .order_by(TestResultMetric.evaluated_at)
    )
    return result.scalars().all()


@router.post(
    "/{test_run_id}/metrics/{metric_id}/override",
    response_model=TestResultMetricResponse,
)
async def override_metric(
    test_run_id: uuid.UUID,
    metric_id: uuid.UUID,
    payload: MetricOverrideRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role(UserRole.LEAD_ENGINEER)),
):
    """
    Apply an audited engineering override to a metric result.
    Only LEAD_ENGINEER+ may override. Requires mandatory rationale string.
    """
    from app.models.orm_models import TestResultMetric
    from datetime import datetime, timezone

    result = await db.execute(
        select(TestResultMetric).where(
            TestResultMetric.metric_id == metric_id,
            TestResultMetric.test_run_id == test_run_id,
        )
    )
    metric = result.scalar_one_or_none()
    if not metric:
        raise HTTPException(status_code=404, detail="Metric not found.")

    metric.engineer_override_status = payload.override_status
    metric.override_reason = payload.override_reason
    metric.override_by = current_user.user_id
    metric.override_at = datetime.now(timezone.utc)

    await db.flush()
    await db.refresh(metric)
    return metric
