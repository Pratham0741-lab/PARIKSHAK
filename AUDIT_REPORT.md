# AUDIT REPORT — SIH 26170 (ISRO) "AI-Driven Anomaly Detection in Component Burn-In & Screening"

Audit date: 2026-09-30 · Commit audited: `cc0e3c4` (branch `master`) · Auditor scripts: `/tmp/audit_smoke.py`, `/tmp/audit_oof.py`, `/tmp/audit_fe.ts`
No project file was modified other than creation of this report.

---

## 1. Verdict: **Partially built**

The repository contains **two disconnected systems**. The **Python backend** (`ml_engine/`, `backend/`) is a genuine, PS-specific implementation: lot-relative Median/MAD + Ledoit-Wolf Mahalanobis + Isolation Forest (Module A), LightGBM regressors that predict 168h values from 0h/24h features only (Module B), a rule-based verdict engine, a per-part deterministic explainer, and a persisted inspector-review API. My smoke test confirmed that a latent-defect part (0h = 30 µA in a lot averaging 10.4 µA, never above the 50 µA limit) is flagged by both modules with a correct plain-language explanation. However, every **headline number** the project reports (recall 80.2%, leakage MAE 0.82 µA, LATE_DRIFT interception 87.5%) comes from **in-sample evaluation**: Module B is fit on all parts and then scored on those same parts. With lot-grouped out-of-fold evaluation (168h hidden), recall drops to **0.66**, LATE_DRIFT interception to **~30%**, and leakage MAE rises to **2.78 µA** (3.4× worse). There is **no false-negative-weighted scoring** anywhere. The **React UI never calls the backend**. It runs an in-browser mock with its own TypeScript pipeline, in which Module B is a linear-extrapolation formula, **the ground-truth label directly sets part status** (`generator.ts:159`), the outlier scores use 96h/168h data, the "SHAP" feature contributions are partly fabricated constants, and the "95% prediction interval" has a fixed width. That frontend data/analytics layer (`frontend/src/data/`, `frontend/src/lib/`) is also **gitignored and absent from every commit**, so a fresh clone of the repo cannot build the UI.

---

## 2. Scorecard

Legend: BE = Python backend/ML, FE = React frontend.

