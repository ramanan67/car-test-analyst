-- ============================================================
-- Automotive Prototype Testing Analytics Platform
-- PostgreSQL Database Schema v1.0
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- DOMAIN ENUMS
-- ============================================================
CREATE TYPE powertrain_type_enum AS ENUM ('ICE', 'MHEV', 'PHEV', 'BEV', 'FCEV');
CREATE TYPE body_style_enum AS ENUM ('SEDAN', 'ESTATE', 'COUPE', 'SUV', 'CABRIOLET');
CREATE TYPE drive_type_enum AS ENUM ('RWD', 'FWD', 'AWD_4MATIC');
CREATE TYPE lifecycle_status_enum AS ENUM ('STAGED', 'ACTIVE_TESTING', 'DECOMMISSIONED');
CREATE TYPE test_category_enum AS ENUM ('DYNO_POWERTRAIN', 'TRACK_DYNAMICS', 'NVH', 'THERMAL_HVAC', 'BATTERY_CYCLE', 'ADAS_SAFETY');
CREATE TYPE test_execution_status_enum AS ENUM ('SCHEDULED', 'IN_PROGRESS', 'COMPLETED', 'ABORTED', 'INVALIDATED');
CREATE TYPE evaluation_status_enum AS ENUM ('PENDING', 'PASS', 'FAIL', 'MARGINAL_DEVIATION');
CREATE TYPE user_role_enum AS ENUM ('TECHNICIAN', 'TEST_ANALYST', 'LEAD_ENGINEER', 'ADMIN', 'VIEWER');

