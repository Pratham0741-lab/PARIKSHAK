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
