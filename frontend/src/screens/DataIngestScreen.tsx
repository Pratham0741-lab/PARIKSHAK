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
    <div className="w-full h-full flex flex-col bg-workspace overflow-hidden font-mono text-xs">
      <div className="border-b border-hairline px-4 py-2 bg-panel flex items-center justify-between">
        <span className="font-bold text-sm text-main">Data ingest: new lot from CSV</span>
        <button onClick={loadExample} disabled={mode === 'offline'} className="bg-workspace border border-hairline px-2.5 py-1 text-muted hover:text-main flex items-center gap-1 disabled:opacity-40">
          <FileText size={12} /> Load example CSV (seeded generator)
        </button>
      </div>
      {mode === 'offline' && <div className="px-4 py-2 text-review">Ingest needs the backend (validation, storage and screening happen there). Switch data source to Backend.</div>}

      <div className="border-b border-hairline p-4 flex gap-6 shrink-0">
        <div onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); if (e.dataTransfer.files[0]) readFile(e.dataTransfer.files[0]); }}
          onClick={() => fileRef.current?.click()}
          className="flex-1 border-2 border-dashed border-hairline hover:border-toprail cursor-pointer flex flex-col items-center justify-center p-4 bg-panel/40 min-h-[170px]">
          <input type="file" ref={fileRef} accept=".csv,text/csv" className="hidden" onChange={e => e.target.files?.[0] && readFile(e.target.files[0])} />
          <UploadCloud size={28} className="text-muted mb-2" />
          <span className="font-semibold text-main">Drop CSV here or click to browse</span>
          <span className="text-[10px] text-muted mt-2 text-center break-all">Required: a part ID and leakage, IDDQ and delay at 0h and 24h. Optional: 96h, 168h, lot, temperature, unit.<br />
            Wide, long or tidy layout; headers matched case-insensitively and fuzzily (Iddq_0h, I_0, T0, "leakage (nA) 24h"); units nA/uA/mA, ps/ns converted.<br />{INGEST_HEADER.join(',')}</span>
          {fileName && <span className="mt-2 text-muted">File: <strong className="text-main">{fileName}</strong></span>}
        </div>

        <div className="w-[380px] border border-hairline p-3 bg-panel flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between pb-2 border-b border-hairline mb-2">
              <span className="font-bold font-sans">Backend validation</span>
              {v && <span className={v.ok ? 'text-accept' : 'text-reject'}>{v.issues.length} issues</span>}
            </div>
            {v ? (
              <div className="space-y-1 text-[11px]">
                {check(v.missingColumns.length === 0, v.missingColumns.length ? `Missing columns: ${v.missingColumns.join(', ')}` : 'All required columns present')}
                {check(true, `${v.rowsTotal} rows, ${v.partsAccepted} parts accepted`)}
                {check(v.rowsRejected === 0, `${v.rowsRejected} rows rejected (${v.duplicatePartIds} duplicate IDs)`)}
                {check(v.nonNumericCells === 0, `${v.nonNumericCells} non-numeric/negative cells (treated as missing)`)}
                {check(v.imputedCells === 0, `${v.imputedCells} cells imputed with lot median (flagged, display only)`)}
                {check(v.insufficientDataParts === 0, `${v.insufficientDataParts} parts with insufficient 0h/24h data → REVIEW, no model score`)}
                {v.layout && <div className="text-muted">Layout: {v.layout}{v.nLotsInFile > 1 ? `, ${v.nLotsInFile} lots in file` : ''}</div>}
                {unitList.length > 0 && (
                  <div className="pt-1" data-testid="detected-units">
                    <div className="font-bold font-sans">Detected units</div>
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
              className="w-full bg-workspace border border-hairline px-2 py-1 focus:outline-none" />
            <button onClick={commit} disabled={!v || !v.ok || busy || mode === 'offline' || (v.needsUnitConfirmation && !unitsConfirmed)}
              className="w-full bg-toprail text-white py-1 disabled:opacity-40">{busy ? 'Ingesting and screening…' : 'Ingest and screen lot'}</button>
            {error && v && <div className="text-reject">{error}</div>}
            {result?.lotId && result.screening && (
              <div className="text-accept">
                ✓ {result.lotNumber}: {result.screening.nScreened} parts screened ({Object.entries(result.screening.verdicts).map(([k, n]) => `${n} ${k}`).join(', ')}).{' '}
                <button className="underline" onClick={() => navigate('/lots')}>Open lot</button>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="flex-1 min-h-0 grid grid-cols-2 gap-4 p-4 overflow-hidden">
        <div className="border border-hairline overflow-auto">
          <div className="p-2 bg-panel border-b border-hairline font-semibold">Raw preview (first {rows.length} lines)</div>
          <table className="text-left border-collapse">
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className={i === 0 ? 'bg-panel font-bold text-muted' : ''}>
                  {r.map((c, j) => <td key={j} className="px-2 border-r border-b border-hairline/40 whitespace-nowrap">{c === '' ? <span className="text-reject italic">&lt;empty&gt;</span> : c}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="border border-hairline overflow-auto">
          <div className="p-2 bg-panel border-b border-hairline font-semibold">Issues ({v?.issues.length ?? 0}){v && v.issues.length > 0 && <span className="font-normal text-muted"> · click an issue to show its file line</span>}</div>
          {selectedRow != null && (
            <div className="m-2 p-2 border border-toprail bg-workspace" data-testid="issue-row">
              <div className="text-muted">Line 1 (header): {lineAt(1)}</div>
              <div className="text-main font-bold">Line {selectedRow}: {lineAt(selectedRow) || '(not found)'}</div>
            </div>
          )}
          {v && v.columnMap.length > 0 && (
            <details className="mx-2 mb-1">
              <summary className="cursor-pointer text-muted">Column mapping ({v.columnMap.filter(c => c.role !== 'ignored').length} used, {v.columnMap.filter(c => c.role === 'ignored').length} ignored)</summary>
              {v.columnMap.map(c => (
                <div key={c.header} className={c.role === 'ignored' ? 'text-review' : ''}>
                  "{c.header}" → {c.role === 'reading' ? `${c.param}${c.hour != null ? ` @ ${c.hour}h` : ''}${c.unit ? ` [${c.unit}]` : ''}` : c.role} {c.how && c.how !== 'exact' ? `(${c.how})` : ''}{c.note ? `: ${c.note}` : ''}
                </div>
              ))}
            </details>
          )}
          <div className="p-2 space-y-1">
            {v?.issues.map((iss, i) => (
              <div key={i} onClick={() => setSelectedRow(iss.row)} className={`p-1.5 border flex gap-2 cursor-pointer ${iss.severity === 'error' ? 'border-reject/40 bg-reject-bg text-reject' : 'border-review/40 bg-review-bg text-review'}`}>
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