-- ============================================================
-- 1. USER DIRECTORY
-- ============================================================
CREATE TABLE users (
    user_id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    corporate_id    VARCHAR(32) NOT NULL UNIQUE,
    first_name      VARCHAR(64) NOT NULL,
    last_name       VARCHAR(64) NOT NULL,
    email           VARCHAR(255) NOT NULL UNIQUE,
    role            user_role_enum NOT NULL DEFAULT 'TECHNICIAN',
    department      VARCHAR(100) NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    last_login_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_users_corporate_id ON users(corporate_id);
CREATE INDEX idx_users_role ON users(role);

-- ============================================================
-- 2. VEHICLE MASTER CONFIGURATION
-- ============================================================
CREATE TABLE vehicle_classes (
    class_id        UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    class_code      VARCHAR(16) NOT NULL UNIQUE,
    segment         VARCHAR(32) NOT NULL,
    description     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE option_packages (
    package_id      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    option_code     VARCHAR(32) NOT NULL UNIQUE,
    name            VARCHAR(128) NOT NULL,
    category        VARCHAR(64) NOT NULL,
    description     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE vehicles (
    vehicle_id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    prototype_code          VARCHAR(64) NOT NULL UNIQUE,
    class_id                UUID NOT NULL REFERENCES vehicle_classes(class_id) ON DELETE RESTRICT,
    model_name              VARCHAR(64) NOT NULL,
    model_year              SMALLINT NOT NULL CHECK (model_year BETWEEN 2020 AND 2040),
    powertrain              powertrain_type_enum NOT NULL,
    body_style              body_style_enum NOT NULL,
    drivetrain              drive_type_enum NOT NULL,
    lifecycle_status        lifecycle_status_enum NOT NULL DEFAULT 'STAGED',
    software_build_version  VARCHAR(64) NOT NULL,
    battery_capacity_kwh    NUMERIC(6, 2) CHECK (battery_capacity_kwh >= 0),
    curb_weight_kg          NUMERIC(6, 2) CHECK (curb_weight_kg > 0),
    created_by              UUID NOT NULL REFERENCES users(user_id),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_vehicles_class_id ON vehicles(class_id);
CREATE INDEX idx_vehicles_powertrain ON vehicles(powertrain);
CREATE INDEX idx_vehicles_lifecycle ON vehicles(lifecycle_status);

CREATE TABLE vehicle_options_bridge (
    vehicle_id      UUID NOT NULL REFERENCES vehicles(vehicle_id) ON DELETE CASCADE,
    package_id      UUID NOT NULL REFERENCES option_packages(package_id) ON DELETE RESTRICT,
    installed_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (vehicle_id, package_id)
);

-- ============================================================
-- 3. PERFORMANCE CRITERIA & BENCHMARK THRESHOLDS
-- ============================================================
CREATE TABLE performance_criteria_definitions (
    criteria_id     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    criteria_code   VARCHAR(64) NOT NULL UNIQUE,
    metric_name     VARCHAR(128) NOT NULL,
    unit_of_measure VARCHAR(32) NOT NULL,
    category        test_category_enum NOT NULL,
    description     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE benchmark_thresholds (
    threshold_id        UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    criteria_id         UUID NOT NULL REFERENCES performance_criteria_definitions(criteria_id) ON DELETE CASCADE,
    class_id            UUID NOT NULL REFERENCES vehicle_classes(class_id) ON DELETE CASCADE,
    powertrain          powertrain_type_enum,
    nominal_target      NUMERIC(10, 4) NOT NULL,
    upper_tolerance     NUMERIC(10, 4),
    lower_tolerance     NUMERIC(10, 4),
    marginal_band_pct   NUMERIC(5, 2) NOT NULL DEFAULT 5.00,
    effective_from      DATE NOT NULL,
    effective_to        DATE,
    created_by          UUID NOT NULL REFERENCES users(user_id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_threshold_context UNIQUE (criteria_id, class_id, powertrain, effective_from)
);

CREATE INDEX idx_thresholds_criteria_class ON benchmark_thresholds(criteria_id, class_id);
CREATE INDEX idx_thresholds_effective ON benchmark_thresholds(effective_from, effective_to);

-- ============================================================
-- 4. TEST FACILITIES
-- ============================================================
CREATE TABLE test_facilities (
    facility_id     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            VARCHAR(128) NOT NULL,
    location        VARCHAR(128),
    country         CHAR(3) NOT NULL,
    facility_type   VARCHAR(64),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- 5. TEST RUNS
-- ============================================================
CREATE TABLE test_runs (
    test_run_id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_number          VARCHAR(64) NOT NULL UNIQUE,
    vehicle_id          UUID NOT NULL REFERENCES vehicles(vehicle_id) ON DELETE RESTRICT,
    facility_id         UUID NOT NULL REFERENCES test_facilities(facility_id) ON DELETE RESTRICT,
    category            test_category_enum NOT NULL,
    execution_status    test_execution_status_enum NOT NULL DEFAULT 'SCHEDULED',
    overall_evaluation  evaluation_status_enum NOT NULL DEFAULT 'PENDING',
    start_time          TIMESTAMPTZ NOT NULL,
    end_time            TIMESTAMPTZ,
    ambient_temp_c      NUMERIC(4, 1),
    humidity_pct        NUMERIC(5, 2),
    track_condition     VARCHAR(32),
    odometer_km         NUMERIC(8, 2) CHECK (odometer_km >= 0),
    notes               TEXT,
    executed_by         UUID NOT NULL REFERENCES users(user_id),
    reviewed_by         UUID REFERENCES users(user_id),
    review_comments     TEXT,
    reviewed_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_run_time_window CHECK (end_time IS NULL OR end_time >= start_time)
);

CREATE INDEX idx_test_runs_vehicle_id ON test_runs(vehicle_id);
CREATE INDEX idx_test_runs_facility_id ON test_runs(facility_id);
CREATE INDEX idx_test_runs_category ON test_runs(category);
CREATE INDEX idx_test_runs_status ON test_runs(execution_status, overall_evaluation);
CREATE INDEX idx_test_runs_start_time ON test_runs(start_time DESC);

-- ============================================================
-- 6. TELEMETRY FILE IMPORTS
-- ============================================================
CREATE TABLE test_import_files (
    file_id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    test_run_id         UUID NOT NULL REFERENCES test_runs(test_run_id) ON DELETE CASCADE,
    file_name           VARCHAR(255) NOT NULL,
    file_format         VARCHAR(16) NOT NULL CHECK (file_format IN ('CSV','PARQUET','XLSX','MDF4','CAN')),
    file_hash_sha256    CHAR(64) NOT NULL UNIQUE,
    file_size_bytes     BIGINT NOT NULL CHECK (file_size_bytes > 0),
    raw_storage_uri     TEXT NOT NULL,
    processing_status   VARCHAR(32) NOT NULL DEFAULT 'QUEUED',
    processing_error    TEXT,
    record_count        BIGINT,
    processed_at        TIMESTAMPTZ,
    uploaded_by         UUID NOT NULL REFERENCES users(user_id),
    uploaded_at         TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_import_files_test_run ON test_import_files(test_run_id);
CREATE INDEX idx_import_files_hash ON test_import_files(file_hash_sha256);
CREATE INDEX idx_import_files_status ON test_import_files(processing_status);

-- ============================================================
-- 7. RESULTS & METRICS EVALUATION
-- ============================================================
CREATE TABLE test_result_metrics (
    metric_id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    test_run_id             UUID NOT NULL REFERENCES test_runs(test_run_id) ON DELETE CASCADE,
    criteria_id             UUID NOT NULL REFERENCES performance_criteria_definitions(criteria_id) ON DELETE RESTRICT,
    measured_value          NUMERIC(12, 4) NOT NULL,
    applied_target          NUMERIC(12, 4) NOT NULL,
    upper_limit             NUMERIC(12, 4),
    lower_limit             NUMERIC(12, 4),
    variance_pct            NUMERIC(6, 2),
    status                  evaluation_status_enum NOT NULL DEFAULT 'PENDING',
    engineer_override_status evaluation_status_enum,
    override_reason         TEXT,
    override_by             UUID REFERENCES users(user_id),
    override_at             TIMESTAMPTZ,
    evaluated_at            TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_test_criteria_pair UNIQUE (test_run_id, criteria_id)
);

CREATE INDEX idx_metrics_test_run ON test_result_metrics(test_run_id);
CREATE INDEX idx_metrics_criteria ON test_result_metrics(criteria_id);
CREATE INDEX idx_metrics_status ON test_result_metrics(status);

-- ============================================================
-- 8. AUDIT TRAIL
-- ============================================================
CREATE TABLE audit_logs (
    audit_id            BIGSERIAL PRIMARY KEY,
    table_name          VARCHAR(64) NOT NULL,
    record_id           UUID NOT NULL,
    action              VARCHAR(16) NOT NULL CHECK (action IN ('INSERT', 'UPDATE', 'DELETE')),
    changed_by          UUID REFERENCES users(user_id),
    old_data            JSONB,
    new_data            JSONB,
    ip_address          INET,
    session_id          VARCHAR(128),
    action_timestamp    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_audit_table_record ON audit_logs(table_name, record_id);
CREATE INDEX idx_audit_timestamp ON audit_logs(action_timestamp DESC);
CREATE INDEX idx_audit_changed_by ON audit_logs(changed_by);

-- ============================================================
-- 9. AUDIT TRIGGER FUNCTION
-- ============================================================
CREATE OR REPLACE FUNCTION fn_audit_trigger()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO audit_logs(table_name, record_id, action, new_data)
        VALUES (TG_TABLE_NAME, NEW.*, 'INSERT', to_jsonb(NEW));
        RETURN NEW;
    ELSIF TG_OP = 'UPDATE' THEN
        INSERT INTO audit_logs(table_name, record_id, action, old_data, new_data)
        VALUES (TG_TABLE_NAME, OLD.*, 'UPDATE', to_jsonb(OLD), to_jsonb(NEW));
        RETURN NEW;
    ELSIF TG_OP = 'DELETE' THEN
        INSERT INTO audit_logs(table_name, record_id, action, old_data)
        VALUES (TG_TABLE_NAME, OLD.*, 'DELETE', to_jsonb(OLD));
        RETURN OLD;
    END IF;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Apply audit trigger to sensitive tables
CREATE TRIGGER trg_audit_vehicles
    AFTER INSERT OR UPDATE OR DELETE ON vehicles
    FOR EACH ROW EXECUTE FUNCTION fn_audit_trigger();

CREATE TRIGGER trg_audit_test_runs
    AFTER INSERT OR UPDATE OR DELETE ON test_runs
    FOR EACH ROW EXECUTE FUNCTION fn_audit_trigger();

CREATE TRIGGER trg_audit_metrics
    AFTER INSERT OR UPDATE OR DELETE ON test_result_metrics
    FOR EACH ROW EXECUTE FUNCTION fn_audit_trigger();

CREATE TRIGGER trg_audit_thresholds
    AFTER INSERT OR UPDATE OR DELETE ON benchmark_thresholds
    FOR EACH ROW EXECUTE FUNCTION fn_audit_trigger();

-- ============================================================
-- 10. SEED REFERENCE DATA
-- ============================================================
INSERT INTO vehicle_classes (class_code, segment, description) VALUES
    ('C-CLASS',  'Compact Executive',   'W206 / S206 generation compact executive saloon/estate'),
    ('E-CLASS',  'Executive',           'W214 / S214 generation executive saloon/estate'),
    ('S-CLASS',  'Full-Size Luxury',    'W223 generation full-size flagship saloon'),
    ('EQS',      'Full-Size BEV Luxury','V297 generation full-size battery-electric flagship'),
    ('EQE',      'Executive BEV',       'V295 generation executive battery-electric saloon'),
    ('GLC',      'Compact SUV',         'X254 generation compact luxury SUV'),
    ('GLE',      'Mid-Size SUV',        'V167 generation mid-size luxury SUV'),
    ('AMG-GT',   'Sports GT',           'X290 generation high-performance GT coupe');

INSERT INTO test_facilities (name, location, country, facility_type) VALUES
    ('Sindelfingen Development Center', 'Sindelfingen, Baden-Württemberg', 'DEU', 'COMBINED_RD_TRACK'),
    ('Immendingen Proving Ground',      'Immendingen, Baden-Württemberg',  'DEU', 'PROVING_GROUND'),
    ('Arjeplog Winter Test Center',     'Arjeplog, Norrbotten',            'SWE', 'WINTER_PROVING_GROUND'),
    ('Papenburg High-Speed Oval',       'Papenburg, Lower Saxony',         'DEU', 'HIGH_SPEED_OVAL'),
    ('Nardo High-Speed Ring',           'Nardò, Puglia',                   'ITA', 'HIGH_SPEED_OVAL'),
    ('Dudenhofen Test Center',          'Dudenhofen, Rhineland-Palatinate','DEU', 'COMBINED_RD_TRACK');

INSERT INTO performance_criteria_definitions (criteria_code, metric_name, unit_of_measure, category, description) VALUES
    ('ACCEL_0_100_KPH',        '0-100 km/h Acceleration Time',    's',   'DYNO_POWERTRAIN', 'Time in seconds from 0 to 100 km/h standing start'),
    ('ACCEL_0_200_KPH',        '0-200 km/h Acceleration Time',    's',   'DYNO_POWERTRAIN', 'Time in seconds from 0 to 200 km/h standing start'),
    ('MAX_INVERTER_TEMP_C',    'Peak Inverter Temperature',        '°C',  'THERMAL_HVAC',    'Maximum recorded power electronics inverter temperature'),
    ('BATTERY_SOC_DRAIN_PCT',  'Battery SoC Drain per Run',        '%',   'BATTERY_CYCLE',   'Net state-of-charge delta across a full test run'),
    ('PEAK_MOTOR_TORQUE_NM',   'Peak Electric Motor Torque',       'N·m', 'DYNO_POWERTRAIN', 'Maximum instantaneous motor torque recorded on dyno'),
    ('NVH_CABIN_DB_100KPH',    'Cabin NVH Level at 100 km/h',     'dB',  'NVH',             'Interior noise level in dB(A) at steady-state 100 km/h cruise'),
    ('BRAKE_60_0_DIST_M',      '60-0 km/h Braking Distance',      'm',   'TRACK_DYNAMICS',  'Distance in metres to halt from 60 km/h panic stop'),
    ('LAT_G_FORCE_PEAK',       'Peak Lateral G-Force',             'g',   'TRACK_DYNAMICS',  'Maximum lateral acceleration recorded through reference corner'),
    ('ADAS_AEB_TRIGGER_MS',    'AEB System Response Latency',      'ms',  'ADAS_SAFETY',     'Time from obstacle detection to first brake actuation by AEBS'),
    ('HVAC_CABIN_DELTA_TEMP_C','HVAC Cabin Temperature Delta',     '°C',  'THERMAL_HVAC',    'Cabin temperature delta from ambient during 30-min conditioning');