| ID | Result | Evidence (file:line) | Note |
|---|---|---|---|
| **D1** | PASS | `backend/app/models/reading.py` (interval_hours + 3 params, composite unique); `data_engine/generator.py:43` `INTERVALS=(0,24,96,168)`; FE `data/types.ts:31` | 4 intervals per part, stored in Postgres (BE) or in memory (FE). |
| **D2** | PARTIAL | `generator.py:46-61`, `reading.py` (leakage µA, IDDQ mA, delay ns) | All three parameters exist as real data in BE. **Temperature is not stored anywhere.** It exists only as the string `'IDDQ @ 125°C'` (FE `generator.ts:79`). FE handles only one parameter (labelled "Iddq" but in µA). |
| **D3** | PARTIAL | FE `lib/analytics/csvValidator.ts:13-152`; `DataIngestScreen.tsx`; `data/api.ts:99-134` | Real PapaParse parsing that detects missing columns, duplicates, non-numeric values and missing cells. **But** missing values are coerced to `0` and the row is still ingested (`:103`, `:115`). Duplicate rows are still ingested. Status uses hardcoded 0.15/50 limits and the actual 168h value (`:136`). **The ingested lot never gets Module A/B predictions** (`api.ts` sets no `predictionsByLot`). **No backend ingest endpoint exists.** |
| **A1** | PASS | `ml_engine/module_a_outlier.py:88-99` (per-lot median/MAD), `:117-126` (Ledoit-Wolf, IForest on lot-normalised Z), `:174-205` | Genuinely lot-relative. Composite score blends 4 sub-scores using hand-tuned offsets (e.g. `-2.5)/2.0`, `-3.2)/2.2`). FE equivalent: `OutlierDetectionScreen.tsx:34-61` (robust-Z of 168h vs lot). |
| **A2** | PASS | `/tmp/audit_smoke.py` output | Injected part: lot mean 10.38 µA, part 0h 30 / 24h 36 / 168h 48.5 µA (always < 50). Module A score **1.0**, Mahalanobis 22.6, **flag=True**, verdict REJECT. No such test exists in the repo. `tests/test_screening_engines.py:32` tests only class-mean separation. |
| **A3** | PASS | `verdict_engine.py:54-58`, `generator.py:310-317` (`is_datasheet_breached`), `module_b_drift.py:36-38` | Separate static-limit check exists. Note: `is_datasheet_breached` is computed from **all intervals including 168h**, and the verdict engine uses it as its top REJECT rule. For this seed that did not change recall (tested with the flag disabled), but it is look-ahead by design. |
| **A4** | PASS (CLI only) | `run_screening.py:347-352` (`-t`), `module_a_outlier.py:207` | Threshold 0.3/0.5/0.7/0.9 → 342/228/145/92 flagged (verified). **Not exposed via API or UI.** The FE sensitivity slider (`OutlierDetectionScreen.tsx:40-42`) only re-colours FE mock data. |
| **B1** | PARTIAL | BE `module_b_drift.py:151-163` LightGBM per parameter. FE `lib/analytics/driftForecast.ts:23-27` | BE: real regression model. **FE (what users see): `v0 + (v24-v0)/24*168`, a hardcoded formula.** Verified: `forecastDrift168h(10,11.2)=18.4=10+1.2·7`. |
| **B2** | PASS (Module B) | `module_b_drift.py:76-128`; printed `feature_columns_` | 21 features, all derived from 0h/24h (+ lot-relative 24h medians). **No 96h/168h features.** Minor: lot medians are computed over the scoring batch (transductive, 0h/24h only). **Leakage exists elsewhere:** FE outlier scores use `[v0,v24,v96,v168,slope]` (`generator.ts:182,186-190`), and the FE status uses the actual `val168h` (`generator.ts:155`). |
| **B3** | **FAIL** | `run_screening.py:131-134`; `api/v1/metrics.py:106-127`; `tests/test_screening_engines.py:83-105`; `SIH26170_EVALUATION_REPORT.md:61` | `evaluate_against_linear_baseline` does use a random 70/30 split by part, not by lot. **However, the persisted predictions, the `/metrics/benchmark` MAE, the verdict-based recall, the E2E test gates and the submitted report all use predictions from a model fit on those same parts.** Reported MAE 0.8212 µA equals the in-sample value I reproduced (0.821). Lot-held-out MAE is **2.775–3.634 µA**. |
| **B4** | PARTIAL | `module_b_drift.py:34-35,189-204`; `verdict_engine.py:29-30,78,105`; FE `generator.ts:57` | The drift rate is computed as `(pred168 − v0)/168` and compared against a limit, producing an early flag. **The "safety slope" is a hardcoded constant (BE 0.12/0.20 µA/h, FE 0.15), not calculated from lot data**, and is uniform across parameters (leakage only). In the smoke test the flag fired because pred168 ≥ 35 µA; the slope (0.106) was under 0.12. |
| **B5** | **FAIL** | BE: none (`module_b_drift.py:206-215` returns no interval). FE `driftForecast.ts:29-33` | BE has no uncertainty at all. The FE "95% prediction interval" is `1.96·max(0.5, lotSpread·√1.84)`, which is **the same ±4.786 µA for every part** (verified). It is not model-derived. |
| **E1** | **FAIL** | `run_screening.py:238-246`; `api/v1/metrics.py:97-123`; FE `lib/analytics/metrics.ts:43-67` | Only plain recall, precision, F1 and FNR. **No weighted cost, F-beta (β>1), or recall-constrained threshold selection anywhere.** Thresholds are hand-set constants. The docstring "Tuned for maximum Recall" (`verdict_engine.py:16`) is not backed by code. |
| **E2** | PASS (with caveat) | `api/v1/metrics.py:81-123`; FE `metrics.ts:25-86`, `ModelPerformanceScreen.tsx:11-30` | TP/FP/FN/TN are computed from labels vs predictions, not hardcoded. The caveat is that the inputs are in-sample (BE) or label-leaked (FE). |
| **E3** | PARTIAL | `api/v1/metrics.py:106-127`; `module_b_drift.py:217-276` | MAE is computed. **Ground-truth 168h is not hidden**: it sits in the same `burn_in_readings` table the model trains on, and there is no holdout partition or hidden-target scoring mode. |
| **E4** | PASS | `generator.py:103` (np RNG seed), `module_b_drift.py:158`, `module_a_outlier.py:124`; FE Mulberry32 `generator.ts:15` | Same seed → identical values and identical eval MAE (2.3217 twice). Component UUIDs use unseeded `uuid4()` (`generator.py:349`). The E2E/API tests depend on a live, pre-seeded Postgres and **write to it**. |
| **X1** | PARTIAL | BE `services/local_explainer.py:145-305` (per-param per-interval Z_MAD, rule trace, summary); FE `lib/analytics/explainability.ts:7-30` | BE gives real rule-based attribution plus plain language. **There is no attribution for the LightGBM prediction itself** (no SHAP or feature importance). FE "Feature Contributions (SHAP / Tree Attribution)" (`ComponentDetailScreen.tsx:117`) is **not SHAP**: `Temperature` = constant `0.62` for every part, and `Package type` = ±0.31/−0.22 chosen by the **parity of the last char of the part ID** (`explainability.ts:20-21`). |
| **X2** | PARTIAL | BE `local_explainer.py:151-195,242-277`; smoke test | BE text is generated from the part's actual Z-scores and predictions (smoke test: "32.5 MAD units above lot median in leakage current … LATENT_LOT_OUTLIER"). FE notes differ per part (1,248 distinct) but three of five contribution bars are fabricated. |
| **X3** | PARTIAL | BE `api/v1/reviews.py:22-80`, `schemas/review.py:17` (`inspector_notes` min_length=5), `models/review.py`; FE `DecisionQueueScreen.tsx:72-76`, `data/api.ts:57-83` | BE: score, threshold, rule trace, mandatory note and a persisted audit table are all present, **but the UI does not use this path**. FE: single override requires a reason, but **bulk override does not** (`useStore.ts:214` default reason). The audit log is in-memory and lost on reload, and it is seeded with fabricated events. |
| **F1** | FAIL (see §4) | — | Multiple hardcoded display values and fabricated audit and system text. |
| **F2** | PASS (BE) / PARTIAL (FE) | smoke test `[F2]` | BE: changing the injected part's 24h value from 36 to 30.5 µA changes pred168 from 47.74 to 34.63. FE metrics screens recompute from store data, but that data is label-driven. |
| **F3** | FAIL | `generator.ts:159`; `useStore.ts:255`; `ModelPerformanceScreen.tsx:47` | FE status-based recall is **exactly 1.000 for every seed and defect rate** because the label forces `Review`. At defectRate 0.2, **71 anomalies are caught only by the label clause**. The dev-modal "defect rate / static limit / safety slope" sliders are **silently ignored** (only `seed`, `lotSize` are passed). The "5-fold cross-validation" label is false. |
| **F4** | PARTIAL | `generator.py:140-147,210-212,120-124`; FE `generator.ts:105` | BE: per-lot **Gaussian** (skew 1.14 comes only from mixing benign-high lots), 5% multiplicative noise, 9.6% labelled anomalies, **93.75% of anomalies pass the static limit** (good). FE: log-normal baseline. Drift classes are deterministic step shapes (e.g. LATE_DRIFT is exactly flat at 0h/24h), so BE LATE_DRIFT is essentially undetectable early by construction. |
| **U1** | PASS | `frontend/src/App.tsx:17-27` | All 8 routes exist: lots, ingest, outliers, drift, components, decisions, model, reports. |
| **U2** | **FAIL** | `frontend/src/data/api.ts:1-5,133`; no `fetch`/axios anywhere in `frontend/src` | Every screen reads the in-browser `MockParikshakApi`. **None is connected to the FastAPI backend or the LightGBM/Ledoit-Wolf models.** |

---

## 3. Critical gaps (ordered by severity, impact on the three PS metrics)

