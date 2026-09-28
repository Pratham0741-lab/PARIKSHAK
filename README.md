# ISRO SIH26170: Anomaly Detection in Component Burn-In & Screening
## Phase 1: Foundation Layer, Database Schema & Synthetic Physics Engine

![ISRO SIH26170 Architecture](https://img.shields.io/badge/Project-ISRO%20SIH26170-blue.svg)
![Python 3.11](https://img.shields.io/badge/Python-3.11%2B-brightgreen.svg)
![PostgreSQL 16](https://img.shields.io/badge/PostgreSQL-16-blue.svg)
![Redis 7](https://img.shields.io/badge/Redis-7-red.svg)
![SQLAlchemy 2.0](https://img.shields.io/badge/SQLAlchemy-2.0-orange.svg)
![Alembic](https://img.shields.io/badge/Alembic-1.14-purple.svg)

---

## 1. Architectural Overview

This repository houses the foundational infrastructure for **ISRO SIH26170**: Anomaly Detection in Component Burn-In and Screening for high-reliability space-grade semiconductor components.

During burn-in screening, parts are subjected to thermal and electrical stress across standardized intervals ($t \in [0, 24, 96, 168]$ hours) to accelerate latent defects. Standard limit screening fails when:
1. Parts drift excessively while staying within static absolute datasheet limits.
2. Fabrication lots experience normal batch-to-batch baseline process shifts (e.g. `BENIGN_HIGH_LOT`).
3. Subtle anomalies degrade concurrently across multiple correlated parameters ($I_{leakage}$, $I_{DDQ}$, propagation delay) without triggering individual 3-sigma univariate alarms.

Phase 1 establishes:
- **Orchestration**: Docker Compose deploying PostgreSQL 16 with persistent volume and healthcheck + Redis 7.
- **Database Layer**: SQLAlchemy 2.0 async and sync engines with complete Alembic migrations.
- **Data Model**: Strongly typed, relational schema tracking `Lot`, `Component`, and multi-interval `BurnInReading`.
- **Synthetic Physics Engine**: A mathematically grounded generator emulating semiconductor physics, batch-level wafer shifts, sensor noise, and targeted defect signatures.
- **Database Seeder**: High-throughput CLI bulk ingestion script streaming 8,000+ readings/sec into PostgreSQL.

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
│   │       └── 9635d36eca2d_initial_burn_in_schema.py # Initial migration
│   └── app/
│       ├── core/
│       │   ├── config.py           # Pydantic BaseSettings with computed URLs
│       │   └── database.py         # Sync (psycopg2) & Async (asyncpg) engines
│       └── models/
│           ├── base.py             # SQLAlchemy 2.0 DeclarativeBase
│           ├── lot.py              # Lot ORM entity & LotStatus enum
│           ├── component.py        # Component entity & GroundTruthLabel enum
│           └── reading.py          # BurnInReading entity with composite indexes
├── data_engine/
│   ├── generator.py                # BurnInSyntheticGenerator physics engine
│   └── seed_db.py                  # High-performance bulk database seeder CLI
└── tests/
    ├── test_generator.py           # Mathematical & physics verification tests
    └── test_models.py              # Schema, cascade delete, & async session tests
```

---

## 3. Database Schema Specification

### Entity Relationship Diagram (ERD)

```mermaid
erDiagram
    LOTS ||--o{ COMPONENTS : contains
    COMPONENTS ||--o{ BURN_IN_READINGS : records

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
```

### Constraints & Indexes
1. **Cascade Delete**: Deleting a `Lot` triggers an `ON DELETE CASCADE` down through `Component` and `BurnInReading`.
2. **Unique Constraints**:
   - `uq_component_lot_serial`: Ensures serial numbers are unique per lot.
   - `uq_reading_component_interval`: Prevents duplicate interval readings per component.
3. **Compound Indexes**:
   - `ix_readings_component_interval` on `(component_id, interval_hours)` for rapid time-series retrieval.
   - `ix_components_lot_id_flag` on `(lot_id, ground_truth_flag)` for lot-level anomaly slicing.

---

## 4. Synthetic Physics Engine (`data_engine/generator.py`)

The `BurnInSyntheticGenerator` emulates the physical degradation phenomena of semiconductor ICs:

### A. Batch Fab Variation & Baselines
- **Nominal Lots**: Drawn from $\mathcal{N}(\mu_{leak}=12.0\,\mu\text{A}, \sigma=1.5\,\mu\text{A})$, $\mathcal{N}(\mu_{iddq}=1.5\,\text{mA}, \sigma=0.15\,\text{mA})$, and $\mathcal{N}(\mu_{delay}=4.2\,\text{ns}, \sigma=0.25\,\text{ns})$.
- **Sensor Noise**: Gaussian measurement error injected per reading: $\sigma_{\text{noise}} = 0.05 \times \text{value}$.

### B. Defect Signatures
| Defect Label | Physics & Mathematical Formulation | Screening Behavior |
| :--- | :--- | :--- |
| **`NORMAL`** | Stable operation with slight infant settling ($\approx 1.5\%$ decrease across $168\,\text{h}$) plus sensor noise. | In-spec baseline. |
| **`LEVEL_OUTLIER`** | Sits $4.0$ to $6.0$ empirical MADs above lot median from $t=0\,\text{h}$; stationary across all intervals, strictly $< 50\,\mu\text{A}$. | Early static outlier. |
| **`STEEP_DRIFT`** | Starts at lot baseline at $0\,\text{h}$; monotonic progressive degradation past $35\,\mu\text{A}$ by $168\,\text{h}$. | Progressive wear-out. |
| **`LATE_DRIFT`** | Flat across $0\,\text{h}$, $24\,\text{h}$, and $96\,\text{h}$; surges upward sharply between $96\,\text{h}$ and $168\,\text{h}$ ($> 35\,\mu\text{A}$). | Latent gate oxide rupture. |
| **`SUBTLE_MULTIVARIATE`** | Sits at $+1.8\times\text{MAD}$ across $I_{leakage}$, $I_{DDQ}$, and propagation delay simultaneously. | Evades 3-sigma univariate rules; detectable via Mahalanobis distance. |
| **`BENIGN_HIGH_LOT`** | Elevated wafer baseline ($\sim 22\,\mu\text{A}$) with zero drift and normal internal variance. Parts retain `NORMAL` label. | Tests adaptive lot normalization vs fixed limits. |

---

## 5. Quickstart & Execution Guide

### Prerequisites
- Python 3.11+
- Docker & Docker Compose

### Step 1: Clone & Configure Environment
```bash
cp .env.example .env
```
Default ports configured:
- PostgreSQL host port: `5433` (container port: `5432` to avoid local host port collisions).
- Redis host port: `6379`.

### Step 2: Launch Docker Services
```bash
docker compose up -d
```
Verify container health:
```bash
docker ps --filter "name=burnin"
```

### Step 3: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 4: Run Database Migrations
```bash
python -m alembic upgrade head
```

### Step 5: Run Automated Tests
```bash
python -m pytest -v
```
All 14 tests validate the generator mathematics, physics signatures, ORM constraints, cascade deletes, and async sessions.

### Step 6: Seed the Database
Run the high-performance bulk database seeder:
```bash
python data_engine/seed_db.py --lots 10 --components 100 --seed 42
```

CLI Options:
- `--lots` / `-l`: Number of lots to generate (default: `10`).
- `--components` / `-c`: Components per lot (default: `100`).
- `--seed` / `-s`: Deterministic random seed (default: `42`).
- `--batch-size` / `-b`: Chunk size for bulk inserts (default: `2000`).
- `--no-drop`: Append to existing records instead of truncating tables.
- `--dry-run`: Generate and display distribution without writing to database.

---

## 6. Verification & Benchmarks

Executing the seeder with 10 lots and 100 components/lot produces:
- **Total Records Ingested**: 10 lots, 1,000 components, 4,000 readings.
- **Ingestion Time**: $\approx 0.47$ seconds ($>8,500$ readings/second).
- **Anomaly Breakdown**:
  - `NORMAL`: 904 (90.4%)
  - `LEVEL_OUTLIER`: 24 (2.4%)
  - `STEEP_DRIFT`: 24 (2.4%)
  - `LATE_DRIFT`: 24 (2.4%)
  - `SUBTLE_MULTIVARIATE`: 24 (2.4%)
- **Datasheet Breaches**: 6 gross defects; 90 subtle in-spec screening outliers.
