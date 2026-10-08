"""
app/api/v1/routers/criteria.py
Endpoints for Performance Criteria Definitions and Benchmark Thresholds.
"""
from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user, require_role
from app.core.database import get_db
from app.models.enums import UserRole
from app.models.orm_models import BenchmarkThreshold, PerformanceCriteriaDefinition
from app.schemas.schemas import (
    BenchmarkThresholdCreate,
    BenchmarkThresholdResponse,
    PerformanceCriteriaCreate,
    PerformanceCriteriaResponse,
)

router = APIRouter(prefix="/criteria", tags=["Performance Criteria"])


# ============================================================
# CRITERIA DEFINITIONS
# ============================================================

@router.get("", response_model=List[PerformanceCriteriaResponse])
async def list_criteria(
    category: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """List all performance criteria definitions, optionally filtered by test category."""
    q = select(PerformanceCriteriaDefinition).order_by(
        PerformanceCriteriaDefinition.category,
        PerformanceCriteriaDefinition.criteria_code,
    )
    if category:
        q = q.where(PerformanceCriteriaDefinition.category == category)
    result = await db.execute(q)
    return result.scalars().all()


@router.post("", response_model=PerformanceCriteriaResponse, status_code=status.HTTP_201_CREATED)
async def create_criteria(
    payload: PerformanceCriteriaCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(UserRole.LEAD_ENGINEER)),
):
    """Create a new performance criteria definition (LEAD_ENGINEER+)."""
    existing = await db.execute(
        select(PerformanceCriteriaDefinition).where(
            PerformanceCriteriaDefinition.criteria_code == payload.criteria_code
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Criteria code '{payload.criteria_code}' already exists.",
        )
    obj = PerformanceCriteriaDefinition(**payload.model_dump())
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return obj


# ============================================================
# BENCHMARK THRESHOLDS
# ============================================================

@router.get("/thresholds", response_model=List[BenchmarkThresholdResponse])
async def list_thresholds(
    criteria_id: Optional[uuid.UUID] = None,
    class_id: Optional[uuid.UUID] = None,
    powertrain: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """List benchmark thresholds with optional context filters."""
    q = select(BenchmarkThreshold).order_by(BenchmarkThreshold.effective_from.desc())
    if criteria_id:
        q = q.where(BenchmarkThreshold.criteria_id == criteria_id)
    if class_id:
        q = q.where(BenchmarkThreshold.class_id == class_id)
    if powertrain:
        q = q.where(BenchmarkThreshold.powertrain == powertrain)
    result = await db.execute(q)
    return result.scalars().all()


@router.post(
    "/thresholds",
    response_model=BenchmarkThresholdResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_threshold(
    payload: BenchmarkThresholdCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role(UserRole.LEAD_ENGINEER)),
):
    """
    Define a new benchmark threshold for a (criteria, class, powertrain) context.
    Only LEAD_ENGINEER+ may define thresholds.
    """
    threshold = BenchmarkThreshold(
        **payload.model_dump(),
        created_by=current_user.user_id,
    )
    db.add(threshold)
    await db.flush()
    await db.refresh(threshold)
    return threshold


@router.patch("/thresholds/{threshold_id}", response_model=BenchmarkThresholdResponse)
async def update_threshold(
    threshold_id: uuid.UUID,
    payload: BenchmarkThresholdCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(UserRole.LEAD_ENGINEER)),
):
    """Update an existing benchmark threshold. Creates full replacement."""
    result = await db.execute(
        select(BenchmarkThreshold).where(BenchmarkThreshold.threshold_id == threshold_id)
    )
    threshold = result.scalar_one_or_none()
    if not threshold:
        raise HTTPException(status_code=404, detail="Threshold not found.")
    for field, val in payload.model_dump(exclude_unset=True).items():
        setattr(threshold, field, val)
    await db.flush()
    await db.refresh(threshold)
    return threshold
