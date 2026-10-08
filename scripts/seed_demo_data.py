"""
scripts/seed_demo_data.py
Populates sample vehicles, test facilities, baseline thresholds,
and test runs into the database.
"""
import asyncio
import uuid
from datetime import datetime, timezone, date
from decimal import Decimal

from app.core.database import get_db_context
from app.core.security import hash_password
from app.models.enums import (
    UserRole,
    PowertrainType,
    BodyStyle,
    DriveType,
    LifecycleStatus,
    TestCategory,
    TestExecutionStatus,
    EvaluationStatus,
)
from app.models.orm_models import (
    User,
    VehicleClass,
    OptionPackage,
    Vehicle,
    VehicleOptionsBridge,
    TestFacility,
    PerformanceCriteriaDefinition,
    BenchmarkThreshold,
    TestRun,
)

async def seed():
    async with get_db_context() as db:
        # 1. Admin & Lead Engineer Users
        admin_user = User(
            corporate_id="MB001092",
            first_name="Hermann",
            last_name="Lang",
            email="h.lang@mercedes-benz.corp",
            role=UserRole.ADMIN,
            department="RD/Vehicle-Testing",
            password_hash=hash_password("admin_pass_2026"),
        )
        lead_eng = User(
            corporate_id="MB004581",
            first_name="Bertha",
            last_name="Benz",
            email="b.benz@mercedes-benz.corp",
            role=UserRole.LEAD_ENGINEER,
            department="RD/Powertrain-Validation",
            password_hash=hash_password("lead_eng_2026"),
        )
        db.add_all([admin_user, lead_eng])
        await db.flush()

        # 2. Vehicle Class
        eqs_class = VehicleClass(
            class_code="EQS",
            segment="Full-Size BEV Luxury",
            description="EVA2 Architecture High-Performance Electric Saloon",
        )
        db.add(eqs_class)
        await db.flush()

        # 3. Option Package
        amg_package = OptionPackage(
            option_code="P31-AMG-LINE",
            name="AMG Line Exterior & Ceramic Braking System",
            category="CHASSIS_BRAKES",
            description="Upgraded 6-piston fixed front callipers and composite carbon-ceramic discs",
        )
        db.add(amg_package)
        await db.flush()

        # 4. Vehicle Prototype
        prototype = Vehicle(
            prototype_code="EQS-580-PROTO-042",
            class_id=eqs_class.class_id,
            model_name="EQS 580 4MATIC Sedan",
            model_year=2026,
            powertrain=PowertrainType.BEV,
            body_style=BodyStyle.SEDAN,
            drivetrain=DriveType.AWD_4MATIC,
            lifecycle_status=LifecycleStatus.ACTIVE_TESTING,
            software_build_version="SW-PROD-26.04-RC2",
            battery_capacity_kwh=Decimal("107.80"),
            curb_weight_kg=Decimal("2585.00"),
            created_by=lead_eng.user_id,
        )
        db.add(prototype)
        await db.flush()

        bridge = VehicleOptionsBridge(vehicle_id=prototype.vehicle_id, package_id=amg_package.package_id)
        db.add(bridge)

        # 5. Facility
        immendingen = TestFacility(
            name="Immendingen Test and Technology Center",
            location="Immendingen, Baden-Wurttemberg",
            country="DEU",
            facility_type="PROVING_GROUND",
            is_active=True,
        )
        db.add(immendingen)
        await db.flush()

        # 6. Criteria Definitions & Benchmarks
        accel_crit = PerformanceCriteriaDefinition(
            criteria_code="ACCEL_0_100_KPH",
            metric_name="0-100 km/h Launch Time",
            unit_of_measure="s",
            category=TestCategory.DYNO_POWERTRAIN,
            description="Standing start 0 to 100 km/h acceleration interval",
        )
        inv_crit = PerformanceCriteriaDefinition(
            criteria_code="MAX_INVERTER_TEMP_C",
            metric_name="Peak Inverter Temperature",
            unit_of_measure="degC",
            category=TestCategory.THERMAL_HVAC,
            description="Maximum silicon carbide power inverter operational temperature",
        )
        db.add_all([accel_crit, inv_crit])
        await db.flush()

        thresh_accel = BenchmarkThreshold(
            criteria_id=accel_crit.criteria_id,
            class_id=eqs_class.class_id,
            powertrain=PowertrainType.BEV,
            nominal_target=Decimal("4.3000"),
            upper_tolerance=Decimal("4.6000"),
            lower_tolerance=Decimal("3.8000"),
            marginal_band_pct=Decimal("5.00"),
            effective_from=date(2026, 1, 1),
            created_by=lead_eng.user_id,
        )
        thresh_inv = BenchmarkThreshold(
            criteria_id=inv_crit.criteria_id,
            class_id=eqs_class.class_id,
            powertrain=PowertrainType.BEV,
            nominal_target=Decimal("75.0000"),
            upper_tolerance=Decimal("85.0000"),
            lower_tolerance=None,
            marginal_band_pct=Decimal("5.00"),
            effective_from=date(2026, 1, 1),
            created_by=lead_eng.user_id,
        )
        db.add_all([thresh_accel, thresh_inv])
        await db.flush()

        # 7. Test Run
        run = TestRun(
            run_number="TR-IMM-2026-0089",
            vehicle_id=prototype.vehicle_id,
            facility_id=immendingen.facility_id,
            category=TestCategory.DYNO_POWERTRAIN,
            execution_status=TestExecutionStatus.COMPLETED,
            overall_evaluation=EvaluationStatus.PASS,
            start_time=datetime(2026, 10, 8, 8, 30, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 10, 8, 9, 15, 0, tzinfo=timezone.utc),
            ambient_temp_c=Decimal("18.5"),
            humidity_pct=Decimal("45.00"),
            track_condition="DRY_ASPHALT",
            odometer_km=Decimal("4120.50"),
            notes="Baseline 0-100 dyno acceleration verification on Immendingen Oval",
            executed_by=lead_eng.user_id,
        )
        db.add(run)
        await db.flush()

        print("Successfully seeded reference test data!")

if __name__ == "__main__":
    asyncio.run(seed())
