import React, { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useStore } from '../store/useStore';
import { previewCsv, INGEST_HEADER } from '../lib/csvPreview';
import { IngestResult, IngestSummary } from '../data/types';
import { UploadCloud, CheckCircle2, AlertTriangle, XCircle, FileText } from 'lucide-react';

/**
 * CSV ingest. Validation and imputation rules are the backend's (single implementation):
 * missing cells are imputed with the lot median and flagged (never 0), duplicates and bad rows are
 * rejected, and the stored lot is screened through Modules A and B.
 */
export const DataIngestScreen: React.FC = () => {
  const navigate = useNavigate();
  const { api, ingestCsv, mode } = useStore();
  const [csv, setCsv] = useState('');
  const [fileName, setFileName] = useState('');
  const [lotNumber, setLotNumber] = useState('');
  const [validation, setValidation] = useState<IngestSummary | null>(null);
  const [result, setResult] = useState<IngestResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [unitsConfirmed, setUnitsConfirmed] = useState(false);
  const [selectedRow, setSelectedRow] = useState<number | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = async (text: string, name: string) => {
    setCsv(text);
    setFileName(name);
    setResult(null);
    setError(null);
    setValidation(null);
    setUnitsConfirmed(false);
    setSelectedRow(null);
    try {
      setValidation(await api.validateCsv(text));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const readFile = (file: File) => {
    const reader = new FileReader();
    reader.onload = ev => load(String(ev.target?.result ?? ''), file.name);
    reader.readAsText(file);
  };

  const loadExample = async () => {
    const res = await fetch('/example_ingest.csv');
    await load(await res.text(), 'example_ingest.csv');
  };

  const commit = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await ingestCsv(csv, lotNumber || undefined, { filename: fileName || undefined, unitsConfirmed });
      setResult(r);
      setValidation(r.validation);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const rows = csv ? previewCsv(csv) : [];
  const lineAt = (n: number) => {
    // file line n (1-based), found without splitting the whole (possibly 10k+ line) file
    let start = 0;
    for (let k = 1; k < n; k++) {
      const nl = csv.indexOf('\n', start);
      if (nl < 0) return '';
      start = nl + 1;
    }
    const end = csv.indexOf('\n', start);
    return csv.slice(start, end < 0 ? undefined : end).replace(/\r$/, '');
  };
  const unitList = validation ? Object.entries(validation.units) : [];
  const v = validation;
  const check = (ok: boolean, text: string) => (
    <div className={`flex items-center gap-2 ${ok ? 'text-accept' : 'text-reject'}`}>{ok ? <CheckCircle2 size={13} /> : <XCircle size={13} />}<span>{text}</span></div>
  );

  return (
    <div className="space-y-5 max-w-[1500px] text-sm" data-testid="ingest">
      <div className="flex items-center justify-between">
        <p className="text-muted">New lot from CSV: validated and imputed by the backend (never zero-filled), then screened through Modules A and B.</p>
        <button onClick={loadExample} disabled={mode === 'offline'} className="rounded-lg bg-workspace border border-hairline px-3 py-1.5 text-main hover:bg-panel flex items-center gap-1.5 disabled:opacity-40">
          <FileText size={14} /> Load example CSV (seeded generator)
        </button>
      </div>
      {mode === 'offline' && <div className="rounded-lg px-4 py-2 bg-review-bg text-review">Ingest needs the backend (validation, storage and screening happen there). Switch data source to Backend.</div>}

      <div className="flex gap-5">
        <div onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); if (e.dataTransfer.files[0]) readFile(e.dataTransfer.files[0]); }}
          onClick={() => fileRef.current?.click()}
          role="button" tabIndex={0} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') fileRef.current?.click(); }} aria-label="Upload CSV"
          className="flex-1 rounded-card border-2 border-dashed border-hairline hover:border-navy cursor-pointer flex flex-col items-center justify-center p-6 bg-workspace min-h-[200px] focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan">
          <input type="file" ref={fileRef} accept=".csv,text/csv" className="hidden" onChange={e => e.target.files?.[0] && readFile(e.target.files[0])} />
          <UploadCloud size={30} className="text-navy mb-2" />
          <span className="font-semibold text-md text-main">Drop CSV here or click to browse</span>
          <span className="text-xs text-muted mt-2 text-center break-all max-w-[720px]">Required: a part ID and leakage, IDDQ and delay at 0h and 24h. Optional: 96h, 168h, lot, temperature, unit.<br />
            Wide, long or tidy layout; headers matched case-insensitively and fuzzily (Iddq_0h, I_0, T0, "leakage (nA) 24h"); units nA/uA/mA, ps/ns converted.<br />{INGEST_HEADER.join(',')}</span>
          {fileName && <span className="mt-2 text-muted">File: <strong className="text-main">{fileName}</strong></span>}
        </div>

        <div className="w-[400px] rounded-card border border-hairline p-4 bg-workspace flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between pb-2 border-b border-hairline mb-2">
              <span className="text-card font-semibold">Backend validation</span>
              {v && <span className={v.ok ? 'text-accept' : 'text-reject'}>{v.issues.length} issues</span>}
            </div>
            {v ? (
              <div className="space-y-1">
                {check(v.missingColumns.length === 0, v.missingColumns.length ? `Missing columns: ${v.missingColumns.join(', ')}` : 'All required columns present')}
                {check(true, `${v.rowsTotal} rows, ${v.partsAccepted} parts accepted`)}
                {check(v.rowsRejected === 0, `${v.rowsRejected} rows rejected (${v.duplicatePartIds} duplicate IDs)`)}
                {check(v.nonNumericCells === 0, `${v.nonNumericCells} non-numeric/negative cells (treated as missing)`)}
                {check(v.imputedCells === 0, `${v.imputedCells} cells imputed with lot median (flagged, display only)`)}
                {check(v.insufficientDataParts === 0, `${v.insufficientDataParts} parts with insufficient 0h/24h data → REVIEW, no model score`)}
                {v.layout && <div className="text-muted">Layout: {v.layout}{v.nLotsInFile > 1 ? `, ${v.nLotsInFile} lots in file` : ''}</div>}
                {unitList.length > 0 && (
                  <div className="pt-1" data-testid="detected-units">
                    <div className="font-semibold">Detected units</div>
                    {unitList.map(([p, u]) => (
                      <div key={p} className={u.implausible ? 'text-review' : ''}>
                        {p}: {Object.entries(u.detected).map(([unit, src]) => `${unit} (${src})`).join(', ')} → {u.canonical}
                        {u.median_0h_canonical != null && ` · 0h median ${u.median_0h_canonical} ${u.canonical}`}{u.implausible && ' · IMPLAUSIBLE, check unit'}
                      </div>
                    ))}
                    {v.needsUnitConfirmation && (
                      <label className="flex items-center gap-1 text-review mt-1">
                        <input type="checkbox" checked={unitsConfirmed} onChange={e => setUnitsConfirmed(e.target.checked)} data-testid="confirm-units" />
                        I confirm these units (required: a unit was converted or looks implausible)
                      </label>
                    )}
                  </div>
                )}
              </div>
            ) : <div className="text-muted italic py-4">{error ?? 'No file loaded.'}</div>}
          </div>
          <div className="pt-2 border-t border-hairline space-y-2">
            <input value={lotNumber} onChange={e => setLotNumber(e.target.value)} placeholder="Lot number (optional)"
              className="w-full rounded-lg bg-workspace border border-hairline px-3 py-1.5 focus:outline-none focus:border-navy" />
            <button onClick={commit} disabled={!v || !v.ok || busy || mode === 'offline' || (v.needsUnitConfirmation && !unitsConfirmed)}
              className="w-full rounded-lg bg-accent hover:bg-accent-hover text-white font-medium py-2 disabled:opacity-40">{busy ? 'Ingesting and screening…' : 'Ingest and screen lot'}</button>
            {error && v && <div className="text-reject">{error}</div>}
            {result?.lotId && result.screening && (
              <div className="text-accept">
                ✓ {result.lotNumber}: {result.screening.nScreened} parts screened ({Object.entries(result.screening.verdicts).map(([k, n]) => `${n} ${k}`).join(', ')}).{' '}
                <button className="underline" onClick={() => navigate('/')}>Open lot</button>
                {result.screening.warning && <div className="text-review mt-1" role="status">⚠ {result.screening.warning}</div>}
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-5">
        <div className="rounded-card border border-hairline bg-workspace overflow-auto max-h-[420px]">
          <div className="px-4 py-3 border-b border-hairline text-card font-semibold">Raw preview <span className="text-sm font-normal text-muted">(first {rows.length} lines)</span></div>
          <table className="text-left border-collapse font-mono text-xs">
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className={i === 0 ? 'bg-panel font-bold text-muted' : ''}>
                  {r.map((c, j) => <td key={j} className="px-2 border-r border-b border-hairline/40 whitespace-nowrap">{c === '' ? <span className="text-reject italic">&lt;empty&gt;</span> : c}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="rounded-card border border-hairline bg-workspace overflow-auto max-h-[420px]">
          <div className="px-4 py-3 border-b border-hairline text-card font-semibold">Parsed columns <span className="text-sm font-normal text-muted">(how each header was interpreted)</span></div>
          {v && v.columnMap.length > 0 ? (
            <table className="w-full text-left" data-testid="parsed-preview">
              <thead><tr className="text-muted border-b border-hairline"><th className="px-4 py-1.5 font-semibold">Header</th><th className="font-semibold">Interpreted as</th><th className="font-semibold">Match</th></tr></thead>
              <tbody>{v.columnMap.map(c => (
                <tr key={c.header} className={`border-b border-hairline-subtle ${c.role === 'ignored' ? 'text-review' : ''}`}>
                  <td className="px-4 py-1 font-mono">{c.header}</td>
                  <td>{c.role === 'reading' ? `${c.param}${c.hour != null ? ` @ ${c.hour}h` : ''}${c.unit ? ` [${c.unit}]` : ''}` : c.role}{c.note ? `: ${c.note}` : ''}</td>
                  <td className="text-muted">{c.how ?? ''}</td>
                </tr>))}</tbody>
            </table>
          ) : <div className="p-4 text-muted">Load a file to see the parsed columns.</div>}
        </div>
      </div>
      <div className="rounded-card border border-hairline bg-workspace overflow-auto max-h-[420px]">
        <div>
          <div className="px-4 py-3 border-b border-hairline text-card font-semibold">Issues ({v?.issues.length ?? 0}){v && v.issues.length > 0 && <span className="font-normal text-muted"> · click an issue to show its file line</span>}</div>
          {selectedRow != null && (
            <div className="m-3 p-3 rounded-lg border border-navy bg-panel font-mono text-xs" data-testid="issue-row">
              <div className="text-muted">Line 1 (header): {lineAt(1)}</div>
              <div className="text-main font-bold">Line {selectedRow}: {lineAt(selectedRow) || '(not found)'}</div>
            </div>
          )}
          <div className="p-3 space-y-1.5">
            {v?.issues.map((iss, i) => (
              <div key={i} role="button" tabIndex={0} onKeyDown={e => { if (e.key === 'Enter') setSelectedRow(iss.row); }} onClick={() => setSelectedRow(iss.row)} className={`px-3 py-1.5 rounded-lg border flex gap-2 cursor-pointer ${iss.severity === 'error' ? 'border-reject/40 bg-reject-bg text-reject' : 'border-review/40 bg-review-bg text-review'}`}>
                <AlertTriangle size={12} className="shrink-0 mt-0.5" />
                <span>Row {iss.row}{iss.partId ? ` (${iss.partId})` : ''}{iss.column ? ` [${iss.column}]` : ''}: {iss.message}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