1. **No false-negative penalisation (E1, Anomaly Detection Score).** No cost-weighted objective, F-beta or recall-constrained threshold exists anywhere. Thresholds (0.50/0.85 Module A, 0.12/0.20 slope, 35 µA) are hand-picked constants. The honest out-of-fold recall is **0.656–0.667 with 32–33 escapes out of 96 defects**, at precision 0.27.
2. **In-sample evaluation / leakage of training targets into reported metrics (B3, E3).** `run_screening.py:132-133` fits and predicts on the same parts. `/metrics/benchmark` and the submission report publish **MAE 0.82 µA (true held-out ≈ 2.3–3.6 µA)** and **LATE_DRIFT 87.5% (true ≈ 29–33%)**. The E2E test gate `recall >= 0.80` (`tests/test_e2e_workflow.py:140`) passes **only because of** this leakage.
3. **Frontend label leakage (F3).** `frontend/src/data/generator.ts:159` sets `status='Review'` when `anomalyType !== 'NORMAL'`. Every recall shown or derivable in the UI is therefore guaranteed. FE anomaly scores also use 96h/168h values (`generator.ts:182,186`).
4. **UI is not wired to the ML system (U2, B1).** The demo UI shows a linear-extrapolation "drift predictor" and a TS mock, not the LightGBM/Ledoit-Wolf backend described in the README.
5. **Frontend cannot be built from the repository.** The root `.gitignore:46` `data/` and `:14` `lib/` exclude `frontend/src/data/` and `frontend/src/lib/`. A clean `git archive HEAD` fails `tsc` with TS2307 errors across the screens. `frontend/Dockerfile` also targets Next.js (`.next/standalone`) but the app is Vite, so `docker compose build` of the frontend cannot succeed.
6. **Explainability of Module B is absent (X1).** No SHAP or feature attribution for LightGBM forecasts. FE shows fabricated "SHAP" bars.
7. **No real prediction uncertainty (B5).** BE has none; FE has a constant-width band.
8. **Safety slope is a constant (B4)**, not derived from lot statistics. It is leakage-only and single-parameter.
9. **`requirements.txt` omits `scikit-learn`**, which both `module_a_outlier.py:15-16` and `module_b_drift.py:15-16` import. It worked here only because sklearn 1.9.0 was already installed globally.
10. **Ingest path is a dead end (D3).** Ingested CSV lots get no Module A/B predictions, and bad rows are ingested with zeros.

---

## 4. Fakery / hardcoding findings

| Location | What |
|---|---|
| `frontend/src/data/generator.ts:159` | Ground-truth label drives predicted status (`anomalyType !== 'NORMAL'` → Review). |
| `frontend/src/lib/analytics/explainability.ts:21` | `tempOffset = 0.62`: identical "Temperature (Arrhenius 125°C)" contribution for every part. |
| `frontend/src/lib/analytics/explainability.ts:20` | "Package type" contribution chosen by `partId.charCodeAt(last) % 2`. |
| `frontend/src/lib/analytics/explainability.ts:19` | "Safety limit" contribution is a fixed ±1.45/−0.75. |
| `frontend/src/screens/ComponentDetailScreen.tsx:114-117` | Heading "Feature Contributions (SHAP / Tree Attribution)" with no SHAP or tree model in the FE. |
| `frontend/src/lib/analytics/driftForecast.ts:30-33` | "95% confidence interval" is a constant width independent of the part or any model. |
| `frontend/src/screens/ModelPerformanceScreen.tsx:47` | "5-fold cross-validation on kinetic burn-in parameter trajectories": no CV exists. |
| `frontend/src/screens/ModelPerformanceScreen.tsx:15` | Fallback `anomalyScore` 0.75/0.2 derived from `isFlagged`. |
| `frontend/src/data/generator.ts:290-311` | Seeded audit events: "10 issues detected in raw telemetry", "v0.9 LightGBM & Ledoit-Wolf inference complete" (no LightGBM runs in the FE), actor "A. Nair" decision. |
| `frontend/src/data/generator.ts:177` | `inspector: 'A. Nair'` assigned to every 3rd flagged part. |
| `frontend/src/store/useStore.ts:55` | Logged-in inspector hardcoded to `'A. Nair'`. |
| `frontend/src/store/useStore.ts:255` | Dev settings defectRate / staticLimit / safetySlope ignored (only seed, lotSize are used). |
| `frontend/src/data/api.ts:108-116` | Ingested lot metadata hardcoded (`W-INGEST`, `MCU`, `QFN-32`, `2416`, `IDDQ @ 125°C`, slope 0.15). |
| `frontend/src/screens/AuditReportScreen.tsx:177,181` | "ATE-03 / Thermotron Chamber", "Firmware v0.9.4-flight". |
| `frontend/src/screens/AuditReportScreen.tsx:39` | Fallback "SHA-256" hash `3f47c879…` (a 40-hex, SHA-1-length literal). |
| `frontend/src/screens/AuditReportScreen.tsx:214-216` | "Signature" auto-generated by reversing the inspector name. |
| `frontend/src/screens/AuditReportScreen.tsx:234-239` | Static "QR" pattern (mockup). |
| `frontend/src/screens/LotOverviewScreen.tsx:34,351` | `warnLimit = 20.0`, slope highlight `> 0.15` hardcoded. |
| `frontend/src/lib/analytics/csvValidator.ts:136-139` | Ingest status uses literal 0.15 / 0.08 / 50.0 on actual 168h. |
| `SIH26170_EVALUATION_REPORT.md:25-63` | Published recall/MAE/per-class figures are in-sample (reproduced exactly: MAE 0.821, LATE_DRIFT 87.5%). |
| `README.md` badge / `Makefile` help | "Next.js 15" and "Redis 7" claimed. FE is Vite + React 18, and Redis is never used by any code path found. README's "58% MAE reduction" conflicts with the report's "86.2%". |
| `ml_engine/verdict_engine.py:16` | "Tuned for maximum Recall and minimum False Negatives": no tuning code exists. |

