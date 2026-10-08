"""
app/schemas/schemas.py

Pydantic v2 request/response schemas for the Automotive Testing Analytics Platform API.
Provides full validation, serialisation, and OpenAPI documentation models.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.enums import (
    BodyStyle,
    DriveType,
    EvaluationStatus,
    FileFormat,
    LifecycleStatus,
    PowertrainType,
    TestCategory,
    TestExecutionStatus,
    UserRole,
)


# ============================================================
# Base model with common config
# ============================================================

class APIBaseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


# ============================================================
# AUTH
# ============================================================

class LoginRequest(BaseModel):
    corporate_id: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=8)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


# ============================================================
# USERS
# ============================================================

class UserCreate(BaseModel):
    corporate_id: str = Field(..., min_length=3, max_length=32)
    first_name: str = Field(..., min_length=1, max_length=64)
    last_name: str = Field(..., min_length=1, max_length=64)
    email: EmailStr
    role: UserRole = UserRole.TECHNICIAN
    department: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=8, max_length=128)


class UserUpdate(BaseModel):
    first_name: Optional[str] = Field(None, min_length=1, max_length=64)
    last_name: Optional[str] = Field(None, min_length=1, max_length=64)
    email: Optional[EmailStr] = None
    role: Optional[UserRole] = None
    department: Optional[str] = Field(None, min_length=1, max_length=100)
    is_active: Optional[bool] = None


class UserResponse(APIBaseModel):
    user_id: uuid.UUID
    corporate_id: str
    first_name: str
    last_name: str
    email: str
    role: UserRole
    department: str
    is_active: bool
    last_login_at: Optional[datetime]
    created_at: datetime


# ============================================================
# VEHICLE CLASSES
# ============================================================

class VehicleClassCreate(BaseModel):
    class_code: str = Field(..., min_length=1, max_length=16)
    segment: str = Field(..., min_length=1, max_length=32)
    description: Optional[str] = None


class VehicleClassResponse(APIBaseModel):
    class_id: uuid.UUID
    class_code: str
    segment: str
    description: Optional[str]
    created_at: datetime


# ============================================================
# OPTION PACKAGES
# ============================================================

class OptionPackageCreate(BaseModel):
    option_code: str = Field(..., min_length=1, max_length=32)
    name: str = Field(..., min_length=1, max_length=128)
    category: str = Field(..., min_length=1, max_length=64)
    description: Optional[str] = None


class OptionPackageResponse(APIBaseModel):
    package_id: uuid.UUID
    option_code: str
    name: str
    category: str
    description: Optional[str]
    created_at: datetime


# ============================================================
# VEHICLES
# ============================================================

class VehicleCreate(BaseModel):
    prototype_code: str = Field(..., min_length=1, max_length=64)
    class_id: uuid.UUID
    model_name: str = Field(..., min_length=1, max_length=64)
    model_year: int = Field(..., ge=2020, le=2040)
    powertrain: PowertrainType
    body_style: BodyStyle
    drivetrain: DriveType
    software_build_version: str = Field(..., min_length=1, max_length=64)
    battery_capacity_kwh: Optional[Decimal] = Field(None, ge=0)
    curb_weight_kg: Optional[Decimal] = Field(None, gt=0)
    option_package_ids: List[uuid.UUID] = Field(default_factory=list)


class VehicleUpdate(BaseModel):
    model_name: Optional[str] = Field(None, min_length=1, max_length=64)
    lifecycle_status: Optional[LifecycleStatus] = None
    software_build_version: Optional[str] = Field(None, min_length=1, max_length=64)
    battery_capacity_kwh: Optional[Decimal] = Field(None, ge=0)
    curb_weight_kg: Optional[Decimal] = Field(None, gt=0)
    option_package_ids: Optional[List[uuid.UUID]] = None


class VehicleResponse(APIBaseModel):
    vehicle_id: uuid.UUID
    prototype_code: str
    class_id: uuid.UUID
    model_name: str
    model_year: int
    powertrain: PowertrainType
    body_style: BodyStyle
    drivetrain: DriveType
    lifecycle_status: LifecycleStatus
    software_build_version: str
    battery_capacity_kwh: Optional[Decimal]
    curb_weight_kg: Optional[Decimal]
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    option_packages: List[OptionPackageResponse] = Field(default_factory=list)


# ============================================================
# PERFORMANCE CRITERIA
# ============================================================

class PerformanceCriteriaCreate(BaseModel):
    criteria_code: str = Field(..., min_length=1, max_length=64)
    metric_name: str = Field(..., min_length=1, max_length=128)
    unit_of_measure: str = Field(..., min_length=1, max_length=32)
    category: TestCategory
    description: Optional[str] = None


class PerformanceCriteriaResponse(APIBaseModel):
    criteria_id: uuid.UUID
    criteria_code: str
    metric_name: str
    unit_of_measure: str
    category: TestCategory
    description: Optional[str]
    created_at: datetime


# ============================================================
# BENCHMARK THRESHOLDS
# ============================================================

class BenchmarkThresholdCreate(BaseModel):
    criteria_id: uuid.UUID
    class_id: uuid.UUID
    powertrain: Optional[PowertrainType] = None
    nominal_target: Decimal = Field(..., description="Nominal engineering target value")
    upper_tolerance: Optional[Decimal] = None
    lower_tolerance: Optional[Decimal] = None
    marginal_band_pct: Decimal = Field(
        default=Decimal("5.00"),
        ge=0, le=50,
        description="% beyond hard limit that still classifies as MARGINAL_DEVIATION",
    )
    effective_from: date
    effective_to: Optional[date] = None


class BenchmarkThresholdResponse(APIBaseModel):
    threshold_id: uuid.UUID
    criteria_id: uuid.UUID
    class_id: uuid.UUID
    powertrain: Optional[PowertrainType]
    nominal_target: Decimal
    upper_tolerance: Optional[Decimal]
    lower_tolerance: Optional[Decimal]
    marginal_band_pct: Decimal
    effective_from: date
    effective_to: Optional[date]
    created_by: uuid.UUID
    created_at: datetime


# ============================================================
# TEST FACILITIES
# ============================================================

class TestFacilityCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    location: Optional[str] = Field(None, max_length=128)
    country: str = Field(..., min_length=2, max_length=3)
    facility_type: Optional[str] = Field(None, max_length=64)


class TestFacilityResponse(APIBaseModel):
    facility_id: uuid.UUID
    name: str
    location: Optional[str]
    country: str
    facility_type: Optional[str]
    is_active: bool
    created_at: datetime


# ============================================================
# TEST RUNS
# ============================================================

class TestRunCreate(BaseModel):
    run_number: str = Field(..., min_length=1, max_length=64)
    vehicle_id: uuid.UUID
    facility_id: uuid.UUID
    category: TestCategory
    start_time: datetime
    end_time: Optional[datetime] = None
    ambient_temp_c: Optional[Decimal] = Field(None, ge=-60, le=80)
    humidity_pct: Optional[Decimal] = Field(None, ge=0, le=100)
    track_condition: Optional[str] = Field(None, max_length=32)
    odometer_km: Optional[Decimal] = Field(None, ge=0)
    notes: Optional[str] = None

    @field_validator("end_time")
    @classmethod
    def end_after_start(cls, v: Optional[datetime], info) -> Optional[datetime]:
        if v and "start_time" in info.data and v < info.data["start_time"]:
            raise ValueError("end_time must be after start_time")
        return v


class TestRunUpdate(BaseModel):
    execution_status: Optional[TestExecutionStatus] = None
    overall_evaluation: Optional[EvaluationStatus] = None
    end_time: Optional[datetime] = None
    ambient_temp_c: Optional[Decimal] = None
    track_condition: Optional[str] = None
    odometer_km: Optional[Decimal] = None
    notes: Optional[str] = None
    review_comments: Optional[str] = None


class TestRunResponse(APIBaseModel):
    test_run_id: uuid.UUID
    run_number: str
    vehicle_id: uuid.UUID
    facility_id: uuid.UUID
    category: TestCategory
    execution_status: TestExecutionStatus
    overall_evaluation: EvaluationStatus
    start_time: datetime
    end_time: Optional[datetime]
    ambient_temp_c: Optional[Decimal]
    humidity_pct: Optional[Decimal]
    track_condition: Optional[str]
    odometer_km: Optional[Decimal]
    notes: Optional[str]
    executed_by: uuid.UUID
    reviewed_by: Optional[uuid.UUID]
    review_comments: Optional[str]
    reviewed_at: Optional[datetime]
    created_at: datetime


# ============================================================
# IMPORT FILES
# ============================================================

class ImportFileResponse(APIBaseModel):
    file_id: uuid.UUID
    test_run_id: uuid.UUID
    file_name: str
    file_format: str
    file_hash_sha256: str
    file_size_bytes: int
    raw_storage_uri: str
    processing_status: str
    processing_error: Optional[str]
    record_count: Optional[int]
    processed_at: Optional[datetime]
    uploaded_by: uuid.UUID
    uploaded_at: datetime


# ============================================================
# RESULT METRICS
# ============================================================

class MetricOverrideRequest(BaseModel):
    override_status: EvaluationStatus
    override_reason: str = Field(
        ..., min_length=10, max_length=1000,
        description="Mandatory engineering rationale for the override (min 10 chars)",
    )


class TestResultMetricResponse(APIBaseModel):
    metric_id: uuid.UUID
    test_run_id: uuid.UUID
    criteria_id: uuid.UUID
    measured_value: Decimal
    applied_target: Decimal
    upper_limit: Optional[Decimal]
    lower_limit: Optional[Decimal]
    variance_pct: Optional[Decimal]
    status: EvaluationStatus
    engineer_override_status: Optional[EvaluationStatus]
    override_reason: Optional[str]
    override_by: Optional[uuid.UUID]
    override_at: Optional[datetime]
    evaluated_at: datetime


# ============================================================
# RUN COMPARISON (analytics)
# ============================================================

class RunComparisonRequest(BaseModel):
    test_run_ids: List[uuid.UUID] = Field(..., min_length=2, max_length=10)
    criteria_codes: Optional[List[str]] = None  # None means all shared criteria


class RunComparisonRow(BaseModel):
    criteria_code: str
    metric_name: str
    unit: str
    values: dict  # run_number -> measured_value


class RunComparisonResponse(BaseModel):
    runs: List[str]  # run_number list
    rows: List[RunComparisonRow]


# ============================================================
# AUDIT LOG
# ============================================================

class AuditLogResponse(APIBaseModel):
    audit_id: int
    table_name: str
    record_id: uuid.UUID
    action: str
    changed_by: Optional[uuid.UUID]
    old_data: Optional[dict]
    new_data: Optional[dict]
    ip_address: Optional[str]
    action_timestamp: datetime


# ============================================================
# PAGINATION
# ============================================================

class PaginatedResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list
