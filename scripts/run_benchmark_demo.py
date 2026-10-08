"""
scripts/run_benchmark_demo.py
Demonstrates the high-throughput processing pipeline on 100,000 synthetic telemetry points,
computing performance metrics, SHA-256 verification, and benchmark evaluation.
"""
import time
import tempfile
from pathlib import Path
import polars as pl
from app.analytics.engine import (
    TelemetryAnalyticsEngine,
    CriteriaRule,
    compute_sha256,
)

def run_benchmark():
    print("=" * 65)
    print(" AUTOMOTIVE PROTOTYPE TESTING ANALYTICS ENGINE BENCHMARK")
    print("=" * 65)

    n_samples = 100_000
    print(f"Generating synthetic dyno pull telemetry dataset ({n_samples:,} records)...")
    
    t_start_gen = time.perf_counter()
    # 10ms sampling interval = 1,000 seconds of continuous test data
    timestamps = [i * 10 for i in range(n_samples)]
    # Speed profile from 0 to 120 km/h
    speeds = [min(120.0, (i / 1500.0) * 100.0) if i < 1500 else 120.0 for i in range(n_samples)]
    inv_temps = [38.0 + (s / 120.0) * 44.0 for s in speeds]
    socs = [96.0 - (i / n_samples) * 8.5 for i in range(n_samples)]
    torques = [max(0.0, 420.0 - s * 2.2) for s in speeds]

    df = pl.DataFrame({
        "timestamp_offset_ms": timestamps,
        "vehicle_speed_kph": speeds,
        "inverter_temp_c": inv_temps,
        "battery_soc_pct": socs,
        "motor_torque_nm": torques,
    })
    gen_time = (time.perf_counter() - t_start_gen) * 1000
    print(f"Dataset generated in {gen_time:.2f} ms.")

    with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False) as tmp:
        df.write_csv(tmp.name)
        csv_path = tmp.name

    try:
        t_start_proc = time.perf_counter()
        
        # 1. SHA-256 Digest
        digest = compute_sha256(csv_path)
        
        # 2. Benchmark Rules
        rules = [
            CriteriaRule("ACCEL_0_100_KPH", nominal_target=4.8, upper_limit=5.2, lower_limit=None),
            CriteriaRule("MAX_INVERTER_TEMP_C", nominal_target=78.0, upper_limit=85.0, lower_limit=None),
            CriteriaRule("BATTERY_SOC_DRAIN_PCT", nominal_target=8.0, upper_limit=10.0, lower_limit=None),
            CriteriaRule("PEAK_MOTOR_TORQUE_NM", nominal_target=410.0, upper_limit=None, lower_limit=390.0),
        ]

        # 3. Analytics Engine Execution
        engine = TelemetryAnalyticsEngine(resample_ms=10)
        summary = engine.process_file(csv_path, rules)
        
        proc_time = (time.perf_counter() - t_start_proc) * 1000
        
        print("\n" + "-" * 65)
        print(" EXECUTION RESULTS")
        print("-" * 65)
        print(f"  • Processed Records      : {summary.record_count:,}")
        print(f"  • Ingestion & Score Time : {proc_time:.2f} ms")
        print(f"  • Throughput             : {summary.record_count / (proc_time / 1000):,.0f} records/sec")
        print(f"  • Cryptographic Hash     : {digest[:32]}...")
        
        print("\n" + "-" * 65)
        print(" EXTRACTED PERFORMANCE METRICS")
        print("-" * 65)
        for code, val in summary.metrics.items():
            print(f"  • {code:<25}: {val}")

        print("\n" + "-" * 65)
        print(" BENCHMARK EVALUATION OUTCOMES")
        print("-" * 65)
        for outcome in summary.outcomes:
            status_symbol = "[PASS]" if outcome.status == "PASS" else f"[{outcome.status}]"
            print(f"  {status_symbol:<14} {outcome.criteria_code:<22} | "
                  f"Measured: {outcome.measured_value:>7} | "
                  f"Target: {outcome.target_value:>6} | "
                  f"Variance: {outcome.variance_pct:>+6.2f}%")

        overall = engine.aggregate_overall_status(summary.outcomes)
        print("-" * 65)
        print(f" OVERALL RUN EVALUATION : {overall}")
        print("=" * 65)

    finally:
        Path(csv_path).unlink(missing_ok=True)

if __name__ == "__main__":
    run_benchmark()
