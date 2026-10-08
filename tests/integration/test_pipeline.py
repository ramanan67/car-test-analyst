"""
tests/integration/test_pipeline.py
Integration tests validating the end-to-end ingestion, criteria scoring,
and evaluation pipeline across synthetic dataset records.
"""
import pytest
import tempfile
import polars as pl
from pathlib import Path
from app.analytics.engine import (
    TelemetryAnalyticsEngine,
    CriteriaRule,
    compute_sha256,
)

def test_full_pipeline_synthetic_run():
    # 1. Create realistic synthetic telemetry log
    n_points = 1000
    times = [i * 10 for i in range(n_points)] # 0 to 9.99s
    # Accelerate 0 to 105 km/h over 5.5s
    speeds = [min(105.0, (i / 550.0) * 100.0) if i < 550 else 105.0 for i in range(n_points)]
    inverter_temps = [35.0 + (s / 105.0) * 45.0 for s in speeds] # max 80.0 C
    battery_soc = [98.0 - (i / n_points) * 4.0 for i in range(n_points)] # start 98%, end 94% -> drain 4%

    df = pl.DataFrame({
        "timestamp_offset_ms": times,
        "vehicle_speed_kph": speeds,
        "inverter_temp_c": inverter_temps,
        "battery_soc_pct": battery_soc,
    })

    with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False) as tmp:
        df.write_csv(tmp.name)
        tmp_path = tmp.name

    try:
        # Check cryptographic hashing
        digest = compute_sha256(tmp_path)
        assert len(digest) == 64

        # Rules
        rules = [
            CriteriaRule(criteria_code="ACCEL_0_100_KPH", nominal_target=5.5, upper_limit=6.0, lower_limit=None),
            CriteriaRule(criteria_code="MAX_INVERTER_TEMP_C", nominal_target=75.0, upper_limit=85.0, lower_limit=None),
            CriteriaRule(criteria_code="BATTERY_SOC_DRAIN_PCT", nominal_target=3.5, upper_limit=5.0, lower_limit=None),
        ]

        engine = TelemetryAnalyticsEngine(resample_ms=10)
        summary = engine.process_file(tmp_path, rules)

        assert summary.record_count > 0
        assert summary.file_hash_sha256 == digest
        assert len(summary.errors) == 0
        assert "ACCEL_0_100_KPH" in summary.metrics
        assert "MAX_INVERTER_TEMP_C" in summary.metrics
        assert "BATTERY_SOC_DRAIN_PCT" in summary.metrics

        # Verify evaluations
        outcomes_map = {o.criteria_code: o for o in summary.outcomes}
        assert outcomes_map["ACCEL_0_100_KPH"].status == "PASS"
        assert outcomes_map["MAX_INVERTER_TEMP_C"].status == "PASS"
        assert outcomes_map["BATTERY_SOC_DRAIN_PCT"].status == "PASS"

        overall = engine.aggregate_overall_status(summary.outcomes)
        assert overall == "PASS"

    finally:
        Path(tmp_path).unlink(missing_ok=True)