No hardcoded metric literals such as "0.983", "38.2" or chart arrays were found inside screen components. All displayed metrics are computed at runtime, but from mock or leaked inputs as described.

---

## 5. What's solid

- **Module A (BE)** is a real lot-adaptive detector: per-lot median/MAD normalisation, Ledoit-Wolf shrunk Mahalanobis, and seeded Isolation Forest (`module_a_outlier.py`). It correctly suppresses benign-high lots (test at `tests/test_screening_engines.py:66-71`) and catches the PS's canonical "45 µA in a 10 µA lot" case.
- **Module B feature set has no target leakage.** Only 0h/24h-derived features (verified by printing `feature_columns_`). LightGBM genuinely beats linear extrapolation even out of sample (2.78 vs 6.02 µA MAE on held-out lots).
- **Data model** is clean: SQLAlchemy 2.0 plus Alembic migrations for lots, components, readings, predictions and reviews, with FK cascades and unique constraints.
- **Deterministic explainer (BE)** produces part-specific Z_MAD tables, rule traces and plain-language summaries from real values.
- **Inspector review API (BE)** enforces mandatory notes (`min_length=5`), records the original verdict, and persists an audit table.
- **Synthetic generator (BE)** is seeded, labelled, includes benign-high lots, and has 93.75% of defects passing the static limit, which is the right regime for this PS.
- **FE CSV validator** performs real parsing and detects missing columns, missing cells, non-numeric values and duplicate IDs.
- Tests are deterministic and pass (see §7).

---

## 6. Fix list (prioritised; not performed)

| # | File(s) | Change | Effort |
|---|---|---|---|
| 1 | `ml_engine/run_screening.py`, `api/v1/metrics.py` | Produce Module B predictions **out-of-fold with `GroupKFold` by `lot_id`** (or train on a fixed set of training lots and score held-out lots with 96h/168h withheld at inference). Persist OOF predictions, and compute `/metrics/benchmark` MAE and recall only on held-out parts. | M |
| 2 | new `ml_engine/scoring.py`, `verdict_engine.py`, `run_screening.py` | Implement an explicit asymmetric cost, e.g. `cost = C_fn·FN + C_fp·FP` with `C_fn ≫ C_fp`, and/or F2/F3. Select Module A/B thresholds by minimising that cost (or by maximising precision subject to recall ≥ 0.95) on OOF data. Report cost and F-beta in the API and UI. | M |
| 3 | `frontend/src/data/generator.ts:155-163,182-190` | Remove the `anomalyType !== 'NORMAL'` clause. Stop using 96h/168h in outlier features and initial status (use 0h/24h only for early decisions). | S |
| 4 | `frontend/src/data/api.ts`, `store/useStore.ts` | Implement an `HttpParikshakApi` against `/api/v1/*` (lots, components, explain, reviews, metrics) and make it the default. Keep the mock behind a flag. | L |
| 5 | root `.gitignore` | Anchor the patterns (`/data/`, `/lib/`) so `frontend/src/data` and `frontend/src/lib` are committed, then commit them. | S |
| 6 | `frontend/Dockerfile` | Replace the Next.js standalone stages with a Vite build and a static server (nginx or `vite preview`). | S |
| 7 | `requirements.txt` | Add `scikit-learn>=1.4`. | S |
| 8 | `ml_engine/module_b_drift.py`, `local_explainer.py`, `api/v1/components.py` | Add per-part SHAP (`shap.TreeExplainer`, or LightGBM `pred_contrib=True`) for the 168h forecast and expose it in `/explain`. Replace the FE fabricated contributions with these values. | M |
| 9 | `ml_engine/module_b_drift.py` | Add real uncertainty: LightGBM quantile models (α = 0.05/0.95), or conformal intervals calibrated on OOF residuals. Persist the bounds and show them in the UI. | M |
| 10 | `module_b_drift.py`, `verdict_engine.py` | Derive the safety slope from lot data (e.g. lot median early slope + k·MAD, or a physics limit such as `(static_limit − v0)/168`). Apply it per parameter and document the rule. | S |
| 11 | `backend/app/api/v1/` (new `ingest.py`) | Add CSV upload with validation. Reject or quarantine rows with missing, non-numeric or duplicate values instead of zero-filling. Trigger Module A/B on the new lot and keep 168h optional/hidden. | M |
| 12 | FE `DecisionQueueScreen.tsx`, `useStore.ts:214` | Require a comment for bulk overrides. Persist the audit log via the backend reviews API. | S |
| 13 | FE `ModelPerformanceScreen.tsx:47`, `AuditReportScreen.tsx:177-239`, `generator.ts:276-313`, `explainability.ts:19-21`, `ComponentDetailScreen.tsx:117`, `useStore.ts:255` | Remove false labels (5-fold CV, SHAP, firmware, fake signature/QR/hash fallback, fake audit events) and wire the dev-modal sliders through to the generator. | S |
| 14 | `tests/` | Add a lot-held-out Module B test, a "passes static limit but lot outlier" test (A2), and a test that recall is computed with 168h hidden. Isolate DB tests (transaction rollback or a test DB) so they stop writing reviews to the dev DB. | M |
| 15 | `data_engine/generator.py` | Use log-normal intra-lot distributions, add stochastic drift-onset variation (LATE_DRIFT with a weak early signature), and seed UUIDs (`uuid.UUID(int=rng.integers(...))`). Update `SIH26170_EVALUATION_REPORT.md` with honest OOF metrics. | M |

---

## 7. Commands run and results

