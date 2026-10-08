"""
SQLAlchemy ORM models for the Automotive Prototype Testing Analytics Platform.
Mapped to PostgreSQL schema defined in app/db/schema.sql.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func

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


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    corporate_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    first_name: Mapped[str] = mapped_column(String(64), nullable=False)
    last_name: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    role: Mapped[UserRole] = mapped_column(default=UserRole.TECHNICIAN, nullable=False)
    department: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    vehicles_created: Mapped[List["Vehicle"]] = relationship(
        back_populates="created_by_user", foreign_keys="Vehicle.created_by"
    )
    test_runs_executed: Mapped[List["TestRun"]] = relationship(
        back_populates="executed_by_user", foreign_keys="TestRun.executed_by"
    )
    test_runs_reviewed: Mapped[List["TestRun"]] = relationship(
        back_populates="reviewed_by_user", foreign_keys="TestRun.reviewed_by"
    )

    def __repr__(self) -> str:
        return f"<User {self.corporate_id} ({self.role})>"


# ---------------------------------------------------------------------------
# Vehicle Classes
# ---------------------------------------------------------------------------
class VehicleClass(Base):
    __tablename__ = "vehicle_classes"

    class_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    class_code: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    segment: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    vehicles: Mapped[List["Vehicle"]] = relationship(back_populates="vehicle_class")
    thresholds: Mapped[List["BenchmarkThreshold"]] = relationship(
        back_populates="vehicle_class"
    )

    def __repr__(self) -> str:
        return f"<VehicleClass {self.class_code}>"


# ---------------------------------------------------------------------------
# Option Packages
# ---------------------------------------------------------------------------
class OptionPackage(Base):
    __tablename__ = "option_packages"

    package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    option_code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    vehicles: Mapped[List["Vehicle"]] = relationship(
        secondary="vehicle_options_bridge", back_populates="option_packages"
    )

    def __repr__(self) -> str:
        return f"<OptionPackage {self.option_code}>"


# ---------------------------------------------------------------------------
# Vehicles
# ---------------------------------------------------------------------------
class Vehicle(Base):
    __tablename__ = "vehicles"
    __table_args__ = (
        CheckConstraint("model_year BETWEEN 2020 AND 2040", name="chk_model_year"),
        CheckConstraint("battery_capacity_kwh >= 0", name="chk_battery_capacity"),
        CheckConstraint("curb_weight_kg > 0", name="chk_curb_weight"),
        Index("idx_vehicles_class_id", "class_id"),
        Index("idx_vehicles_powertrain", "powertrain"),
        Index("idx_vehicles_lifecycle", "lifecycle_status"),
    )

    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    prototype_code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    class_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vehicle_classes.class_id", ondelete="RESTRICT"),
        nullable=False,
    )
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    model_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    powertrain: Mapped[PowertrainType] = mapped_column(nullable=False)
    body_style: Mapped[BodyStyle] = mapped_column(nullable=False)
    drivetrain: Mapped[DriveType] = mapped_column(nullable=False)
    lifecycle_status: Mapped[LifecycleStatus] = mapped_column(
        default=LifecycleStatus.STAGED, nullable=False
    )
    software_build_version: Mapped[str] = mapped_column(String(64), nullable=False)
    battery_capacity_kwh: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2))
    curb_weight_kg: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2))
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
        nullable=False
    )

    # Relationships
    vehicle_class: Mapped["VehicleClass"] = relationship(back_populates="vehicles")
    created_by_user: Mapped["User"] = relationship(
        back_populates="vehicles_created", foreign_keys=[created_by]
    )
    option_packages: Mapped[List["OptionPackage"]] = relationship(
        secondary="vehicle_options_bridge", back_populates="vehicles"
    )
    test_runs: Mapped[List["TestRun"]] = relationship(back_populates="vehicle")

    def __repr__(self) -> str:
        return f"<Vehicle {self.prototype_code} ({self.powertrain})>"


# ---------------------------------------------------------------------------
# Vehicle Options Bridge (many-to-many)
# ---------------------------------------------------------------------------
class VehicleOptionsBridge(Base):
    __tablename__ = "vehicle_options_bridge"

    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vehicles.vehicle_id", ondelete="CASCADE"),
        primary_key=True,
    )
    package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("option_packages.package_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    installed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Performance Criteria Definitions
# ---------------------------------------------------------------------------
class PerformanceCriteriaDefinition(Base):
    __tablename__ = "performance_criteria_definitions"

    criteria_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    criteria_code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    metric_name: Mapped[str] = mapped_column(String(128), nullable=False)
    unit_of_measure: Mapped[str] = mapped_column(String(32), nullable=False)
    category: Mapped[TestCategory] = mapped_column(nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    thresholds: Mapped[List["BenchmarkThreshold"]] = relationship(
        back_populates="criteria"
    )
    result_metrics: Mapped[List["TestResultMetric"]] = relationship(
        back_populates="criteria"
    )

    def __repr__(self) -> str:
        return f"<PerfCriteria {self.criteria_code}>"


# ---------------------------------------------------------------------------
# Benchmark Thresholds
# ---------------------------------------------------------------------------
class BenchmarkThreshold(Base):
    __tablename__ = "benchmark_thresholds"
    __table_args__ = (
        UniqueConstraint(
            "criteria_id", "class_id", "powertrain", "effective_from",
            name="uq_threshold_context",
        ),
        Index("idx_thresholds_criteria_class", "criteria_id", "class_id"),
    )

    threshold_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    criteria_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("performance_criteria_definitions.criteria_id", ondelete="CASCADE"),
        nullable=False,
    )
    class_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vehicle_classes.class_id", ondelete="CASCADE"),
        nullable=False,
    )
    powertrain: Mapped[Optional[PowertrainType]] = mapped_column(nullable=True)
    nominal_target: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    upper_tolerance: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))
    lower_tolerance: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))
    marginal_band_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("5.00")
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[Optional[date]] = mapped_column(Date)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    criteria: Mapped["PerformanceCriteriaDefinition"] = relationship(
        back_populates="thresholds"
    )
    vehicle_class: Mapped["VehicleClass"] = relationship(back_populates="thresholds")

    def __repr__(self) -> str:
        return f"<Threshold {self.threshold_id} target={self.nominal_target}>"


# ---------------------------------------------------------------------------
# Test Facilities
# ---------------------------------------------------------------------------
class TestFacility(Base):
    __tablename__ = "test_facilities"

    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    location: Mapped[Optional[str]] = mapped_column(String(128))
    country: Mapped[str] = mapped_column(String(3), nullable=False)
    facility_type: Mapped[Optional[str]] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    test_runs: Mapped[List["TestRun"]] = relationship(back_populates="facility")

    def __repr__(self) -> str:
        return f"<TestFacility {self.name}>"


# ---------------------------------------------------------------------------
# Test Runs
# ---------------------------------------------------------------------------
class TestRun(Base):
    __tablename__ = "test_runs"
    __table_args__ = (
        CheckConstraint(
            "end_time IS NULL OR end_time >= start_time", name="chk_run_time_window"
        ),
        Index("idx_test_runs_vehicle_id", "vehicle_id"),
        Index("idx_test_runs_category", "category"),
        Index("idx_test_runs_status", "execution_status", "overall_evaluation"),
    )

    test_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_number: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vehicles.vehicle_id", ondelete="RESTRICT"),
        nullable=False,
    )
    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("test_facilities.facility_id", ondelete="RESTRICT"),
        nullable=False,
    )
    category: Mapped[TestCategory] = mapped_column(nullable=False)
    execution_status: Mapped[TestExecutionStatus] = mapped_column(
        default=TestExecutionStatus.SCHEDULED, nullable=False
    )
    overall_evaluation: Mapped[EvaluationStatus] = mapped_column(
        default=EvaluationStatus.PENDING, nullable=False
    )
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    ambient_temp_c: Mapped[Optional[Decimal]] = mapped_column(Numeric(4, 1))
    humidity_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    track_condition: Mapped[Optional[str]] = mapped_column(String(32))
    odometer_km: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    executed_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False
    )
    reviewed_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id")
    )
    review_comments: Mapped[Optional[str]] = mapped_column(Text)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    vehicle: Mapped["Vehicle"] = relationship(back_populates="test_runs")
    facility: Mapped["TestFacility"] = relationship(back_populates="test_runs")
    executed_by_user: Mapped["User"] = relationship(
        back_populates="test_runs_executed", foreign_keys=[executed_by]
    )
    reviewed_by_user: Mapped[Optional["User"]] = relationship(
        back_populates="test_runs_reviewed", foreign_keys=[reviewed_by]
    )
    import_files: Mapped[List["TestImportFile"]] = relationship(
        back_populates="test_run"
    )
    result_metrics: Mapped[List["TestResultMetric"]] = relationship(
        back_populates="test_run"
    )

    def __repr__(self) -> str:
        return f"<TestRun {self.run_number} ({self.overall_evaluation})>"


# ---------------------------------------------------------------------------
# Test Import Files
# ---------------------------------------------------------------------------
class TestImportFile(Base):
    __tablename__ = "test_import_files"
    __table_args__ = (
        CheckConstraint("file_size_bytes > 0", name="chk_file_size"),
        Index("idx_import_files_test_run", "test_run_id"),
        Index("idx_import_files_status", "processing_status"),
    )

    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    test_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("test_runs.test_run_id", ondelete="CASCADE"),
        nullable=False,
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_format: Mapped[str] = mapped_column(String(16), nullable=False)
    file_hash_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    raw_storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    processing_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="QUEUED"
    )
    processing_error: Mapped[Optional[str]] = mapped_column(Text)
    record_count: Mapped[Optional[int]] = mapped_column(BigInteger)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    test_run: Mapped["TestRun"] = relationship(back_populates="import_files")
    uploaded_by_user: Mapped["User"] = relationship()

    def __repr__(self) -> str:
        return f"<ImportFile {self.file_name} ({self.processing_status})>"


# ---------------------------------------------------------------------------
# Test Result Metrics
# ---------------------------------------------------------------------------
class TestResultMetric(Base):
    __tablename__ = "test_result_metrics"
    __table_args__ = (
        UniqueConstraint("test_run_id", "criteria_id", name="uq_test_criteria_pair"),
        Index("idx_metrics_test_run", "test_run_id"),
        Index("idx_metrics_status", "status"),
    )

    metric_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    test_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("test_runs.test_run_id", ondelete="CASCADE"),
        nullable=False,
    )
    criteria_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("performance_criteria_definitions.criteria_id", ondelete="RESTRICT"),
        nullable=False,
    )
    measured_value: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    applied_target: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    upper_limit: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4))
    lower_limit: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4))
    variance_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2))
    status: Mapped[EvaluationStatus] = mapped_column(
        default=EvaluationStatus.PENDING, nullable=False
    )
    engineer_override_status: Mapped[Optional[EvaluationStatus]] = mapped_column()
    override_reason: Mapped[Optional[str]] = mapped_column(Text)
    override_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id")
    )
    override_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    test_run: Mapped["TestRun"] = relationship(back_populates="result_metrics")
    criteria: Mapped["PerformanceCriteriaDefinition"] = relationship(
        back_populates="result_metrics"
    )
    override_by_user: Mapped[Optional["User"]] = relationship(
        foreign_keys=[override_by]
    )

    def __repr__(self) -> str:
        return f"<Metric {self.criteria_id} = {self.measured_value} ({self.status})>"


# ---------------------------------------------------------------------------
# Audit Logs
# ---------------------------------------------------------------------------
class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("idx_audit_table_record", "table_name", "record_id"),
        Index("idx_audit_timestamp", "action_timestamp"),
    )

    audit_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    table_name: Mapped[str] = mapped_column(String(64), nullable=False)
    record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    changed_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id")
    )
    old_data: Mapped[Optional[dict]] = mapped_column(JSONB)
    new_data: Mapped[Optional[dict]] = mapped_column(JSONB)
    ip_address: Mapped[Optional[str]] = mapped_column(INET)
    session_id: Mapped[Optional[str]] = mapped_column(String(128))
    action_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    changed_by_user: Mapped[Optional["User"]] = relationship(
        foreign_keys=[changed_by]
    )

    def __repr__(self) -> str:
        return f"<AuditLog {self.action} on {self.table_name}>"
