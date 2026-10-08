"""
tests/unit/test_analytics_engine.py
Unit tests for TelemetryAnalyticsEngine and MetricExtractor.
Covers metric extraction, criteria evaluation, and edge cases.
"""
from __future__ import annotations

import csv
import os
import tempfile
from typing import List

import polars as pl
import pytest

from app.analytics.engine import (
    CriteriaRule,
    EvaluationOutcome,
    MetricExtractor,
    TelemetryAnalyticsEngine,
    TelemetryLoader,
    compute_sha256,
)


# ============================================================
# FIXTURES
# ============================================================

def make_telemetry_df(
    n_samples: int = 5000,
    max_speed: float = 110.0,
    soc_start: float = 90.0,
    soc_end: float = 75.0,
    peak_inv_temp: float = 82.5,
) -> pl.DataFrame:
    """Generate a synthetic in-memory telemetry DataFrame."""
    import math

    timestamps = list(range(0, n_samples * 10, 10))
    speeds = [min(max_speed, i * 0.05) for i in range(n_samples)]
    soc_step = (soc_start - soc_end) / n_samples
    socs = [soc_start - i * soc_step for i in range(n_samples)]
    inv_temps = [40.0 + (peak_inv_temp - 40.0) * (s / max_speed) for s in speeds]
    torques = [max(0, 380.0 - s * 1.8) for s in speeds]
    brakes = [0.0] * n_samples
    lat_g = [0.3 * math.sin(i / 200.0) for i in range(n_samples)]
    cabin_noise = [58.0 + s * 0.08 for s in speeds]

    return pl.DataFrame({
        "timestamp_offset_ms": timestamps,
        "vehicle_speed_kph":   speeds,
        "inverter_temp_c":     inv_temps,
        "battery_soc_pct":     socs,
        "motor_torque_nm":     torques,
        "brake_pressure_bar":  brakes,
        "lateral_g_force":     lat_g,
        "cabin_noise_db":      cabin_noise,
    })


@pytest.fixture
def sample_df():
    return make_telemetry_df()


@pytest.fixture
def sample_rules() -> List[CriteriaRule]:
    return [
        CriteriaRule("ACCEL_0_100_KPH",       nominal_target=6.5,  upper_limit=7.0,  lower_limit=None, marginal_band_pct=5.0),
        CriteriaRule("MAX_INVERTER_TEMP_C",    nominal_target=80.0, upper_limit=90.0, lower_limit=None, marginal_band_pct=5.0),
        CriteriaRule("BATTERY_SOC_DRAIN_PCT",  nominal_target=15.0, upper_limit=18.0, lower_limit=None, marginal_band_pct=5.0),
        CriteriaRule("PEAK_MOTOR_TORQUE_NM",   nominal_target=380.0, upper_limit=None, lower_limit=350.0, marginal_band_pct=5.0),
    ]


# ============================================================
# METRIC EXTRACTOR TESTS
# ============================================================

class TestMetricExtractor:

    def test_accel_0_100_returns_float(self, sample_df):
        result = MetricExtractor.accel_0_100_kph(sample_df)
        assert result is not None
        assert isinstance(result, float)
        assert 0.0 < result < 60.0

    def test_accel_0_100_missing_column_returns_none(self):
        df = pl.DataFrame({"timestamp_offset_ms": [0, 1000], "inverter_temp_c": [40.0, 45.0],
                           "battery_soc_pct": [90.0, 89.0]})
        assert MetricExtractor.accel_0_100_kph(df) is None

    def test_max_inverter_temp(self, sample_df):
        result = MetricExtractor.max_inverter_temp(sample_df)
        assert result is not None
        assert 40.0 <= result <= 200.0

    def test_battery_soc_drain(self, sample_df):
        drain = MetricExtractor.battery_soc_drain(sample_df)
        assert drain is not None
        # We set soc_start=90, soc_end=75 => drain ~ 15
        assert abs(drain - 15.0) < 1.0

    def test_peak_motor_torque(self, sample_df):
        torque = MetricExtractor.peak_motor_torque(sample_df)
        assert torque is not None
        assert torque > 0

    def test_nvh_returns_none_when_no_cruise_band(self):
        df = pl.DataFrame({
            "timestamp_offset_ms": list(range(0, 1000, 10)),
            "vehicle_speed_kph": [50.0] * 100,
            "inverter_temp_c": [60.0] * 100,
            "battery_soc_pct": [80.0] * 100,
            "cabin_noise_db": [65.0] * 100,
        })
        assert MetricExtractor.nvh_cabin_db(df) is None

    def test_extract_all_returns_dict_with_expected_keys(self, sample_df):
        results = MetricExtractor.extract_all(sample_df)
        assert "ACCEL_0_100_KPH" in results
        assert "MAX_INVERTER_TEMP_C" in results
        assert "BATTERY_SOC_DRAIN_PCT" in results
        assert all(isinstance(v, float) for v in results.values())


# ============================================================
# CRITERIA EVALUATION TESTS
# ============================================================