| Command | Result |
|---|---|
| `git ls-files`, `git status --ignored`, `git check-ignore -v frontend/src/data/api.ts` | 101 tracked files. `frontend/src/data/` and `frontend/src/lib/` are ignored by root `.gitignore` (`data/`, `lib/`). |
| `python --version`; import check | Python 3.11.0; sklearn 1.9.0, lightgbm 4.7.0 present (sklearn is not in `requirements.txt`). |
| `python -m pytest -q -p no:cacheprovider` | **32 passed** in 19.0 s. Requires the live Postgres already seeded on localhost:5433. **Side effect: `test_api_and_explainer.py:388` and `test_e2e_workflow.py:104` POST inspector reviews, which appended 2 `inspector_reviews` rows to the local DB.** |
| `cd frontend && npx vitest run` | **12 passed** (1 file). |
| `cd frontend && npx tsc --noEmit` | 0 errors (working copy, which includes the gitignored files). |
| `cd frontend && npx vite build --outDir /tmp/audit_vite_dist` | Built OK: 424 kB JS (working copy). |
| `git archive HEAD frontend \| tar -x -C /tmp/audit_clean && npx tsc --noEmit` | **FAIL**: TS2307 "Cannot find module '../data/types' / '../lib/analytics/*'" across screens. The committed frontend does not build. |
| Lint | No lint script or config (no ESLint, ruff or flake8) in the repo. Not run. |
| Docker build | Not run. Static inspection shows `frontend/Dockerfile` copies `.next/standalone`, which a Vite build never produces. |
| `python /tmp/audit_smoke.py` | Latent part (0h 30 µA vs lot mean 10.38; max 48.5 < 50): **Module A score 1.0 flag=True**; **Module B pred168 47.74 (true 48.5), module_b_flag=True** (via the 35 µA rule; slope 0.106 < 0.12); verdict **REJECT**; explanation cites "32.5 MAD units above lot median in leakage current". In-sample leakage MAE **0.821**, lot-held-out **3.634** (linear 6.016), repo's random split **2.32**. Threshold sweep changes flag counts. Changing 24h 36→30.5 moves pred168 47.74→34.63. Same seed gives identical data and MAE. |
| `python /tmp/audit_oof.py` (GroupKFold by lot, 168h hidden) | In-sample: recall **0.812**, FN 18, precision 0.308, MAE 0.821, LATE_DRIFT 88%. **Out-of-fold: recall 0.667, FN 32, precision 0.268, MAE 2.775, LATE_DRIFT 33%** (29% with the 168h-derived breach flag disabled). |
| `esbuild /tmp/audit_fe.ts && node /tmp/audit_fe.cjs` | FE status-based recall = **1.000** for seeds 42 and 7 and for defectRate 0.2 (**71 parts flagged only by the label clause**). ModelPerf@0.5 recall 1.000 / precision 0.869 / MAE 0.86 (seed 42). Temperature contribution = **0.62 for all parts**. CI half-width **4.786 for every part**. `forecastDrift168h(10,11.2)=18.4` is an exact linear formula. |

### Step 3 smoke-test summary (requested items)
1. **Latent-defect lot:** built by injecting a part into a seeded generator lot (`/tmp/audit_smoke.py`).
2. **Module A flags it:** yes (score 1.0).
3. **Module B elevated 168h forecast and safety-slope flag:** pred168 = 47.7 µA with `module_b_flag=True`. The flag came from the 35 µA predicted-level rule, **not** the slope rule (0.106 < 0.12 µA/h).
4. **Explanation cites real factors:** yes (BE explainer: leakage, 32.5 MAD at 0h, LATENT_LOT_OUTLIER). The FE explanation for the same kind of part would include fabricated Temperature/Package bars.
5. **Recall and MAE:** both come from computed data. The honest values are **recall 0.66, leakage MAE 2.8 µA** (lot-held-out). The repository reports 0.80 / 0.82 µA, which are in-sample.


---

# Re-audit (after remediation, branch `fix/audit-remediation`)

Re-audit date: 2026-09-30. All numbers below come from `reports/evaluation_results.json`, produced by
`python -m evaluation.run` (seed 42, 10 lots, 1,000 parts, 96 defective, 5-fold GroupKFold over lots,
96h/168h and labels hidden at prediction time). `tests/test_evaluation_report.py` checks that a fresh
run reproduces them exactly.

## Updated verdict: **Built for this PS** (with the open items listed below)

The ML system is now evaluated honestly (lot-held-out, out-of-fold), decisions minimise an explicit
FN-weighted cost, and the UI is a client of the real backend. Every score, interval, explanation and
metric shown is computed from data. The remaining gaps concern data realism and the achievable
performance on this synthetic data, not fabrication.

## Held-out results vs TRAIN (optimistic)

| Metric | Held-out lots | TRAIN (in-sample) |
|---|---:|---:|
| Recall | 78.1% | 92.7% |
| Precision | 20.1% | 23.4% |
| F2 | 49.5% | 58.3% |
| Weighted cost (FN x20 + FP x1) | 718 | 431 |
| Reference: flag every part / flag none | 904 / 1920 | 904 / 1920 |
| TP / FN / FP / TN | 75 / 21 / 298 / 606 | 89 / 7 / 291 / 613 |
| LATE_DRIFT catch rate | 37.5% | 87.5% |
| Leakage 168h MAE / RMSE (uA) | 1.930 / 5.112 | 1.428 / 4.059 |
| Linear baseline MAE (uA) | 5.970 | 5.970 |
| IDDQ MAE (mA) / delay MAE (ns) | 0.0918 / 0.2059 | 0.0667 / 0.1516 |
| 90% interval coverage: leakage / IDDQ / delay | 89.0% / 91.5% / 90.9% | 98.3% / 98.6% / 98.7% |

Other figures:
- **Nested lot-grouped CV estimate for Module B** (selection inside CV): leakage MAE 2.040 uA,
  vs 3.358 for the original model.
- **Joint threshold strategy** (for comparison): cost 709, but it disables Module B's slope rule in
  5/5 folds. The default "separate" strategy keeps Module B active at cost 718.
- **Before remediation, measured the same way:** recall 64.6%, precision 25.9%, cost 857, leakage
  MAE 3.358 uA.
- **The previously reported 80.2% recall / 0.82 uA MAE** were in-sample; the in-sample MAE is
  reproduced exactly in the P0-1 commit message.

## Scorecard (re-audit)

