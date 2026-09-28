# ISRO SIH26170: Official Evaluation & Benchmark Report
**Problem Statement:** Anomaly Detection in Component Burn-In & Screening  
**Generated:** `2026-09-28 20:57:57 UTC`  
**Architecture:** Module A (Lot-Adaptive Spatial Outlier Detector) + Module B (24h Early Drift Forecaster) + Deterministic Local Explainability Engine  
**AI/LLM Dependencies:** ZERO (100% Deterministic Local Statistics & Tree Ensembles)

---

## Executive Summary

This report documents the rigorous quantitative evaluation of our semiconductor burn-in screening platform for mission-critical aerospace hardware. The platform combines:
1. **Module A (Spatial Lot-Adaptive Outlier Detection):** Robust Median/MAD standardization, Ledoit-Wolf covariance shrinkage Mahalanobis distance ($D_M$), and Isolation Forest density filtering.
2. **Module B (24h Early Degradation Forecaster):** LightGBM gradient-boosted regressors predicting 168h end-of-test values from only 0h and 24h milestone data.
3. **Deterministic Explainability Engine:** Zero-LLM local attribution generating aerospace-grade engineering justifications, MAD excursion tables, and risk classifications.
4. **QA Review Workbench:** Immutable human review audit trail for borderline part dispositions (`ACCEPTED`, `QUARANTINED`, `RE_TEST`).

---

## 1. System Screening Performance (Mission Safety Gates)

In space hardware assurance, **Screening Recall (minimizing False Negatives)** is the paramount objective to prevent latent defect parts from escaping to flight payloads.

| Metric | Measured Value | Target Gate | Aerospace Significance |
| :--- | :---: | :---: | :--- |
| **Screening Recall (Sensitivity)** | **80.21%** | $\ge 80.0\%$ | **PASS**: Over 80% of latent physical defects intercepted |
| **False Negative Rate (Miss Rate)** | **19.79%** | $\le 20.0\%$ | **PASS**: Escape rate to flight package strictly contained |
| **Screening Precision** | **30.56%** | $\ge 25.0\%$ | **PASS**: High true-anomaly density in quarantine queue |
| **F1-Score** | **44.25%** | $\ge 40.0\%$ | **PASS**: Balanced harmonic precision and recall |
| **True Positives (TP)** | **77** | -- | Defective components intercepted |
| **False Negatives (FN)** | **19** | -- | Escaped defective components |
| **False Positives (FP)** | **175** | -- | Normal parts escalated to QA review workbench |
| **True Negatives (TN)** | **729** | -- | Nominal units cleared for space payload |

---

## 2. Detection Breakdown by Physical Defect Signature

The synthetic benchmark emulates physics-based semiconductor failure modes:
- `LEVEL_OUTLIER`: Initial oxide / doping contamination at $t=0\text{h}$.
- `STEEP_DRIFT`: Severe exponential thermal runaway kinetics.
- `LATE_DRIFT`: Subtle incubation leading to late 96h–168h degradation.
- `SUBTLE_MULTIVARIATE`: Simultaneous small multi-parameter drift requiring covariance shrinkage.
- `NORMAL`: Nominal manufacturing variation across the wafer.

| Physical Defect Class | Total Units | PASS | REVIEW | REJECT | Interception / Pass Rate |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `NORMAL` | 904 | 729 | 107 | 68 | **80.6% Normal Pass Yield** |
| `LEVEL_OUTLIER` | 24 | 5 | 6 | 13 | **79.2% Intercepted** |
| `STEEP_DRIFT` | 24 | 0 | 8 | 16 | **100.0% Intercepted** |
| `LATE_DRIFT` | 24 | 3 | 15 | 6 | **87.5% Intercepted** |
| `SUBTLE_MULTIVARIATE` | 24 | 11 | 6 | 7 | **54.2% Intercepted** |

---

## 3. Module B 168h Forecast Accuracy vs. Linear Extrapolation Baseline

Module B forecasts 168h burn-in end values using **only 0h and 24h readings**. Below is the comparative Mean Absolute Error (MAE) versus a standard linear extrapolation baseline:

| Telemetry Parameter | LightGBM 168h MAE | Linear Baseline MAE | Error Reduction (%) |
| :--- | :---: | :---: | :---: |
| **Subthreshold Leakage ($I_{\text{leak}}$)** | **0.8212 $\mu\text{A}$** | 5.9695 $\mu\text{A}$ | **+86.2% Accuracy Gain** |
| **Quiescent Current ($I_{\text{DDQ}}$)** | **0.0400 $\text{mA}$** | 0.6081 $\text{mA}$ | **+93.4% Accuracy Gain** |
| **Propagation Delay ($t_{\text{pd}}$)** | **0.0920 $\text{ns}$** | 1.6873 $\text{ns}$ | **+94.6% Accuracy Gain** |

### Mathematical Validation:
Semiconductor burn-in kinetics exhibit nonlinear exponential and power-law acceleration ($I(t) \propto I_0 e^{\beta t}$). Naive linear projection ($v_0 + 7 \cdot (v_{24} - v_0)$) drastically underestimates thermal runaway, whereas LightGBM tree ensembles capture gradient curvature from early delta and ratio features.

---

## 4. Deterministic Explainability & Compliance

Unlike generative AI LLMs which are non-deterministic and can hallucinate numerical metrics, our Local Explainability Engine:
1. Calculates explicit $Z_{\text{MAD}}$ excursions with divide-by-zero protection.
2. Identifies the primary driving physical parameter.
3. Classifies components into deterministic risk categories (`CRITICAL_RUNAWAY`, `LATENT_LOT_OUTLIER`, `SUBTLE_DEGRADATION`, `NOMINAL`).
4. Generates an immutable QA audit trail with badge ID logging and engineering justifications.

---
*Report generated automatically by `scripts/generate_sih_report.py`.*
