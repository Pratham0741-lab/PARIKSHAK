# SIH 26170 (ISRO): AI-Driven Anomaly Detection in Component Burn-In & Screening

Lot-relative outlier detection (Module A), early 168h drift forecasting from 0h/24h readings
(Module B), FN-weighted decisions, per-part explanations and a QA inspector workflow, served by a
FastAPI backend (PostgreSQL) with a React (Vite) UI.

**Performance numbers are not quoted here.** They are generated from data by
`python -m evaluation.run` into [SIH26170_EVALUATION_REPORT.md](SIH26170_EVALUATION_REPORT.md)
(held-out lots, with the TRAIN / held-out gap shown side by side) and served live by
`GET /api/v1/metrics/benchmark`. `tests/test_evaluation_report.py` fails if the committed report
does not match a fresh run.

---

## Quick start

```bash
docker compose up -d burnin_postgres       # PostgreSQL on :5433
pip install -r requirements-dev.txt        # pinned; Python 3.11
python scripts/bootstrap.py --no-server    # migrate, seed 10 lots x 100 parts (seed 42), run screening
cd frontend && npm ci && cd ..
make dev                                   # API http://localhost:8000/docs, UI http://localhost:8080
```

Full containerised stack, from a clean checkout: `docker compose up --build` (UI :8080, API :8000).
Startup order: postgres → `burnin_init` (migrations, seeding, out-of-fold screening; exits 0) →
backend → frontend. The model artifact lives on the `burnin_model_artifacts` volume.

Checks against the running stack:

```bash
scripts/smoke_test.sh                       # health, ingest, predictions/explanations/decisions,
                                            # 30 uA-in-10 uA injection, 24h perturbation, restart persistence
cd frontend && node scripts/screenshots.mjs # all 8 screens -> reports/screenshots/*.png; fails on
                                            # error banners, console errors, failed requests, stale values
```

| Command | What it does |
|---|---|
| `make test` | Python tests (on an isolated `burn_in_test_db`; the dev DB is guarded) |
| `cd frontend && npm test` | Frontend tests (Vitest) |
| `make lint` | ruff + ESLint |
| `make eval` | Held-out evaluation, regenerates the report |
| `python -m evaluation.module_b_study` | Nested lot-grouped CV model selection for Module B |
| `python -m evaluation.module_a_dev_study` | Module A decision-statistic selection on development seeds |
| `python ml_engine/run_screening.py [--fn-cost 20 --fp-cost 1 --report-train]` | Screen all labelled lots out-of-fold, persist predictions, save the model artifact |
| `python -m evaluation.score --predictions p.csv --truth t.csv` | Score predictions against separately held ground truth |

---

## How it works

**Data.** Each part has leakage current (µA), IDDQ (mA) and propagation delay (ns) at 0h, 24h, 96h
and 168h of burn-in (`burn_in_readings`); each lot stores its test conditions (temperature, monitored
parameter, unit, static limit; defaulted values are flagged "assumed"). Two seeded generators:
`physics` (default, `data_engine/physics_generator.py`: log-normal lots, Arrhenius temperature
dependence, power-law drift, heteroscedastic noise, latent parts with clear/partial/no 24h signal,
40 lots) and `legacy` (`data_engine/generator.py`, `--generator legacy`). The evaluation report runs a
pinned protocol for each and lists them side by side. CSV ingest (`POST /api/v1/ingest`) stores unlabelled production lots; missing cells are
imputed with the lot median and flagged (never zero-filled), and parts missing a 0h/24h value are
sent to REVIEW without a model score.

**Only 0h and 24h readings are model inputs.** `ml_engine/features.py` drops later intervals before
building features and raises if a 96h/168h-derived column reaches a feature matrix.

**Module A (lot-relative outliers).** Each part is compared with its own lot's median and MAD of
the 0h/24h mean. The decision score is the sum of positive robust z-scores over the three
parameters (chosen on development seeds, `evaluation/module_a_dev_study.py`). Mahalanobis
(Ledoit-Wolf) and Isolation Forest scores are reported as diagnostics.

**Module B (drift forecast).** LightGBM predicts `log(v168 / v24)` per parameter from 0h/24h
values and lot-relative features. The configuration was chosen by nested lot-grouped CV against
a linear-extrapolation baseline (`ml_engine/module_b_config.json`). Per-part 90% prediction
intervals come from conformalised quantile regression calibrated on inner out-of-fold residuals.
The **safety slope** is calculated per lot and per parameter: lot median of predicted drift rates +
k × lot spread. A part is flagged when its predicted rate exceeds it.

**Decisions.** flag = Module A ∪ Module B (plus datasheet rules: an observed breach, or a forecast
breach at 168h). Module A's threshold and Module B's k are chosen by minimising
`FN_COST × FN + FP_COST × FP` (default 20 : 1, configurable) on inner lot-grouped cross-validation
of the training lots, and are persisted with the model (`artifacts/`, `screening_runs`).

**Evaluation.** Lots are split with GroupKFold. Every persisted prediction is out-of-fold, i.e. made
by a model that never saw the part's lot. Metrics: recall, precision, F2, FN-weighted cost (with the
flag-all / flag-none reference costs), confusion matrix, 168h MAE/RMSE vs. linear baseline, interval
coverage, and catch rate per defect class.

**Explainability.** Per part: Module A's exact additive decomposition (robust z per parameter vs the
lot median), Module B's TreeSHAP contributions (LightGBM `pred_contrib`), the safety-slope
derivation, the prediction interval and the static-limit status, rendered into a plain-language
justification (`ml_engine/explain.py`, `GET /api/v1/components/{id}/explain`).

**QA workflow.** Every disposition requires an inspector ID and a written justification
(`POST /api/v1/reviews/{id}/action`) and is written to the audit log (`GET /api/v1/audit`).

---

## Layout

```
backend/        FastAPI app, SQLAlchemy models, Alembic migrations, services (ingest, screening, lot stats)
ml_engine/      features, Module A, Module B, safety slope, verdict engine, ScreeningModel, explainer, pipeline CLI
evaluation/     lot-grouped splits, cross-fitting, cost scoring, threshold selection, report + studies
data_engine/    seeded synthetic generator and DB seeder
frontend/       React + Vite UI (HttpApi to the backend; labelled offline demo mode)
reports/        committed evaluation / study results (JSON)
tests/          pytest suite (isolated test database)
```

## Known limitations

- Data is synthetic. In the generator, `LATE_DRIFT` parts are indistinguishable from normal parts
  at 24h by construction, so no 0h/24h method can reliably catch them. Their held-out catch rate is
  reported separately in the evaluation report.
- The dataset has 10 lots. Lot-grouped CV folds are small, and the chosen thresholds vary between
  folds (listed per fold in the report).
- Module B forecasts for parts far outside the training range (e.g. extreme early drift) can
  overshoot. The conformal interval widens for such parts.
