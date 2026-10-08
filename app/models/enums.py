"""
Domain enumerations mirroring PostgreSQL enum types.
Kept in sync with app/db/schema.sql.
"""
from enum import Enum


class PowertrainType(str, Enum):
    ICE = "ICE"
    MHEV = "MHEV"
    PHEV = "PHEV"
    BEV = "BEV"
    FCEV = "FCEV"


class BodyStyle(str, Enum):
    SEDAN = "SEDAN"
    ESTATE = "ESTATE"
    COUPE = "COUPE"
    SUV = "SUV"
    CABRIOLET = "CABRIOLET"


class DriveType(str, Enum):
    RWD = "RWD"
    FWD = "FWD"
    AWD_4MATIC = "AWD_4MATIC"


class LifecycleStatus(str, Enum):
    STAGED = "STAGED"
    ACTIVE_TESTING = "ACTIVE_TESTING"
    DECOMMISSIONED = "DECOMMISSIONED"


class TestCategory(str, Enum):
    DYNO_POWERTRAIN = "DYNO_POWERTRAIN"
    TRACK_DYNAMICS = "TRACK_DYNAMICS"
    NVH = "NVH"
    THERMAL_HVAC = "THERMAL_HVAC"
    BATTERY_CYCLE = "BATTERY_CYCLE"
    ADAS_SAFETY = "ADAS_SAFETY"


class TestExecutionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    INVALIDATED = "INVALIDATED"


class EvaluationStatus(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"
    MARGINAL_DEVIATION = "MARGINAL_DEVIATION"


class UserRole(str, Enum):
    TECHNICIAN = "TECHNICIAN"
    TEST_ANALYST = "TEST_ANALYST"
    LEAD_ENGINEER = "LEAD_ENGINEER"
    ADMIN = "ADMIN"
    VIEWER = "VIEWER"


class FileFormat(str, Enum):
    CSV = "CSV"
    PARQUET = "PARQUET"
    XLSX = "XLSX"
    MDF4 = "MDF4"
    CAN = "CAN"