class TestEvaluationEngine:

    def test_pass_outcome(self):
        rules = [CriteriaRule("ACCEL_0_100_KPH", 6.5, upper_limit=7.0, lower_limit=None)]
        outcomes = TelemetryAnalyticsEngine.evaluate_run({"ACCEL_0_100_KPH": 6.8}, rules)
        assert len(outcomes) == 1
        assert outcomes[0].status == "PASS"

    def test_fail_outcome(self):
        rules = [CriteriaRule("ACCEL_0_100_KPH", 6.5, upper_limit=7.0, lower_limit=None, marginal_band_pct=5.0)]
        # 8.0 exceeds 7.0 limit AND 7.0 * 1.05 = 7.35 marginal band
        outcomes = TelemetryAnalyticsEngine.evaluate_run({"ACCEL_0_100_KPH": 8.0}, rules)
        assert outcomes[0].status == "FAIL"

    def test_marginal_deviation_just_beyond_limit(self):
        rules = [CriteriaRule("ACCEL_0_100_KPH", 6.5, upper_limit=7.0, lower_limit=None, marginal_band_pct=5.0)]
        # 7.2 is beyond 7.0 but within 7.0 * 1.05 = 7.35
        outcomes = TelemetryAnalyticsEngine.evaluate_run({"ACCEL_0_100_KPH": 7.2}, rules)
        assert outcomes[0].status == "MARGINAL_DEVIATION"

    def test_variance_pct_calculated_correctly(self):
        rules = [CriteriaRule("MAX_INVERTER_TEMP_C", 80.0, upper_limit=90.0, lower_limit=None)]
        outcomes = TelemetryAnalyticsEngine.evaluate_run({"MAX_INVERTER_TEMP_C": 84.0}, rules)
        expected_variance = (84.0 - 80.0) / 80.0 * 100.0
        assert abs(outcomes[0].variance_pct - expected_variance) < 0.01

    def test_missing_metric_skipped(self, sample_rules):
        # Only provide one metric; others should be skipped not errored
        outcomes = TelemetryAnalyticsEngine.evaluate_run({"ACCEL_0_100_KPH": 6.5}, sample_rules)
        assert len(outcomes) == 1
        assert outcomes[0].criteria_code == "ACCEL_0_100_KPH"

    def test_aggregate_status_fail_takes_priority(self):
        outcomes = [
            EvaluationOutcome("A", 1.0, 1.0, None, None, 0.0, "PASS"),
            EvaluationOutcome("B", 1.0, 1.0, None, None, 10.0, "FAIL"),
            EvaluationOutcome("C", 1.0, 1.0, None, None, 3.0, "MARGINAL_DEVIATION"),
        ]
        assert TelemetryAnalyticsEngine.aggregate_overall_status(outcomes) == "FAIL"

    def test_aggregate_status_marginal_with_no_fail(self):
        outcomes = [
            EvaluationOutcome("A", 1.0, 1.0, None, None, 0.0, "PASS"),
            EvaluationOutcome("B", 1.0, 1.0, None, None, 3.0, "MARGINAL_DEVIATION"),
        ]
        assert TelemetryAnalyticsEngine.aggregate_overall_status(outcomes) == "MARGINAL_DEVIATION"

    def test_aggregate_empty_returns_pending(self):
        assert TelemetryAnalyticsEngine.aggregate_overall_status([]) == "PENDING"


# ============================================================
# SHA-256 HASH TESTS
# ============================================================

class TestSHA256:

    def test_consistent_hash_same_content(self, tmp_path):
        f = tmp_path / "test.csv"
        f.write_text("timestamp,speed\n0,0\n10,5\n")
        h1 = compute_sha256(f)
        h2 = compute_sha256(f)
        assert h1 == h2
        assert len(h1) == 64

    def test_different_files_different_hash(self, tmp_path):
        f1 = tmp_path / "a.csv"
        f2 = tmp_path / "b.csv"
        f1.write_text("data_a")
        f2.write_text("data_b")
        assert compute_sha256(f1) != compute_sha256(f2)


# ============================================================
# TELEMETRY LOADER TESTS
# ============================================================

class TestTelemetryLoader:

    def test_load_csv_valid(self, tmp_path):
        f = tmp_path / "telemetry.csv"
        rows = ["timestamp_offset_ms,vehicle_speed_kph,inverter_temp_c,battery_soc_pct"]
        for i in range(100):
            rows.append(f"{i*10},{min(100, i*1.2):.2f},{45+i*0.3:.2f},{90-i*0.1:.3f}")
        f.write_text("\n".join(rows))
        df = TelemetryLoader.load(f, resample_ms=100)
        assert "timestamp_offset_ms" in df.columns
        assert len(df) > 0

    def test_missing_required_column_raises(self, tmp_path):
        f = tmp_path / "bad.csv"
        f.write_text("timestamp_offset_ms,vehicle_speed_kph\n0,0\n10,5\n")
        with pytest.raises(ValueError, match="missing required channels"):
            TelemetryLoader.load(f)

    def test_unsupported_format_raises(self, tmp_path):
        f = tmp_path / "trace.bin"
        f.write_bytes(b"\x00\x01\x02")
        with pytest.raises(ValueError, match="Unsupported telemetry format"):
            TelemetryLoader.load(f)
