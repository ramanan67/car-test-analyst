# Automotive Prototype Testing Analytics Platform
**Enterprise Engineering Telemetry Processing, Benchmarking & Sign-Off Engine**

Compliant with **ISO 26262 Road Vehicles – Functional Safety** retention and audit guidelines.

---

## Architecture Overview

```
                      +-----------------------------+
                      |    Client Applications      |
                      |  (Web UI, Dyno Rig, CANbox) |
                      +--------------+--------------+
                                     |
                                     v
                      +-----------------------------+
                      |     Nginx Reverse Proxy     |
                      |        (Port 80/443)        |
                      +--------------+--------------+
                                     |
                                     v
                      +-----------------------------+
                      |   FastAPI Application       |
                      |   (Async REST API, Port 8000)
                      +-------+--------------+------+
                              |              |
                +-------------+              +-------------+
                v                                          v
      +--------------------+                     +--------------------+
      |   PostgreSQL 16    |                     |      Redis 7       |
      | Relational Storage |                     |   Message Broker   |
      |   & Audit Trail    |                     +---------+----------+
      +--------------------+                               |
                                                           v
                                                 +--------------------+
                                                 |   Celery Workers   |
                                                 | Polars Processing  |
                                                 | Engine & PDF/Excel |
                                                 +--------------------+
```

---

## Key Modules

### Module A: Vehicle Master Configuration (Pre-Test)
* **Metadata Registration:** Prototype Codes (VIN equivalents), vehicle classes (C-Class, E-Class, S-Class, EQS, etc.), powertrain architectures (`ICE`, `MHEV`, `PHEV`, `BEV`, `FCEV`), model year, and software build hashes.
* **Hardware BOM & Options:** Dynamic multi-select tagging of chassis packages, ADAS sensor suites, and drive configurations (e.g. `4MATIC Dual-Motor`).
* **Lifecycle Management:** State machine transitions across `STAGED` -> `ACTIVE_TESTING` -> `DECOMMISSIONED`.

### Module B: High-Throughput Telemetry Ingestion (Post-Test)
* **Multi-Format Parsing:** Ingests CSV, Parquet, XLSX, and MDF4/MF4 binary CAN traces.
* **Cryptographic Verification:** SHA-256 deduplication blocking redundant or collision test runs.
* **Resampling & Alignment:** High-frequency CANbus signal bucket resampling to uniform 10 ms / 100 ms time grids.
* **Decoupled Worker Queue:** Payloads over 10 MB run asynchronously via Redis & Celery task pools.

### Module C: Dynamic Performance & Evaluation Engine
* **Contextual Benchmarking:** Matches metrics against criteria definitions keyed on `(vehicle_class, powertrain_type, test_category)`.
* **Automated Scoring:** Vectorised Polars evaluation calculating variance percentages:
  $$\Delta\% = \frac{\text{measured} - \text{target}}{\text{target}} \times 100$$
* **Categorisation:** Evaluates to `PASS`, `MARGINAL_DEVIATION` (configurable 5% band), or `FAIL`.
* **Audited Engineering Overrides:** Lead Test Engineers can apply manual overrides accompanied by mandatory engineering rationales recorded in immutable audit tables.

### Module D: Visual Analytics & Export
* **Run Comparison Matrix:** Multi-run side-by-side variance analysis comparing prototype software revisions across identical test routes.
* **Cryptographic Sign-off:** Automated PDF and Excel sign-off documentation containing SHA-256 result digests.

---

## Directory Layout

```
automotive-test-platform/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── main.py
├── app/
│   ├── analytics/
│   │   ├── engine.py           # Polars metric extraction & scoring engine
│   │   └── report_generator.py # PDF & Excel cryptographic sign-off export
│   ├── api/
│   │   └── v1/
│   │       ├── dependencies.py # JWT authentication & RBAC
│   │       └── routers/
│   │           ├── analytics.py
│   │           ├── auth.py
│   │           ├── criteria.py
│   │           ├── test_runs.py
│   │           └── vehicles.py
│   ├── core/
│   │   ├── config.py           # Pydantic v2 application settings
│   │   ├── database.py         # Async SQLAlchemy session management
│   │   └── security.py         # Bcrypt hashing & JWT token issuing
│   ├── db/
│   │   ├── schema.sql          # PostgreSQL DDL with triggers & audit logs
│   │   └── migrations/
│   ├── models/
│   │   ├── enums.py            # Domain enum mappings
│   │   └── orm_models.py       # SQLAlchemy 2.0 mapped models
│   ├── schemas/
│   │   └── schemas.py          # Pydantic request/response schemas
│   └── worker/
│       └── tasks.py            # Celery async tasks & synthetic test generator
├── infra/
│   └── nginx/
│       └── nginx.conf          # Reverse proxy configuration
├── scripts/
│   └── seed_demo_data.py       # Seed script for initial fixtures
└── tests/
    ├── unit/
    │   └── test_analytics_engine.py
    └── integration/
        └── test_pipeline.py
```

---

## Deployment & Execution

### 1. Start Services via Docker Compose
```bash
docker compose up --build -d
```
Access points:
* **REST API & Swagger UI:** `http://localhost:8000/docs`
* **Health Check:** `http://localhost:8000/health`
* **Celery Flower Dashboard:** `http://localhost:5555`

### 2. Run Test Suite
```bash
pytest -v tests/
```
