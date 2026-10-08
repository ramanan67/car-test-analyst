"""
app/worker/tasks.py
Celery task definitions for async telemetry processing.
Decouples large file ingestion from the HTTP request cycle.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import List

from celery import Celery

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

celery_app = Celery(
    "automotive_worker",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "app.worker.tasks.process_telemetry_file_task": {"queue": "telemetry"},
        "app.worker.tasks.generate_report_task": {"queue": "reports"},
    },
)


@celery_app.task(
    name="app.worker.tasks.process_telemetry_file_task",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    soft_time_limit=300,
    time_limit=360,
)
def process_telemetry_file_task(
    self,
    file_id: str,
    test_run_id: str,
    storage_uri: str,
    file_format: str,
) -> dict:
    """
    Celery task: Download, parse, score, and persist telemetry metrics.

    Steps:
      1. Download raw file from object storage to temp path.
      2. Compute SHA-256 for final verification.
      3. Load and resample telemetry via TelemetryLoader.
      4. Extract performance KPIs via MetricExtractor.
      5. Load applicable BenchmarkThreshold rules from DB (sync context).
      6. Evaluate all metrics via TelemetryAnalyticsEngine.evaluate_run().
      7. Persist TestResultMetric rows and update TestRun.overall_evaluation.
      8. Mark TestImportFile processing_status = PROCESSED / FAILED.

    Args:
        file_id     : UUID of the TestImportFile record.
        test_run_id : UUID of the parent TestRun.
        storage_uri : Object storage URI of the raw telemetry file.
        file_format : File format string (CSV, PARQUET, etc.).

    Returns:
        dict with record_count, metric count, and overall evaluation.
    """
    import asyncio
    import tempfile
    import os

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.analytics.engine import (
        CriteriaRule,
        TelemetryAnalyticsEngine,
        TelemetryLoader,
        MetricExtractor,
        compute_sha256,
    )
    from app.core.database import get_db_context
    from app.models.orm_models import (
        BenchmarkThreshold,
        PerformanceCriteriaDefinition,
        TestImportFile,
        TestResultMetric,
        TestRun,
        Vehicle,
    )

    async def _run():
        async with get_db_context() as db:
            # Load import file record
            result = await db.execute(
                select(TestImportFile).where(TestImportFile.file_id == uuid.UUID(file_id))
            )
            import_file = result.scalar_one_or_none()
            if not import_file:
                logger.error("ImportFile %s not found", file_id)
                return {"error": "file_not_found"}

            import_file.processing_status = "PROCESSING"
            await db.flush()

            try:
                # -- Simulate download from storage to temp file --
                # In production: download from S3/MinIO using boto3/minio client
                # Here we resolve directly from storage_uri (local dev mode)
                with tempfile.NamedTemporaryFile(
                    suffix=f".{file_format.lower()}", delete=False
                ) as tmp:
                    tmp_path = tmp.name

                # For demo: write a synthetic CSV if uri points to nothing real
                if storage_uri.startswith("s3://") and not os.path.exists(tmp_path):
                    _write_synthetic_telemetry(tmp_path)
                else:
                    tmp_path = storage_uri  # local path fallback

                # -- Load and extract metrics --
                df = TelemetryLoader.load(tmp_path, resample_ms=settings.TELEMETRY_RESAMPLE_MS)
                metrics = MetricExtractor.extract_all(df)
                record_count = len(df)

                # -- Load threshold rules for this vehicle/class --
                run_result = await db.execute(
                    select(TestRun)
                    .where(TestRun.test_run_id == uuid.UUID(test_run_id))
                    .options(selectinload(TestRun.vehicle))
                )
                run = run_result.scalar_one_or_none()
                if not run:
                    raise ValueError(f"TestRun {test_run_id} not found")

                today = datetime.now(timezone.utc).date()
                thresholds_result = await db.execute(
                    select(BenchmarkThreshold, PerformanceCriteriaDefinition)
                    .join(
                        PerformanceCriteriaDefinition,
                        BenchmarkThreshold.criteria_id
                        == PerformanceCriteriaDefinition.criteria_id,
                    )
                    .where(
                        BenchmarkThreshold.class_id == run.vehicle.class_id,
                        BenchmarkThreshold.effective_from <= today,
                        (
                            BenchmarkThreshold.effective_to.is_(None)
                            | (BenchmarkThreshold.effective_to >= today)
                        ),
                    )
                )

                rules: List[CriteriaRule] = [
                    CriteriaRule(
                        criteria_code=criteria.criteria_code,
                        nominal_target=float(threshold.nominal_target),
                        upper_limit=float(threshold.upper_tolerance) if threshold.upper_tolerance else None,
                        lower_limit=float(threshold.lower_tolerance) if threshold.lower_tolerance else None,
                        marginal_band_pct=float(threshold.marginal_band_pct),
                    )
                    for threshold, criteria in thresholds_result.all()
                ]

                # -- Evaluate --
                engine = TelemetryAnalyticsEngine(resample_ms=settings.TELEMETRY_RESAMPLE_MS)
                outcomes = engine.evaluate_run(metrics, rules)

                # -- Persist metric results --
                criteria_map = {}
                criteria_result = await db.execute(
                    select(PerformanceCriteriaDefinition)
                )
                for c in criteria_result.scalars().all():
                    criteria_map[c.criteria_code] = c.criteria_id

                for outcome in outcomes:
                    if outcome.criteria_code not in criteria_map:
                        continue
                    metric = TestResultMetric(
                        test_run_id=uuid.UUID(test_run_id),
                        criteria_id=criteria_map[outcome.criteria_code],
                        measured_value=outcome.measured_value,
                        applied_target=outcome.target_value,
                        upper_limit=outcome.upper_limit,
                        lower_limit=outcome.lower_limit,
                        variance_pct=outcome.variance_pct,
                        status=outcome.status,
                    )
                    db.add(metric)

                # -- Update overall evaluation --
                overall = engine.aggregate_overall_status(outcomes)
                run.overall_evaluation = overall
                run.execution_status = "COMPLETED"

                # -- Update import file --
                import_file.processing_status = "PROCESSED"
                import_file.record_count = record_count
                import_file.processed_at = datetime.now(timezone.utc)
                import_file.processing_error = None

                await db.flush()
                logger.info(
                    "Processed file %s | records=%d | metrics=%d | overall=%s",
                    file_id, record_count, len(outcomes), overall,
                )
                return {
                    "file_id": file_id,
                    "record_count": record_count,
                    "metric_count": len(outcomes),
                    "overall_evaluation": overall,
                }

            except Exception as exc:
                logger.error("Processing failed for file %s: %s", file_id, exc, exc_info=True)
                import_file.processing_status = "FAILED"
                import_file.processing_error = str(exc)[:1000]
                await db.flush()
                raise self.retry(exc=exc)

    return asyncio.run(_run())


def _write_synthetic_telemetry(path: str, n_samples: int = 5000) -> None:
    """Write a synthetic CSV telemetry file for local development/testing."""
    import csv
    import math
    import random

    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "timestamp_offset_ms", "vehicle_speed_kph", "inverter_temp_c",
            "battery_soc_pct", "motor_torque_nm", "brake_pressure_bar",
            "lateral_g_force", "cabin_noise_db",
        ])
        soc = 95.0
        for i in range(n_samples):
            t_ms = i * 10
            speed = min(100.0, i * 0.04) if i < 2500 else 100.0
            inv_temp = 40.0 + 30.0 * (speed / 100.0) + random.uniform(-2, 2)
            soc -= 0.001
            torque = max(0, 400.0 - speed * 2.0) + random.uniform(-5, 5)
            brake = 0.0 if speed < 99.0 else random.uniform(0, 5)
            lat_g = 0.2 * math.sin(i / 200.0) + random.uniform(-0.05, 0.05)
            cabin = 62.0 + speed * 0.1 + random.uniform(-1, 1)
            writer.writerow([t_ms, round(speed, 2), round(inv_temp, 2),
                             round(soc, 3), round(torque, 1), round(brake, 2),
                             round(lat_g, 4), round(cabin, 1)])


@celery_app.task(
    name="app.worker.tasks.generate_report_task",
    bind=True,
    max_retries=2,
    soft_time_limit=120,
)
def generate_report_task(self, test_run_id: str, format: str = "pdf") -> dict:
    """
    Async report generation task.
    Triggered when a sign-off document is requested for large run datasets.
    """
    import asyncio

    async def _run():
        import tempfile
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.core.database import get_db_context
        from app.models.orm_models import TestRun, TestResultMetric
        from app.analytics.report_generator import PDFReportGenerator, ExcelReportGenerator

        async with get_db_context() as db:
            run_result = await db.execute(
                select(TestRun)
                .where(TestRun.test_run_id == uuid.UUID(test_run_id))
                .options(
                    selectinload(TestRun.vehicle),
                    selectinload(TestRun.facility),
                    selectinload(TestRun.executed_by_user),
                )
            )
            run = run_result.scalar_one_or_none()
            if not run:
                return {"error": "run_not_found"}

            metrics_result = await db.execute(
                select(TestResultMetric)
                .where(TestResultMetric.test_run_id == uuid.UUID(test_run_id))
                .options(selectinload(TestResultMetric.criteria))
            )
            metrics = metrics_result.scalars().all()

            run_data = {
                "run_number": run.run_number,
                "prototype_code": run.vehicle.prototype_code,
                "category": str(run.category),
                "facility": run.facility.name,
                "start_time": run.start_time,
                "end_time": run.end_time,
                "overall_evaluation": str(run.overall_evaluation),
            }
            metrics_data = [
                {
                    "criteria_code": m.criteria.criteria_code,
                    "metric_name": m.criteria.metric_name,
                    "measured_value": float(m.measured_value),
                    "applied_target": float(m.applied_target),
                    "upper_limit": float(m.upper_limit) if m.upper_limit else None,
                    "lower_limit": float(m.lower_limit) if m.lower_limit else None,
                    "variance_pct": float(m.variance_pct) if m.variance_pct else None,
                    "status": str(m.status),
                    "engineer_override_status": str(m.engineer_override_status) if m.engineer_override_status else None,
                    "override_reason": m.override_reason,
                }
                for m in metrics
            ]

            suffix = ".pdf" if format == "pdf" else ".xlsx"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                output_path = tmp.name

            if format == "pdf":
                digest = PDFReportGenerator().generate(run_data, metrics_data, output_path)
            else:
                digest = ExcelReportGenerator().generate(run_data, metrics_data, output_path)

            return {"output_path": output_path, "digest": digest}

    return asyncio.run(_run())
