"""
app/api/v1/routers/vehicles.py
REST endpoints for Vehicle Master Configuration (Module A).
"""
from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.dependencies import get_current_user, require_role
from app.core.database import get_db
from app.models.enums import LifecycleStatus, UserRole
from app.models.orm_models import OptionPackage, Vehicle, VehicleClass, VehicleOptionsBridge
from app.schemas.schemas import (
    VehicleCreate,
    VehicleResponse,
    VehicleUpdate,
    VehicleClassCreate,
    VehicleClassResponse,
)

router = APIRouter(prefix="/vehicles", tags=["Vehicle Configuration"])


# ============================================================
# VEHICLE CLASSES
# ============================================================

@router.get("/classes", response_model=List[VehicleClassResponse])
async def list_vehicle_classes(db: AsyncSession = Depends(get_db)):
    """List all vehicle class definitions."""
    result = await db.execute(select(VehicleClass).order_by(VehicleClass.class_code))
    return result.scalars().all()


@router.post(
    "/classes",
    response_model=VehicleClassResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_vehicle_class(
    payload: VehicleClassCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role(UserRole.ADMIN)),
):
    """Create a new vehicle class (Admin only)."""
    obj = VehicleClass(**payload.model_dump())
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return obj


# ============================================================
# VEHICLES CRUD
# ============================================================

@router.get("", response_model=List[VehicleResponse])
async def list_vehicles(
    class_id: Optional[uuid.UUID] = None,
    lifecycle_status: Optional[LifecycleStatus] = None,
    powertrain: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """
    List prototype vehicles with optional filters.
    Supports pagination.
    """
    q = select(Vehicle).options(
        selectinload(Vehicle.option_packages),
        selectinload(Vehicle.vehicle_class),
    )
    if class_id:
        q = q.where(Vehicle.class_id == class_id)
    if lifecycle_status:
        q = q.where(Vehicle.lifecycle_status == lifecycle_status)
    if powertrain:
        q = q.where(Vehicle.powertrain == powertrain)
    q = q.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    return result.scalars().all()


@router.post("", response_model=VehicleResponse, status_code=status.HTTP_201_CREATED)
async def create_vehicle(
    payload: VehicleCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role(UserRole.TECHNICIAN)),
):
    """
    Register a new prototype vehicle (Module A pre-test intake).
    Only TECHNICIAN+ roles may register prototypes.
    """
    # Check prototype_code uniqueness
    existing = await db.execute(
        select(Vehicle).where(Vehicle.prototype_code == payload.prototype_code)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Prototype code '{payload.prototype_code}' already registered.",
        )

    vehicle_data = payload.model_dump(exclude={"option_package_ids"})
    vehicle = Vehicle(**vehicle_data, created_by=current_user.user_id)
    db.add(vehicle)
    await db.flush()

    # Attach option packages
    for pkg_id in payload.option_package_ids:
        bridge = VehicleOptionsBridge(vehicle_id=vehicle.vehicle_id, package_id=pkg_id)
        db.add(bridge)

    await db.refresh(vehicle, ["option_packages"])
    return vehicle


@router.get("/{vehicle_id}", response_model=VehicleResponse)
async def get_vehicle(
    vehicle_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Retrieve a single prototype vehicle by ID."""
    result = await db.execute(
        select(Vehicle)
        .where(Vehicle.vehicle_id == vehicle_id)
        .options(selectinload(Vehicle.option_packages))
    )
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    return vehicle


@router.patch("/{vehicle_id}", response_model=VehicleResponse)
async def update_vehicle(
    vehicle_id: uuid.UUID,
    payload: VehicleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role(UserRole.TEST_ANALYST)),
):
    """Update vehicle configuration or lifecycle state."""
    result = await db.execute(
        select(Vehicle)
        .where(Vehicle.vehicle_id == vehicle_id)
        .options(selectinload(Vehicle.option_packages))
    )
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found.")

    update_data = payload.model_dump(exclude_unset=True, exclude={"option_package_ids"})
    for field, val in update_data.items():
        setattr(vehicle, field, val)

    if payload.option_package_ids is not None:
        # Clear and re-attach option packages
        await db.execute(
            VehicleOptionsBridge.__table__.delete().where(
                VehicleOptionsBridge.vehicle_id == vehicle_id
            )
        )
        for pkg_id in payload.option_package_ids:
            db.add(VehicleOptionsBridge(vehicle_id=vehicle_id, package_id=pkg_id))

    await db.flush()
    await db.refresh(vehicle, ["option_packages"])
    return vehicle


@router.delete("/{vehicle_id}", status_code=status.HTTP_204_NO_CONTENT)
async def decommission_vehicle(
    vehicle_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(UserRole.LEAD_ENGINEER)),
):
    """
    Decommission a prototype vehicle (soft-delete via lifecycle state).
    Only LEAD_ENGINEER+ may decommission.
    """
    result = await db.execute(select(Vehicle).where(Vehicle.vehicle_id == vehicle_id))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    vehicle.lifecycle_status = LifecycleStatus.DECOMMISSIONED
    await db.flush()
