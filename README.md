# ISRO SIH26170: Anomaly Detection in Component Burn-In & Screening
## Phase 1 & 2: Database Schema, Synthetic Physics Engine, Analytical Modules & Verdict Layer

![ISRO SIH26170 Architecture](https://img.shields.io/badge/Project-ISRO%20SIH26170-blue.svg)
![Python 3.11](https://img.shields.io/badge/Python-3.11%2B-brightgreen.svg)
![PostgreSQL 16](https://img.shields.io/badge/PostgreSQL-16-blue.svg)
![Redis 7](https://img.shields.io/badge/Redis-7-red.svg)
![SQLAlchemy 2.0](https://img.shields.io/badge/SQLAlchemy-2.0-orange.svg)
![Alembic](https://img.shields.io/badge/Alembic-1.14-purple.svg)
![LightGBM](https://img.shields.io/badge/LightGBM-4.7-brightgreen.svg)

---

## 1. Architectural Overview

This repository houses the end-to-end analytical infrastructure for **ISRO SIH26170**: Anomaly Detection in Component Burn-In and Screening for high-reliability space-grade semiconductor components.

During burn-in screening, parts are subjected to thermal and electrical stress across standardized intervals ($t \in [0, 24, 96, 168]$ hours) to accelerate latent defects. Standard limit screening fails when:
1. Parts drift excessively while staying within static absolute datasheet limits.
2. Fabrication lots experience normal batch-to-batch baseline process shifts (e.g. `BENIGN_HIGH_LOT`).
3. Subtle anomalies degrade concurrently across multiple correlated parameters ($I_{leakage}$, $I_{DDQ}$, propagation delay) without triggering individual 3-sigma univariate alarms.

### System Pipeline Architecture
- **Phase 1 (Data Foundation)**:
  * Docker Compose: PostgreSQL 16 Alpine + Redis 7 Alpine with persistent volumes and healthchecks.
  * Schema & Migrations: SQLAlchemy 2.0 and Alembic tracking `Lot`, `Component`, and `BurnInReading`.
  * Synthetic Data Generator: Mathematical semiconductor physics engine with labeled anomalies and sensor noise.
  * Database Seeder: Bulk batch ingestion streaming >8,500 readings/sec into PostgreSQL.
- **Phase 2 (Analytical Engines & Triage)**:
  * **Module A (Lot-Adaptive Outlier Detector)**: Robust Median/MAD scaling, Ledoit-Wolf covariance shrinkage Mahalanobis distance, and Isolation Forests to detect spatial outliers without false-flagging benign elevated baseline lots.
  * **Module B (24h Early Drift Predictor)**: LightGBM gradient-boosted kinetic regressors forecasting 168h parameter states from only 0h/24h intervals (outperforming linear extrapolators by >58% MAE reduction).
  * **Unified Verdict Layer**: Deterministic triage rules mapping components to `PASS`, `REVIEW`, or `REJECT` with actionable rule justification traces.
  * **Model Predictions Schema**: Persisted `ModelPrediction` records linked via foreign keys to components.

---

## 2. Directory Layout

```
BURN_IN/
├── docker-compose.yml              # PostgreSQL 16 & Redis 7 services with healthchecks
├── .env.example                    # Environment variable template
├── .env                            # Active environment configuration
├── .gitignore                      # Git exclusion rules
├── requirements.txt                # Python dependencies
├── README.md                       # Architecture & execution guide
├── alembic.ini                     # Root Alembic migration configuration
├── backend/
│   ├── alembic.ini                 # Localized Alembic configuration
│   ├── alembic/
│   │   ├── env.py                  # Dynamic database URL wiring
│   │   ├── script.py.mako          # Revision template
│   │   └── versions/
│   │       ├── 9635d36eca2d_initial_burn_in_schema.py   # Phase 1 Migration
│   │       └── cd34b5de42c0_add_model_predictions_table.py # Phase 2 Migration
│   └── app/
│       ├── core/
│       │   ├── config.py           # Pydantic BaseSettings with computed URLs
│       │   └── database.py         # Sync (psycopg2) & Async (asyncpg) engines
│       └── models/
│           ├── base.py             # SQLAlchemy 2.0 DeclarativeBase
│           ├── lot.py              # Lot entity & LotStatus enum
│           ├── component.py        # Component entity & GroundTruthLabel enum
│           ├── reading.py          # BurnInReading entity with composite indexes
│           └── prediction.py       # ModelPrediction entity & ScreeningVerdict enum
├── data_engine/
│   ├── generator.py                # BurnInSyntheticGenerator physics engine
│   └── seed_db.py                  # High-performance bulk database seeder CLI
├── ml_engine/
│   ├── module_a_outlier.py         # LotOutlierDetector (Ledoit-Wolf + iForest)
│   ├── module_b_drift.py           # DriftPredictor (LightGBM 168h forecaster)
│   ├── verdict_engine.py           # ScreeningVerdictEngine (PASS/REVIEW/REJECT)
│   └── run_screening.py            # Complete screening pipeline & benchmark runner
└── tests/
    ├── test_generator.py           # Mathematical & physics verification tests
    ├── test_models.py              # Schema, cascade delete, & async session tests
    └── test_screening_engines.py   # Module A, Module B, & Verdict tests
```

---

## 3. Database Schema & Entity Relationships

```mermaid
erDiagram
    LOTS ||--o{ COMPONENTS : contains
    COMPONENTS ||--o{ BURN_IN_READINGS : records
    COMPONENTS ||--o| MODEL_PREDICTIONS : evaluates

    LOTS {
        uuid id PK "UUIDv4 default"
        varchar(64) lot_number UK "Unique lot tracking ID, indexed"
        varchar(64) wafer_id "Wafer batch tracking ID, indexed"
        enum status "INGESTED, SCREENED, REVIEW_PENDING"
        timestamp with_tz created_at "Default now()"
    }

    COMPONENTS {
        uuid id PK "UUIDv4 default"
        uuid lot_id FK "FK -> lots.id ON DELETE CASCADE"
        varchar(64) serial_number "Part serial number"
        enum ground_truth_label "NORMAL, LEVEL_OUTLIER, STEEP_DRIFT, LATE_DRIFT, SUBTLE_MULTIVARIATE"
        boolean ground_truth_flag "True if anomaly, False if normal"
        boolean is_datasheet_breached "True if >50uA leakage, >5mA iddq, or >8ns delay"
    }

    BURN_IN_READINGS {
        uuid id PK "UUIDv4 default"
        uuid component_id FK "FK -> components.id ON DELETE CASCADE"
        integer interval_hours "0, 24, 96, 168 (chk >= 0)"
        float leakage_current_ua "Subthreshold leakage (uA)"
        float iddq_ma "Quiescent supply current (mA)"
        float propagation_delay_ns "Critical path delay (ns)"
        timestamp with_tz recorded_at "Default now()"
    }

    MODEL_PREDICTIONS {
        uuid id PK "UUIDv4 default"
        uuid component_id FK "FK -> components.id ON DELETE CASCADE"
        float module_a_score "Composite lot outlier score [0.0, 1.0]"
        float module_a_mahalanobis "Ledoit-Wolf shrunk Mahalanobis distance"
        boolean module_a_flag "True if spatial lot outlier"
        float pred_leakage_168h "LightGBM forecasted leakage at 168h (uA)"
        float pred_iddq_168h "LightGBM forecasted IDDQ at 168h (mA)"
        float pred_delay_168h "LightGBM forecasted delay at 168h (ns)"
        float drift_slope_ua_per_hr "Forecasted leakage drift rate (uA/hr)"
        boolean module_b_flag "True if excessive drift or threshold breach"
        enum verdict "PASS, REVIEW, REJECT"
        text verdict_reason "Deterministic rule trace justification"
        timestamp with_tz created_at "Inference timestamp"
    }
```

---

## 4. Analytical Modules & Verdict Logic

### Module A — Dynamic Lot Outlier Detector (`ml_engine/module_a_outlier.py`)
- **Lot-Adaptive Normalization**: Computes Median and MAD per lot, expressing readings in MAD units:
  $$Z_{p} = \frac{v - \text{Median}_p}{\text{MAD}_p}$$
- **Ledoit-Wolf Covariance Shrinkage**: Computes Mahalanobis distance from lot origin:
  $$D_M = \sqrt{\mathbf{z}^T \Sigma_{\text{shrunk}}^{-1} \mathbf{z}}$$
- **Isolation Forest**: Fits non-linear density boundaries on lot-normalized features.
- **Multivariate Excursion**: Directly tracks simultaneous positive shifts across all 3 parameters to isolate `SUBTLE_MULTIVARIATE` anomalies.

### Module B — 24h Early Drift Predictor (`ml_engine/module_b_drift.py`)
- **Inputs**: Only $0\text{h}$ and $24\text{h}$ measurements ($v_0, v_{24}, \Delta, \text{ratio}, \text{early slope}, \text{lot-relative delta}$).
- **Targets**: Forecasts $168\text{h}$ values for leakage, IDDQ, and delay using LightGBM regressors.
- **Kinetic Drift Slope**:
  $$\text{drift\_slope} = \frac{\hat{v}_{\text{leakage}, 168\text{h}} - v_0}{168.0\,\text{hours}}$$
- **Outperforms Linear Extrapolation**: Achieves **>58% lower MAE** on leakage forecasting compared to naive linear projection.

### Unified Verdict Layer (`ml_engine/verdict_engine.py`)
Deterministic rules prioritized for space-grade flight safety (High Recall / Low False Negatives):
1. **`REJECT`**:
   - Hardware datasheet ceiling breach (`is_datasheet_breached == True`).
   - Predicted 168h value crossing absolute ceilings ($\hat{I}_{\text{leak}} \ge 50\,\mu\text{A}$, $\hat{I}_{DDQ} \ge 5\,\text{mA}$, $\hat{\tau}_{\text{delay}} \ge 8\,\text{ns}$).
   - Severe runaway drift slope ($\ge 0.20\,\mu\text{A/hr}$).
   - Critical Module A spatial outlier score ($\ge 0.85$).
2. **`REVIEW`**:
   - Borderline spatial outlier ($0.50 \le \text{score}_A < 0.85$ or `module_a_flag == True`).
   - Elevated drift rate ($\text{slope} \ge 0.12\,\mu\text{A/hr}$) or elevated forecasted leakage ($\ge 35\,\mu\text{A}$).
   - `module_b_flag == True`.
3. **`PASS`**:
   - Normal lot envelope, stable drift kinetics throughout 168h.

---

## 5. Quickstart & Execution Guide

### Prerequisites
- Python 3.11+
- Docker & Docker Compose

### Step 1: Start Containers
```bash
docker compose up -d
```
PostgreSQL 16 runs on port `5433:5432` and Redis 7 on `6379`.

### Step 2: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 3: Run Database Migrations
```bash
python -m alembic upgrade head
```

### Step 4: Run Automated Tests
```bash
python -m pytest -v
```
All **18 unit and integration tests** execute across data generator physics, schema cascades, Module A, Module B, and the Verdict layer.

### Step 5: Seed the Database
```bash
python data_engine/seed_db.py --lots 10 --components 100 --seed 42
```

### Step 6: Run Full Screening Pipeline
```bash
python ml_engine/run_screening.py
```
Pulls components from PostgreSQL, fits Module A and Module B, applies the Unified Verdict Layer, persists `ModelPrediction` records, and renders the Rich benchmark report.

---

## 6. Phase 2 Verification & Benchmark Results

```
                 ISRO Burn-In Screening Unified Verdict Triage                 
┌─────────┬────────────┬────────────┬─────────────────────────────────────────┐
│ Verdict │ Part Count │ Percentage │ Operational Meaning                     │
├─────────┼────────────┼────────────┼─────────────────────────────────────────┤
│ PASS    │        748 │     74.80% │ Cleared for space flight integration    │
│ REVIEW  │        142 │     14.20% │ Diverted to QA engineering inspection   │
│ REJECT  │        110 │     11.00% │ Strictly quarantined; defect / runaway  │
└─────────┴────────────┴────────────┴─────────────────────────────────────────┘

             Anomaly Detection Performance (Ground-Truth Defects)              
┌─────────────────────────────────┬────────┬──────────────────────────────────┐
│ Metric                          │  Value │ Significance for Mission Safety  │
├─────────────────────────────────┼────────┼──────────────────────────────────┤
│ Screening Recall (Sensitivity)  │ 80.21% │ Intercepted defect proportion    │
│ False Negative Rate (Miss Rate) │ 19.79% │ Escape rate to flight payload    │
│ Screening Precision             │ 30.56% │ Genuine anomaly confidence       │
│ F1-Score                        │ 44.25% │ Balanced precision and recall    │
│ True Positives (TP)             │     77 │ Defective parts intercepted      │
│ False Negatives (FN)            │     19 │ Defective parts missed           │
│ False Positives (FP)            │    175 │ Normal parts sent to QA review   │
└─────────────────────────────────┴────────┴──────────────────────────────────┘

              Disposition Breakdown by Physical Defect Signature               
┌───────────────────┬─────────────┬──────┬────────┬────────┬──────────────────┐
│ Ground Truth      │ Total Parts │ Pass │ Review │ Reject │   Detection Rate │
├───────────────────┼─────────────┼──────┼────────┼────────┼──────────────────┤
│ LATE_DRIFT        │          24 │    3 │     15 │      6 │ 87.5% Intercepted│
│ LEVEL_OUTLIER     │          24 │    5 │      6 │     13 │ 79.2% Intercepted│
│ NORMAL            │         904 │  729 │    107 │     68 │ 80.6% Passed     │
│ STEEP_DRIFT       │          24 │    0 │      8 │     16 │100.0% Intercepted│
│ SUBTLE_MULTIVARI… │          24 │   11 │      6 │      7 │ 54.2% Intercepted│
└───────────────────┴─────────────┴──────┴────────┴────────┴──────────────────┘

         Module B: 168h Drift Forecasting Accuracy vs Linear Baseline          
┌────────────┬────────────┬────────────┬────────────┬────────────┬────────────┐
│ Parameter  │LightGBM MAE│ Linear MAE │LightGBM RMS│ Linear RMS │MAE Reduct. │
├────────────┼────────────┼────────────┼────────────┼────────────┼────────────┤
│ leakage_ua │  2.4295 uA │  5.8321 uA │  5.4653 uA │  8.2830 uA │     +58.3% │
│ iddq_ma    │  0.0949 mA │  0.5946 mA │  0.1286 mA │  0.7520 mA │     +84.0% │
│ delay_ns   │  0.2222 ns │  1.7365 ns │  0.2776 ns │  2.1570 ns │     +87.2% │
└────────────┴────────────┴────────────┴────────────┴────────────┴────────────┘
```

---

## Phase 3: Local Deterministic Explainability & FastAPI Service Layer

Phase 3 introduces a zero-dependency local deterministic explainability engine, immutable QA review audit trails, and an asynchronous FastAPI REST service layer.

### Architecture Overview

```
                      FastAPI Application (Port 8000)
                     [backend/app/main.py (CORS :3000)]
                                     │
      ┌──────────────────────────────┼──────────────────────────────┐
      │                              │                              │
[GET /lots]                    [GET /components]              [GET /metrics/benchmark]
- Summary & triage counts      - Paginated search             - System Recall & FNR
- Parametric distributions     - Time-series profile          - Model B MAE reduction
                               - Deterministic explainer
                               - POST /reviews/{id}/action
                                     │
                 ┌───────────────────┴───────────────────┐
                 │                                       │
     Deterministic Explainer                  Inspector Review Trail
     [services/local_explainer.py]             [models/review.py]
     - Robust MAD Z-scores                     - Badge ID & Timestamp
     - Ledoit-Wolf Mahalanobis                 - Prior Verdict & Override
     - Kinetic drift rates                     - Immutable Audit Ledger
     - Zero external AI/LLMs
```

### Risk Classification Matrix

| Risk Category | Criteria | Recommended Action |
| :--- | :--- | :--- |
| `CRITICAL_RUNAWAY` | Implied drift rate $\ge 0.20\,\mu\text{A/hr}$, predicted 168h leakage $\ge 50\,\mu\text{A}$, or datasheet ceiling breach | `QUARANTINE_FLIGHT_HARDWARE` |
| `LATENT_LOT_OUTLIER` | Initial $0\text{h}$ excursion $\ge 4.0\,\text{MAD}$ above lot median or Module A score $\ge 0.85$ | `QUARANTINE_FLIGHT_HARDWARE` |
| `SUBTLE_DEGRADATION` | Mahalanobis distance $D_M \ge 3.0$, multi-parameter elevation, or Module A flag active | `HOLD_FOR_96H_CHECK` |
| `NOMINAL` | Parameters strictly within normal lot variance ($\pm 2.5\,\text{MAD}$), stable drift | `PASS_FLIGHT_READY` |

### REST Endpoints Reference

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/health` | System health check and API version status |
| `GET` | `/api/v1/lots` | Manufacturing lots with total, pass, review, and reject counts |
| `GET` | `/api/v1/lots/{lot_id}/distribution` | Lot statistical envelope (min, p25, median, p75, max, MAD) per interval |
| `GET` | `/api/v1/components` | Paginated component search filterable by `lot_id`, `verdict`, `ground_truth_flag` |
| `GET` | `/api/v1/components/{id}/profile` | Component metadata, readings time series, lot bands, predictions, and review logs |
| `GET` | `/api/v1/components/{id}/explain` | Deterministic local explanation with executive summary and technical Markdown |
| `POST` | `/api/v1/reviews/{id}/action` | Submit QA inspector disposition (`ACCEPTED`, `QUARANTINED`, `RE_TEST`) with notes |
| `GET` | `/api/v1/metrics/benchmark` | System-wide screening Recall, FNR, Precision, F1, and LightGBM MAE improvement |

### Running the FastAPI Server

```bash
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```
Interactive Swagger documentation is available at `http://localhost:8000/docs`.

