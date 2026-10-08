"""
automotive_processor.py  /  app/analytics/engine.py

High-throughput telemetry metric aggregation and engineering criteria evaluation.
Built on Polars for vectorised, out-of-core processing.

Key capabilities:
  - Multi-format ingestion  : CSV, Parquet, XLSX, MDF4 (via asammdf)
  - Metric extraction       : 0-100 acceleration, thermal peaks, SoC drain, torque, NVH, braking
  - Criteria evaluation     : PASS / MARGINAL_DEVIATION / FAIL with configurable marginal bands
  - Timestamp normalisation : resampling to uniform 10 ms or 100 ms slices
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import polars as pl

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Transfer Objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CriteriaRule:
    """Benchmark rule loaded from the benchmark_thresholds table."""
    criteria_code: str
    nominal_target: float
    upper_limit: Optional[float]
    lower_limit: Optional[float]
    marginal_band_pct: float = 5.0  # % beyond hard limits that still counts as marginal


@dataclass(frozen=True)
class EvaluationOutcome:
    """Single metric evaluation result ready for DB persistence."""
    criteria_code: str
    measured_value: float
    target_value: float
    upper_limit: Optional[float]
    lower_limit: Optional[float]
    variance_pct: float
    status: str  # 'PASS' | 'MARGINAL_DEVIATION' | 'FAIL'


@dataclass
class IngestionSummary:
    """Aggregate result of a full file ingestion cycle."""
    file_path: str
    file_hash_sha256: str
    record_count: int
    metrics: Dict[str, float] = field(default_factory=dict)
    outcomes: List[EvaluationOutcome] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Format Loaders
# ---------------------------------------------------------------------------

class TelemetryLoader:
    """Reads raw telemetry files into a canonical Polars DataFrame."""

    REQUIRED_COLUMNS = {
        "timestamp_offset_ms",
        "vehicle_speed_kph",
        "inverter_temp_c",
        "battery_soc_pct",
    }

    @classmethod
    def load(cls, path: str | Path, resample_ms: int = 10) -> pl.DataFrame:
        """
        Load and normalise a telemetry file.

        Args:
            path        : Path to telemetry file.
            resample_ms : Target resampling interval in milliseconds.

        Returns:
            Normalised Polars DataFrame with uniform time axis.
        """
        p = Path(path)
        suffix = p.suffix.lower()

        if suffix == ".csv":
            df = cls._load_csv(p)
        elif suffix == ".parquet":
            df = cls._load_parquet(p)
        elif suffix in (".xlsx", ".xls"):
            df = cls._load_excel(p)
        elif suffix in (".mf4", ".mdf"):
            df = cls._load_mdf4(p)
        else:
            raise ValueError(f"Unsupported telemetry format: {suffix}")

        cls._validate_schema(df)
        df = cls._normalise_types(df)
        df = cls._resample(df, resample_ms)
        return df

    # -- private loaders --

    @staticmethod
    def _load_csv(path: Path) -> pl.DataFrame:
        return pl.read_csv(
            path,
            infer_schema_length=2000,
            null_values=["", "NA", "N/A", "null", "NaN"],
            try_parse_dates=False,
        )

    @staticmethod
    def _load_parquet(path: Path) -> pl.DataFrame:
        return pl.read_parquet(path)

    @staticmethod
    def _load_excel(path: Path) -> pl.DataFrame:
        try:
            import openpyxl  # noqa: F401
            import pandas as pd
            pf = pd.read_excel(path, engine="openpyxl")
            return pl.from_pandas(pf)
        except ImportError as exc:
            raise ImportError(
                "openpyxl and pandas are required for XLSX ingestion."
            ) from exc

    @staticmethod
    def _load_mdf4(path: Path) -> pl.DataFrame:
        """
        MDF4 / MF4 (ASAM Measurement Data Format v4) loader via asammdf.
        Extracts standard automotive channel names.
        """
        try:
            from asammdf import MDF  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "asammdf is required for MDF4 ingestion. pip install asammdf"
            ) from exc

        mdf = MDF(str(path))
        channel_map = {
            "timestamp_offset_ms": ["timestamps", "t", "time_ms"],
            "vehicle_speed_kph": ["vehicle_speed", "v_vehicle", "VehicleSpeed"],
            "inverter_temp_c": ["inverter_temp", "T_inverter", "InverterTemperature"],
            "battery_soc_pct": ["battery_soc", "HV_SoC", "BattSOC"],
            "motor_torque_nm": ["motor_torque", "T_motor", "MotorTorque"],
            "brake_pressure_bar": ["brake_pressure", "p_brake", "BrakePressure"],
            "lateral_g_force": ["lateral_accel", "a_lat", "LateralAcceleration"],
            "cabin_noise_db": ["cabin_noise", "NVH_cabin", "CabinNoiseLevel"],
        }

        records: dict[str, list] = {}
        for canonical, aliases in channel_map.items():
            for alias in aliases:
                try:
                    sig = mdf.get(alias)
                    if canonical == "timestamp_offset_ms":
                        records[canonical] = (sig.timestamps * 1000.0).tolist()
                    else:
                        records[canonical] = sig.samples.tolist()
                    break
                except Exception:  # noqa: BLE001
                    continue

        mdf.close()
        return pl.DataFrame(records)

    @classmethod
    def _validate_schema(cls, df: pl.DataFrame) -> None:
        missing = cls.REQUIRED_COLUMNS - set(df.columns)
        if missing:
            raise ValueError(
                f"Telemetry file missing required channels: {sorted(missing)}"
            )

    @staticmethod
    def _normalise_types(df: pl.DataFrame) -> pl.DataFrame:
        """Cast key columns to canonical float64 and ensure timestamp is integer ms."""
        casts = [
            pl.col("timestamp_offset_ms").cast(pl.Int64),
            pl.col("vehicle_speed_kph").cast(pl.Float64),
            pl.col("inverter_temp_c").cast(pl.Float64),
            pl.col("battery_soc_pct").cast(pl.Float64),
        ]
        # Optional channels
        for optional_col in (
            "motor_torque_nm", "brake_pressure_bar", "lateral_g_force", "cabin_noise_db"
        ):
            if optional_col in df.columns:
                casts.append(pl.col(optional_col).cast(pl.Float64))
        return df.with_columns(casts)

    @staticmethod
    def _resample(df: pl.DataFrame, resample_ms: int) -> pl.DataFrame:
        """
        Normalise to uniform time grid using forward-fill resampling.
        Groups timestamps into resample_ms buckets and takes the mean.
        """
        df = df.with_columns(
            (pl.col("timestamp_offset_ms") // resample_ms * resample_ms)
            .alias("time_bucket_ms")
        )
        numeric_cols = [
            c for c in df.columns
            if c not in ("timestamp_offset_ms", "time_bucket_ms")
            and df[c].dtype in (pl.Float64, pl.Int64)
        ]
        agg_exprs = [pl.col(c).mean().alias(c) for c in numeric_cols]
        return (
            df.group_by("time_bucket_ms")
            .agg(agg_exprs)
            .sort("time_bucket_ms")
            .rename({"time_bucket_ms": "timestamp_offset_ms"})
        )


# ---------------------------------------------------------------------------
# SHA-256 Cryptographic Verification
# ---------------------------------------------------------------------------

def compute_sha256(path: str | Path, chunk_size: int = 1 << 20) -> str:
    """
    Stream-compute SHA-256 digest of a file without loading it fully into RAM.

    Args:
        path       : File path.
        chunk_size : Read chunk size in bytes (default 1 MiB).

    Returns:
        64-character lowercase hex digest string.
    """
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Metric Extraction
# ---------------------------------------------------------------------------

class MetricExtractor:
    """
    Computes high-level performance KPIs from a normalised telemetry DataFrame.
    Each extraction method is isolated for independent unit-testing.
    """

    @staticmethod
    def accel_0_100_kph(df: pl.DataFrame) -> Optional[float]:
        """
        Standing-start 0→100 km/h time.
        Uses first timestamp where speed >= 1 km/h as launch reference.
        """
        if "vehicle_speed_kph" not in df.columns:
            return None
        valid = df.filter(pl.col("vehicle_speed_kph") >= 0.0)
        t_launch_rows = valid.filter(pl.col("vehicle_speed_kph") >= 1.0).head(1)
        t_100_rows = valid.filter(pl.col("vehicle_speed_kph") >= 100.0).head(1)
        if t_launch_rows.is_empty() or t_100_rows.is_empty():
            return None
        t_start = t_launch_rows["timestamp_offset_ms"].item()
        t_100 = t_100_rows["timestamp_offset_ms"].item()
        return round((t_100 - t_start) / 1000.0, 3)

    @staticmethod
    def accel_0_200_kph(df: pl.DataFrame) -> Optional[float]:
        """Standing-start 0→200 km/h time."""
        if "vehicle_speed_kph" not in df.columns:
            return None
        valid = df.filter(pl.col("vehicle_speed_kph") >= 0.0)
        t_launch_rows = valid.filter(pl.col("vehicle_speed_kph") >= 1.0).head(1)
        t_200_rows = valid.filter(pl.col("vehicle_speed_kph") >= 200.0).head(1)
        if t_launch_rows.is_empty() or t_200_rows.is_empty():
            return None
        t_start = t_launch_rows["timestamp_offset_ms"].item()
        t_200 = t_200_rows["timestamp_offset_ms"].item()
        return round((t_200 - t_start) / 1000.0, 3)

    @staticmethod
    def max_inverter_temp(df: pl.DataFrame) -> Optional[float]:
        """Peak inverter temperature across the run."""
        if "inverter_temp_c" not in df.columns:
            return None
        return round(float(df["inverter_temp_c"].max()), 2)

    @staticmethod
    def battery_soc_drain(df: pl.DataFrame) -> Optional[float]:
        """Net SoC delta: first sample minus last sample."""
        if "battery_soc_pct" not in df.columns:
            return None
        start = df["battery_soc_pct"].head(1).item()
        end = df["battery_soc_pct"].tail(1).item()
        return round(float(start - end), 2)

    @staticmethod
    def peak_motor_torque(df: pl.DataFrame) -> Optional[float]:
        """Peak electric motor torque (N·m)."""
        if "motor_torque_nm" not in df.columns:
            return None
        return round(float(df["motor_torque_nm"].max()), 1)

    @staticmethod
    def nvh_cabin_db(df: pl.DataFrame) -> Optional[float]:
        """
        NVH cabin noise at 100 km/h ±2 km/h cruise band.
        Returns mean dB(A) reading in that window.
        """
        if "cabin_noise_db" not in df.columns or "vehicle_speed_kph" not in df.columns:
            return None
        cruise_window = df.filter(
            (pl.col("vehicle_speed_kph") >= 98.0)
            & (pl.col("vehicle_speed_kph") <= 102.0)
        )
        if cruise_window.is_empty():
            return None
        return round(float(cruise_window["cabin_noise_db"].mean()), 1)

    @staticmethod
    def brake_60_0_distance(df: pl.DataFrame) -> Optional[float]:
        """
        Braking distance from 60 km/h to standstill.
        Approximates using speed integral when brake event is detected.
        Requires 'brake_pressure_bar' column for event detection.
        """
        if not all(c in df.columns for c in ("vehicle_speed_kph", "brake_pressure_bar")):
            return None
        # Find brake event start: first sample where pressure > 30 bar and speed ~ 60 kph
        brake_events = df.filter(
            (pl.col("brake_pressure_bar") > 30.0)
            & (pl.col("vehicle_speed_kph") >= 55.0)
            & (pl.col("vehicle_speed_kph") <= 65.0)
        )
        if brake_events.is_empty():
            return None
        t_brake_start = brake_events["timestamp_offset_ms"].min()
        stop_events = df.filter(
            (pl.col("timestamp_offset_ms") > t_brake_start)
            & (pl.col("vehicle_speed_kph") <= 1.0)
        )
        if stop_events.is_empty():
            return None
        t_stop = stop_events["timestamp_offset_ms"].min()
        # Approximate distance via trapezoidal integration (v in m/s, t in seconds)
        window = df.filter(
            (pl.col("timestamp_offset_ms") >= t_brake_start)
            & (pl.col("timestamp_offset_ms") <= t_stop)
        )
        v_ms = window["vehicle_speed_kph"] / 3.6  # km/h -> m/s
        dt_s = window["timestamp_offset_ms"].diff().fill_null(0) / 1000.0  # ms -> s
        distance_m = float((v_ms * dt_s).sum())
        return round(distance_m, 1)

    @staticmethod
    def peak_lateral_g(df: pl.DataFrame) -> Optional[float]:
        """Peak lateral G-force."""
        if "lateral_g_force" not in df.columns:
            return None
        return round(float(df["lateral_g_force"].abs().max()), 3)

    @classmethod
    def extract_all(cls, df: pl.DataFrame) -> Dict[str, float]:
        """
        Run all extractor methods and return a dict of criteria_code -> value.
        None results (channel absent) are excluded.
        """
        extractors = {
            "ACCEL_0_100_KPH":       cls.accel_0_100_kph,
            "ACCEL_0_200_KPH":       cls.accel_0_200_kph,
            "MAX_INVERTER_TEMP_C":   cls.max_inverter_temp,
            "BATTERY_SOC_DRAIN_PCT": cls.battery_soc_drain,
            "PEAK_MOTOR_TORQUE_NM":  cls.peak_motor_torque,
            "NVH_CABIN_DB_100KPH":   cls.nvh_cabin_db,
            "BRAKE_60_0_DIST_M":     cls.brake_60_0_distance,
            "LAT_G_FORCE_PEAK":      cls.peak_lateral_g,
        }
        results: Dict[str, float] = {}
        for code, fn in extractors.items():
            try:
                val = fn(df)
                if val is not None:
                    results[code] = val
            except Exception as exc:  # noqa: BLE001
                logger.warning("Metric extraction failed for %s: %s", code, exc)
        return results


# ---------------------------------------------------------------------------
# Criteria Evaluation Engine
# ---------------------------------------------------------------------------

class TelemetryAnalyticsEngine:
    """
    Orchestrates the full pipeline:
      load file → compute SHA-256 → extract metrics → evaluate against rules.
    """

    def __init__(self, resample_ms: int = 10):
        self.resample_ms = resample_ms

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_file(
        self,
        file_path: str | Path,
        rules: List[CriteriaRule],
    ) -> IngestionSummary:
        """
        Full pipeline for a single telemetry file.

        Args:
            file_path : Path to raw telemetry file.
            rules     : Applicable benchmark rules for this test run.

        Returns:
            IngestionSummary containing metrics, outcomes, and SHA-256 digest.
        """
        path = Path(file_path)
        file_hash = compute_sha256(path)
        summary = IngestionSummary(
            file_path=str(path),
            file_hash_sha256=file_hash,
            record_count=0,
        )
        try:
            df = TelemetryLoader.load(path, resample_ms=self.resample_ms)
            summary.record_count = len(df)
            summary.metrics = MetricExtractor.extract_all(df)
            summary.outcomes = self.evaluate_run(summary.metrics, rules)
            logger.info(
                "Processed %s | records=%d | metrics=%d | hash=%s",
                path.name, summary.record_count,
                len(summary.metrics), file_hash[:12],
            )
        except Exception as exc:  # noqa: BLE001
            msg = f"Pipeline error for {path.name}: {exc}"
            logger.error(msg)
            summary.errors.append(msg)
        return summary

    @staticmethod
    def evaluate_run(
        metrics: Dict[str, float],
        rules: List[CriteriaRule],
    ) -> List[EvaluationOutcome]:
        """
        Apply benchmark rules to extracted metrics.

        Scoring logic:
          - PASS             : measured within [lower_limit, upper_limit]
          - MARGINAL_DEVIATION: within marginal_band_pct % beyond the hard limit
          - FAIL             : outside the marginal band

        Args:
            metrics : Dict of criteria_code -> measured float value.
            rules   : List of CriteriaRule thresholds.

        Returns:
            List of EvaluationOutcome objects.
        """
        outcomes: List[EvaluationOutcome] = []

        for rule in rules:
            if rule.criteria_code not in metrics:
                continue

            val = metrics[rule.criteria_code]
            target = rule.nominal_target
            upper = rule.upper_limit
            lower = rule.lower_limit
            band = rule.marginal_band_pct / 100.0

            within_hard = (
                (lower is None or val >= lower) and
                (upper is None or val <= upper)
            )

            if within_hard:
                status = "PASS"
            else:
                # Check marginal band: within (1 ± band) of the breached limit
                upper_marginal = (upper * (1.0 + band)) if upper is not None else None
                lower_marginal = (lower * (1.0 - band)) if lower is not None else None
                within_marginal = (
                    (lower_marginal is None or val >= lower_marginal) and
                    (upper_marginal is None or val <= upper_marginal)
                )
                status = "MARGINAL_DEVIATION" if within_marginal else "FAIL"

            variance = ((val - target) / target * 100.0) if target != 0.0 else 0.0

            outcomes.append(
                EvaluationOutcome(
                    criteria_code=rule.criteria_code,
                    measured_value=val,
                    target_value=target,
                    upper_limit=upper,
                    lower_limit=lower,
                    variance_pct=round(variance, 4),
                    status=status,
                )
            )

        return outcomes

    @staticmethod
    def aggregate_overall_status(outcomes: List[EvaluationOutcome]) -> str:
        """
        Roll up individual metric outcomes into a single test-run evaluation.

        Priority: FAIL > MARGINAL_DEVIATION > PASS > PENDING
        """
        statuses = {o.status for o in outcomes}
        if not statuses:
            return "PENDING"
        if "FAIL" in statuses:
            return "FAIL"
        if "MARGINAL_DEVIATION" in statuses:
            return "MARGINAL_DEVIATION"
        return "PASS"