| ID | Result | Evidence | Note |
|---|---|---|---|
| D1 | PASS | backend/app/models/reading.py; ml_engine/features.py:64 | 0/24/96/168h per part, stored and used with interval semantics. |
| D2 | PARTIAL | backend/app/models/reading.py | Leakage, IDDQ and delay are data. **Burn-in temperature is still not stored**; it appears nowhere in the schema. |
| D3 | PASS | backend/app/services/ingest.py:112, :172; backend/app/api/v1/ingest.py:40; backend/app/models/reading.py:68; tests/test_ingest.py | Missing columns reject the file; duplicates, empty IDs and non-numeric/negative cells are handled; lot-median imputation is flagged, never 0; insufficient-data parts go to REVIEW. |
| A1 | PASS | ml_engine/module_a_outlier.py:82, :161 | Each scored lot is normalised by its own median/MAD; decision = sum of positive robust z. |
| A2 | PASS | tests/test_ingest.py:106; smoke test below | 30 uA part in a 10.1 uA lot, below 50 uA: Module A score 27.39 >= 2.05. |
| A3 | PASS | ml_engine/screening.py:52; ml_engine/verdict_engine.py:50 | Static check on observed 0h/24h readings, separate from A/B; shown per part in the UI. |
| A4 | PASS | ml_engine/screening.py:142; evaluation/thresholds.py:135 | Thresholds are learned from FN_COST/FP_COST/RECALL_TARGET (settings/CLI). Changing FN_COST from 20 to 5 changed the UI (64/35/1 -> 75/25/0 pass/review/reject in lot B001). |
| B1 | PASS | ml_engine/module_b_drift.py:54; evaluation/module_b_study.py:110 | LightGBM on a log-ratio target, chosen by nested lot-grouped CV against a linear baseline. |
| B2 | PASS | ml_engine/features.py:27, :64; tests/test_evaluation_protocol.py:97 | 0h/24h only; name guard plus a perturbation test (changing 96h/168h values leaves features and forecasts unchanged). |
| B3 | PASS | evaluation/splits.py:25; evaluation/crossfit.py:58, :88; tests/test_evaluation_protocol.py:68 | GroupKFold over lots; a spy model proves no test-lot part reaches training. Persisted predictions are all out-of-fold (cv_fold). |
| B4 | PASS | ml_engine/safety_slope.py:70, :86; tests/test_safety_slope.py:24 | Per-lot, per-parameter slope = lot median + k x spread; k is cost-learned; the derivation is persisted and shown. |
| B5 | PASS | ml_engine/module_b_drift.py:124; ml_engine/screening.py:158; tests/test_intervals.py:20, :45 | CQR intervals per part; held-out coverage is computed (89.0-91.5%). |
| E1 | PASS | evaluation/cost.py:17, :55; evaluation/thresholds.py:47; tests/test_cost_thresholds.py:26, :51 | FN_COST = 20 x FP_COST by default; F2; cost per 1,000; FN-monotonicity test. |
| E2 | PASS | evaluation/score.py:38; backend/app/api/v1/metrics.py:66 | Confusion matrix, recall and precision computed from predictions vs separately held truth. |
| E3 | PASS | evaluation/score.py:101; evaluation/crossfit.py:88 | Truth is hidden at prediction time and joined only in scoring (`python -m evaluation.score --predictions --truth`). |
| E4 | PASS | data_engine/generator.py:120; tests/test_evaluation_report.py:10 | Seeded RNG and seed-derived IDs; the report reproduces exactly. |
| X1 | PASS | ml_engine/module_b_drift.py:136; ml_engine/module_a_outlier.py:177; ml_engine/explain.py:81 | TreeSHAP (pred_contrib) plus Module A's exact decomposition plus a plain-language justification. |
| X2 | PASS | tests/test_explanations.py:40; backend/app/api/v1/components.py:279 | Every part gets distinct text; the named top contributor is the argmax of \|contribution\|. |
| X3 | PASS | backend/app/schemas/review.py:19; frontend/src/components/layout/DecisionDialog.tsx:24; backend/app/api/v1/reviews.py:71; backend/app/api/v1/audit.py:33 | Score, threshold and rule trace per part; every override (single, bulk, keyboard) needs a comment; persistent audit log. |
| F1 | PASS | repo-wide grep (see Commands) | No hardcoded display metrics, part IDs or intervals remain outside seeded generators and fixtures. |
| F2 | PASS | frontend/src/data/api.ts:81, :242; frontend/src/screens/ModelPerformanceScreen.tsx:12 | UI metrics come from /metrics; a changed backend output changes the UI (verified live). |
| F3 | PASS | tests/test_api_and_explainer.py:242; frontend/src/data/offlineDemo.ts:81 | No label reaches the UI (the API test walks the full payload); the offline demo is labelled and its statuses are invariant to 96h/168h. |
| F4 | PARTIAL | data_engine/generator.py | Seeded, noisy, labelled, most defects below the limit. **Still per-lot Gaussian (not log-normal).** LATE_DRIFT has no 0h/24h precursor by construction; left unchanged on purpose, because altering it would make results look better without making the system better. |
| U1 | PASS | frontend/src/App.tsx:17 | All 8 routes. |
| U2 | PASS | frontend/src/data/api.ts:242; screens | Every screen reads backend data; the offline demo is explicit and exposes no metrics. |

## Smoke test (repeated through the UI and the real backend)

Ingested `frontend/public/example_ingest.csv` from the Ingest screen as lot SMOKE-LATENT-10UA:
- **Validation (backend):** 64 rows, 63 accepted, 1 duplicate, 1 non-numeric, 2 imputed,
  2 insufficient-data parts.
- **Screening:** 63 parts screened (36 PASS / 22 REVIEW / 5 REJECT).

EX-LATENT-001 (0h 30.0, 24h 36.0 uA; lot median 10.13 uA; below 50 uA at every interval):
- **Module A** score 27.39 >= 2.05, leakage +27.1 lot-MADs → flag.
- **Module B** predicted drift 0.2966 uA/h > lot safety slope 0.01936 uA/h
  (= 0.00141 + 4.89 x 0.00367) → flag.
- **Verdict REJECT.** The explanation names leakage and the 0-24h change robust z as the drivers.
- **Caveat:** the forecast (79.8 uA) overshoots the true 168h value (48.5 uA). The 90% interval
  (31.3-98.3 uA) contains it.

