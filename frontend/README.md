# PARIKSHAK Frontend
### Burn-in screening & anomaly review UI (React + Vite)

The UI is a client of the FastAPI backend. Statuses, Module A/B scores, learned thresholds, 168h
forecasts, conformal prediction intervals, per-part explanations (TreeSHAP + lot-relative z) and
held-out metrics all come from the backend (`src/data/api.ts`, `HttpApi`). The frontend contains no
ground-truth labels.

**Offline demo mode** (top bar → Source, or `VITE_API_MODE=offline`) generates a seeded synthetic lot
and screens it with simple, documented client rules on 0h/24h readings (`src/data/offlineDemo.ts`).
It is labelled in the UI, is not the ML model, and provides no intervals, contributions or metrics.

---

## 1. Quickstart

```bash
cd frontend
npm ci
cp .env.example .env          # VITE_API_URL (default http://localhost:8000/api/v1), VITE_API_MODE
npm run dev -- --port 8080    # or from the repo root: make dev (backend + frontend)
```

```bash
npm test          # Vitest: API mapping, decision payloads, offline-demo guarantees (no labels, 0h/24h only)
npx tsc --noEmit  # type check
npm run lint      # ESLint
npm run build     # production build to dist/
```

The production image (`Dockerfile`) builds `dist/` and serves it with nginx; set `VITE_API_URL`
as a build argument.

---

## 2. Design System & Tokens

Character: dense, exact, unfashionable in a confident way, like instrument or test-engineering software (Keysight/NI, Grafana, Bloomberg Terminal).

- **Surfaces**:
  * Workspace: `#FFFFFF`
  * Panels: `#F1F3F4`
  * Hairline borders: `#C9CED2`
  * Top rail: `#1C2328`
  * Page background: `#D9DCDE`
- **Semantic Status Colors**:
  * Reject: `#D63A2F`
  * Review: `#E0A100`
  * Accept: `#2E7D4F`
- **Zero Decorative Accent Colors**: Neutral grey for normal traces (`#B0B7BC`), saturated colour only for selected or flagged parts.
- **Corner Radius**: 2px across all components. Zero box shadows (`box-shadow: none`).
- **Typography**: IBM Plex Sans for UI, IBM Plex Mono for all data, IDs, tabular numerals, and axes.
- **Spacing**: 4px grid, 28px table rows with sticky headers.

---

## 3. Keyboard Shortcuts

Designed for test-bench keyboard efficiency:
- `J` / `K`: Navigate down / up parts in tables and lists
- `A`: Accept selected part(s)
- `R`: Escalate selected part(s) to QA Review
- `X`: Reject / quarantine selected part(s)
- `/`: Focus search input
- `?`: Open keyboard shortcuts dialog
- `Esc`: Close open modal / dialog

---

## 4. Data Layer Contract & Architecture

All display data is dynamically generated or computed—zero hardcoded part IDs or measurements exist in UI components.

### Interfaces (`src/data/types.ts`)
- `Lot`: Wafer batch metadata, static limits, and safety slope thresholds.
- `Part`: Serial number, 0h/24h/96h/168h parameter telemetry, slope, status.
- `Prediction`: 168h forecast, residual, confidence intervals, anomaly scores, SHAP contributions.
- `Decision`: Inspector override log with timestamp, previous/new status, and mandatory rationale.
- `AuditEvent`: Immutable audit trail of report generations, ingest checks, and model runs.

### Swapping In a Real Backend

All components consume data through the `ParikshakApiInterface` (`src/data/api.ts`):

```typescript
export interface ParikshakApiInterface {
  getLots(): Promise<Lot[]>;
  getLot(id: string): Promise<Lot | null>;
  getParts(lotId: string): Promise<Part[]>;
  getPredictions(lotId: string): Promise<Record<string, Prediction>>;
  submitDecision(decision: Decision): Promise<void>;
  submitBulkDecisions(decisions: Decision[]): Promise<void>;
  getAuditLog(lotId?: string): Promise<AuditEvent[]>;
  ingestCsv(csvContent: string, columnMapping?: Record<string, string>): Promise<IngestValidationResult>;
}
```

To connect to a live REST or GraphQL backend:
1. Implement `ParikshakApiInterface` in `src/data/httpApi.ts` using `fetch` or `axios` connecting to your FastAPI / Flask / Express backend.
2. In `src/data/api.ts`, replace `export const api = new MockParikshakApi();` with `export const api = new HttpParikshakApi('https://api.your-domain.isro.gov.in/v1');`.
3. The UI components, state stores, charts, and audit views will function identically without any code changes.

---

## 5. Screen Inventory

1. **Drift Predictor (Hero, `/drift`)**: Virtualized list, D3 multi-trace canvas/SVG plot with log/linear scales, dynamic callouts, 95% confidence intervals, safety slope reference, and inspector panel.
2. **Lot Overview (`/lots`)**: Table-first layout with 168h histogram, plain-text summary counts (no cards), sortable filterable virtualized table.
3. **Data Ingest (`/ingest`)**: Real CSV upload and validation using PapaParse, column mapping, split view of raw rows, parsed rows, and error list.
4. **Dynamic Outlier Detection (`/outliers`)**: Log-scale histogram with rug plot, MAD range, method comparison (Z-score, Isolation Forest, Mahalanobis), and live sensitivity slider.
5. **Component Detail & Explainability (`/components`)**: Mini trajectory, signed SHAP feature attribution bars, lab-note QA justification in mono, similar-parts nearest neighbors.
6. **Decision Queue (`/decisions`)**: Multi-select dense table of flagged components, bulk action bar, inspector override with validated reason.
7. **Model Performance (`/model`)**: Plain labeled numbers, confusion matrix with visually emphasized false negative escape cell, interactive recall vs. threshold curve, predicted-vs-actual scatter.
8. **Audit Report (`/reports`)**: A4-proportioned document preview, real SHA-256 document hash via Web Crypto API, printable PDF stylesheet, CSV export, tabbed chronological audit log.