## Still open

1. **Achievable performance is modest.** Held-out cost 718 vs 904 for flagging every part; precision
   20%. The oracle diagnostic, with thresholds tuned on the held-out data itself, reached only about
   752 with the earlier scores. The limit is in the data.
2. **LATE_DRIFT is undetectable at 24h in this generator:** its 37.5% catch rate is about the 33%
   normal-part flag rate.
3. **Thresholds vary across folds** (Module B k 2.5-8.2) with only 8 training lots per fold.
4. **Temperature (D2) and log-normal/precursor realism (F4)** are not addressed.
5. **Out-of-distribution forecasts can overshoot** (see smoke test); intervals widen but point
   forecasts are unreliable there.
6. **Docker:** images build and the backend image imports the full stack, but `docker compose up`
   of the whole stack was not run end to end.
7. **Minor:** ESLint 9 prints a deprecation notice; long part IDs wrap in narrow table columns;
   lot SMOKE-LATENT-10UA remains in the dev DB as a demo (delete the lot to remove it).

## Commands run (final verification)

| Command | Result |
|---|---|
| `python -m ruff check .` | All checks passed |
| `python -m pytest -q` (isolated `burn_in_test_db`) | 71 passed; dev DB counts unchanged (inspector_reviews 0 -> 0) |
| fresh venv: `pip install -r requirements-dev.txt` + pytest | 69 passed at P1-8 (all tests at that point) |
| `cd frontend && npm run lint` / `npx tsc --noEmit` / `npx vitest run` / `npm run build` | clean / clean / 10 passed / built |
| `git clone . /tmp/clean && cd /tmp/clean/frontend && npm ci && npx tsc --noEmit && npm run build` | success |
| `docker build frontend` (clean clone) / `docker build -f backend/Dockerfile .` + import check | built (74 MB) / imports OK after adding libgomp1 |
| grep for `0.983`, `38.2`, `U-0342`, `ISR-24`, `4.79`, `80.21`, `0.8212`, `Next.js`, `Redis 7` (excluding node_modules, this report) | only `0.983` in reports/evaluation_results.json (a computed TRAIN coverage value) |


---

# T1–T7 follow-up (branch `feat/judge-mode`, on top of master `47b9c77`)

Every number below was produced by the code at the cited lines; none is typed into the UI.

## T1: One-command stack, smoke test, browser check
- `docker compose down -v && docker compose up --build` comes up from a clean checkout. Re-run after T7 with UP_EXIT=0.
  - Startup order is postgres → one-shot `burnin_init` (migrate, seed, out-of-fold screening) → backend → frontend: `docker-compose.yml:38`, `docker-compose.yml:70`.
  - The model artifact lives on a named volume: `docker-compose.yml:101`.
  - nginx also listens on IPv6 (it previously failed its healthcheck on Alpine): `frontend/nginx.conf:3`.
- `scripts/smoke_test.sh` → `scripts/smoke_test.py:99` covers health, lots, ingest, parts, predictions, explanations and decisions, the injection and perturbation scenarios, and restart persistence (`--restart`). Final run on the clean 40-lot physics stack: **SMOKE TEST PASSED**.
  - Injection: LATENT-001 at 30 µA in a lot with median 10.05 µA, never above the 50 µA limit. Module A 32.45 ≥ 1.26; Module B drift z 102.56 ≥ k 2.00; verdict REJECT.
  - Perturbation: changing one 24h value moved the forecast from 10.453 to 50.472 µA and changed the explanation.
  - Persistence: the ingested lot, prediction, decision and explanations all survive `docker compose restart`.
- `frontend/scripts/screenshots.mjs` checks every screen against a fresh API read: error banners, console errors, failed requests, stale values, the data-source tag, and the Recompute result.
  - Final run: lots, ingest, outliers, drift, components, decisions, model, reports and judge, plus the judge-flow and ingest-flow interaction checks, are all **OK**. Screenshots are in `reports/screenshots/*.png`.
  - Earlier problems found and fixed in T1: "µA" rendered as "MA" (CSS uppercase), truncated Drift part IDs, and a stale lot status of INGESTED.

## T2: Merge
- `fix/audit-remediation` was merged into master as `47b9c77` (no force-push). Nothing needed a manual decision.
- T3–T7 are on `feat/judge-mode` and are **not** merged into master.
- Local master is 22 commits ahead of `origin/master`. Nothing has been pushed.

## T3: Test conditions as data
- `temperature_c`, `test_parameter`, `unit`, `static_limit`, `conditions_assumed` and `source_detail` are stored on the lot: `backend/app/models/lot.py:62`.
- Defaults are flagged "assumed": `ml_engine/conditions.py`.
- Arrhenius factor: `ml_engine/conditions.py:39`.
- Module B's lot-level feature comes from lot metadata only: `ml_engine/features.py:125`.
- Conditions are shown in the lot header and in the audit report: `frontend/src/screens/LotOverviewScreen.tsx:7`, `frontend/src/screens/AuditReportScreen.tsx:5`.

## T4: Physics generator
- `data_engine/physics_generator.py:60`:
  - log-normal lot baselines with Arrhenius temperature dependence;
  - power-law drift, with the exponent range and citation comment at `:16`;
  - heteroscedastic noise (`:23`);
  - latent parts that pass the static limit at every time point (`:158`), with 24h signal mix clear / partial / none = 0.40 / 0.25 / 0.35 (`:57`).
- The legacy generator stays selectable with `--generator legacy`.
- The report uses lot-grouped CV for both generators, and states that **the generator change alters every number**: `evaluation/run.py:209`.
- Threshold variance across folds: `evaluation/run.py:161`.

Final held-out numbers (`SIH26170_EVALUATION_REPORT.md`, reproduced live on the Model screen of the clean stack):

| Held-out | Physics (primary, 40 lots / 4000 parts) | Legacy (10 lots / 1000 parts) |
|---|---:|---:|
| Recall / precision / F2 | 86.4% / 15.6% / 45.4% | 78.1% / 20.1% / 49.5% |
| Weighted cost (FN×20+FP×1) vs flag-everything | 3099 vs 3580 | 718 vs 904 |
| Leakage 168h MAE / RMSE (linear baseline MAE) | 1.906 / 6.10 (3.68) | 1.930 / 5.11 (5.97) |
| 90% interval coverage | 90.4% | 89.0% |
| LATE_DRIFT catch rate | 59.7% | 37.5% |
| Threshold A / k across folds | 1.287±0.031 / 1.994±0.653 | 2.155±0.467 / 5.530±2.758 |

Honest reading:
- On physics data, latent parts with **no** 24h signal are flagged at 59.0%. NORMAL parts are flagged at 54.7%, so for these parts the model is barely better than chance.
- The detections come from parts that carry signal by 24h: clear 88.8%, partial 82.9%.
- The model beats flag-everything by only 13% in cost.

## T5: Judge mode
- Train: `POST /api/v1/judge/train` (`backend/app/api/v1/judge.py:104`) → `ml_engine/judge.py:158`.
  - Runs as a background job, needs no labels, and persists the model with the data sha256.
  - Labels, if present, are used only to choose thresholds on out-of-fold (OOF) predictions.
  - Files with fewer than 3 lots get a within-file split labelled "single-lot, less reliable" (`ml_engine/judge.py:39`).
- Labels-free rule LFR-1 (`evaluation/rules.py:17`): static limit, lot-relative drift ln(v168/v24), or a 168h outlier, using the fixed Iglewicz–Hoaglin cut-off 3.5. The rule text is shown in the UI and is never used at inference.
  - Agreement with the physics generator's hidden labels (40 lots): it catches 251/251 drift defects and 79/88 level outliers, with 13/3580 false positives on NORMAL parts.
  - It misses most SUBTLE_MULTIVARIATE parts (19/81 caught), as expected for a single-parameter rule.
- Predict: `POST /judge/predict` (`judge.py:155`) uses only 0h/24h; 96h, 168h and label columns are dropped before the model.
  - Export columns: `ml_engine/judge.py:38`.
- Score: `POST /judge/score` (`judge.py:194`) and `python -m evaluation.score --predictions preds.csv --truth truth.csv` both call `evaluation/score.py:168` on the same bytes.
  - Identity is asserted in `tests/test_judge.py:124` and in the browser judge-flow check.
- UI: "Trained on <file>, <n> parts, <k> lots" (`frontend/src/screens/JudgeScreen.tsx:128`), the rule, predictions with explanations, and a score panel with MAE, recall, cost and the confusion matrix.

Example run (`examples/judge/`, physics seed 7: train on 12 lots without labels, test on 4 other lots):

| | OOF on training file | Unseen test lots vs generator labels |
|---|---:|---:|
| Recall / precision | 94.3% / 9.4% | 92.3% / 12.3% |
| Cost vs flag-everything | **888 vs 873** | **317 vs 281** |
| Leakage MAE / 90% PI coverage | 3.08 / 91.1% | 2.72 / 89.7% |

On these files judge mode does **not** beat flagging every part. At 20:1 cost, with about 12 training lots and no labels, the selected thresholds flag about 90% of parts. The UI prints a warning whenever the model's cost is not below flag-everything.

## T6: Robust ingest
- One reader for ingest, judge mode and scoring: `data_engine/tabular.py`.
  - Header interpretation (`:167`) and parameter matching including fuzzy (`:148`): `Iddq_0h`, `I_0`, `T0`, `leakage (nA) @ 24 h`, misspellings.
  - Unit conversion table: `:47`. A converted or implausible unit requires confirmation (`:485`), enforced at `backend/app/api/v1/ingest.py:55` and by the UI checkbox (`DataIngestScreen.tsx:133`).
  - Wide, long and tidy layouts; delimiter sniffing; missing 96h; blank, non-numeric and negative cells become NaN, never 0. Ingest then imputes the lot median for display only and sends the part to REVIEW.
  - Duplicate IDs are rejected with the first line cited. Issues carry file lines, and clicking one shows that line (`DataIngestScreen.tsx:174`).
  - Streamed parse: `_HashingReader` at `:233`. Raw-body `POST /ingest/stream` at `ingest.py:142`, with bulk inserts.
- Tests: `tests/test_robust_ingest.py` (18 tests). They include a streamed ingest of 10,000 parts in nA, with a 409 until the units are confirmed and values stored in µA (`:149`).
- Example of every case in one file: `examples/ingest_messy.csv`.
- Decision: the production model needs all three parameters, so ingest rejects a file that lacks one and points to Judge mode, which trains on whatever parameters the file has.

## T7: Provenance tag, recompute, hardcode sweep
- A permanent tag on every screen (`frontend/src/components/layout/DataSourceBar.tsx:16`, mounted at `WorkspaceLayout.tsx:23`) shows one of:
  - `UPLOADED: <file>` (sha256 in the tooltip);
  - `SYNTHETIC seed=<n> generator=<name>`;
  - `MANUAL ENTRY`;
  - on the Judge screen, its own uploaded files.
- Lots seeded before T3 have no recorded provenance and are tagged as such rather than given a guessed seed.
- The debug "Recompute" button calls `backend/app/api/v1/debug.py:22`, which recomputes from raw SQL rows in plain Python and compares against every visible metric and lot count. Final run: "all 136 visible values match raw data".
  - Test: `tests/test_debug_recompute.py:19`.
- Hardcode sweep: the only display literal found was the Judge screen's "90% PI coverage" label. It now reads the coverage target from `/config` (`JudgeScreen.tsx:42`). The remaining numeric literals are chart geometry.

## Still open after T1–T7
- Judge mode on small unlabelled files is not cost-effective at 20:1 (see T5); this needs more lots or labels.
- Latent parts with no 24h signal are near chance on physics data. No 0h/24h method can catch them by construction.
- Ingest stores a multi-lot file as one lot (with a warning); lot-relative statistics then mix lots.
- The user's local `.env` still has `DEFAULT_NUM_LOTS=10`. I did not touch it. Docker uses the compose environment, so the stack seeds 40 lots.
- `design/reference.pdf` is untracked and was left uncommitted.
