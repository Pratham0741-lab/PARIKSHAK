import React, { useState, useRef } from 'react';
import { parseAndValidateCsv } from '../lib/analytics/csvValidator';
import { generateDemoRawCsv } from '../data/generator';
import { useStore } from '../store/useStore';
import { IngestValidationResult } from '../data/types';
import { UploadCloud, CheckCircle2, AlertTriangle, XCircle, FileText } from 'lucide-react';

export const DataIngestScreen: React.FC = () => {
  const { ingestCsvLot, activeLot } = useStore();

  const [activeTab, setActiveTab] = useState<'Upload' | 'Column Mapping' | 'Validation' | 'Preview'>('Upload');
  const [csvContent, setCsvContent] = useState<string>('');
  const [fileName, setFileName] = useState<string>('');
  const [fileSize, setFileSize] = useState<string>('');
  const [validationResult, setValidationResult] = useState<IngestValidationResult | null>(null);
  const [columnMapping, setColumnMapping] = useState<Record<string, string>>({});
  const [selectedSubTab, setSelectedSubTab] = useState<'Raw CSV' | 'Parsed Data' | 'Issues'>('Raw CSV');
  const [isSuccess, setIsSuccess] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleProcessCsv = (content: string, name: string = 'burnin_telemetry.csv', sizeStr: string = '12.4 KB') => {
    setCsvContent(content);
    setFileName(name);
    setFileSize(sizeStr);

    const res = parseAndValidateCsv(content, activeLot?.id || 'lot-temp', columnMapping);
    setValidationResult(res);
    setIsSuccess(false);
  };

  const handleFileDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const file = e.dataTransfer.files[0];
      const reader = new FileReader();
      reader.onload = evt => {
        const text = evt.target?.result as string;
        handleProcessCsv(text, file.name, `${(file.size / 1024).toFixed(1)} KB`);
      };
      reader.readAsText(file);
    }
  };

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      const reader = new FileReader();
      reader.onload = evt => {
        const text = evt.target?.result as string;
        handleProcessCsv(text, file.name, `${(file.size / 1024).toFixed(1)} KB`);
      };
      reader.readAsText(file);
    }
  };

  const handleLoadDemoCsv = () => {
    const demo = generateDemoRawCsv(101);
    handleProcessCsv(demo, 'demo_lot_sample.csv', '8.6 KB');
  };

  const handleCommitIngest = async () => {
    if (!csvContent) return;
    const ok = await ingestCsvLot(csvContent);
    if (ok) {
      setIsSuccess(true);
    }
  };

  return (
    <div className="w-full h-full flex flex-col bg-workspace overflow-hidden">
      {/* 1. Header with Top Sub-Tabs */}
      <div className="border-b border-hairline px-4 py-2 bg-panel flex items-center justify-between text-xs font-mono">
        <div className="flex items-center gap-6">
          <span className="font-bold text-sm text-main">
            Data Ingest: {activeLot?.lotNumber}
          </span>
          <div className="flex space-x-1">
            {(['Upload', 'Column Mapping', 'Validation', 'Preview'] as const).map(tab => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`px-3 py-1 font-sans text-xs border ${
                  activeTab === tab
                    ? 'bg-toprail text-white border-toprail font-medium'
                    : 'bg-workspace text-muted border-hairline hover:text-main'
                }`}
              >
                {tab}
              </button>
            ))}
          </div>
        </div>

        <button
          onClick={handleLoadDemoCsv}
          className="bg-panel border border-hairline px-2.5 py-1 text-xs text-muted hover:text-main font-mono flex items-center gap-1"
        >
          <FileText size={12} /> Load Demo CSV
        </button>
      </div>

      {/* 2. Upload and Validation Summary Strip */}
      <div className="h-[210px] border-b border-hairline p-4 flex gap-6 bg-workspace shrink-0">
        {/* Drag and Drop Zone */}
        <div
          onDragOver={e => e.preventDefault()}
          onDrop={handleFileDrop}
          onClick={() => fileInputRef.current?.click()}
          className="flex-1 border-2 border-dashed border-hairline hover:border-toprail cursor-pointer flex flex-col items-center justify-center p-4 bg-panel/40 transition-colors"
        >
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileInputChange}
            accept=".csv,text/csv"
            className="hidden"
          />
          <UploadCloud size={28} className="text-muted mb-2" />
          <span className="font-mono text-xs font-semibold text-main mb-1">
            Drop CSV file here
          </span>
          <span className="font-sans text-[11px] text-muted">
            or click to browse local filesystem
          </span>
          {fileName && (
            <div className="mt-3 text-[11px] font-mono text-muted bg-workspace px-2 py-0.5 border border-hairline">
              File: <strong className="text-main">{fileName}</strong> ({fileSize},{' '}
              {validationResult?.totalRowsParsed || 0} rows)
            </div>
          )}
        </div>

        {/* Validation Results Checklist */}
        <div className="w-[360px] border border-hairline p-3 bg-panel flex flex-col justify-between font-mono text-xs">
          <div>
            <div className="flex items-center justify-between pb-2 border-b border-hairline mb-2">
              <span className="font-bold text-main font-sans">Validation Results</span>
              {validationResult ? (
                <span
                  className={`text-[11px] font-semibold ${
                    validationResult.issues.length > 0 ? 'text-reject' : 'text-accept'
                  }`}
                >
                  {validationResult.issues.length} issues found
                </span>
              ) : (
                <span className="text-[11px] text-muted">Awaiting file</span>
              )}
            </div>

            {validationResult ? (
              <div className="space-y-1.5 text-[11px]">
                <div className="flex items-center gap-2 text-accept">
                  <CheckCircle2 size={13} />
                  <span>{validationResult.totalRowsParsed.toLocaleString()} rows parsed</span>
                </div>
                {validationResult.missingReadingsCount > 0 ? (
                  <div className="flex items-center gap-2 text-reject">
                    <XCircle size={13} />
                    <span>{validationResult.missingReadingsCount} missing readings</span>
                  </div>
                ) : (
                  <div className="flex items-center gap-2 text-accept">
                    <CheckCircle2 size={13} />
                    <span>All interval readings present</span>
                  </div>
                )}
                {validationResult.duplicatePartIds > 0 ? (
                  <div className="flex items-center gap-2 text-reject">
                    <XCircle size={13} />
                    <span>{validationResult.duplicatePartIds} duplicate Part IDs</span>
                  </div>
                ) : (
                  <div className="flex items-center gap-2 text-accept">
                    <CheckCircle2 size={13} />
                    <span>Part IDs unique</span>
                  </div>
                )}
                <div className="flex items-center gap-2 text-accept">
                  <CheckCircle2 size={13} />
                  <span>
                    {validationResult.requiredColumnsFound
                      ? 'All required columns found'
                      : 'Missing required columns'}
                  </span>
                </div>
                {validationResult.invalidNumericCount > 0 && (
                  <div className="flex items-center gap-2 text-reject">
                    <XCircle size={13} />
                    <span>{validationResult.invalidNumericCount} non-numeric values</span>
                  </div>
                )}
              </div>
            ) : (
              <div className="text-muted text-[11px] italic py-4">
                No telemetry file loaded. Drop a CSV or load demo.
              </div>
            )}
          </div>

          {/* Ingest Action Button */}
          <div className="pt-2 border-t border-hairline flex items-center justify-between">
            {isSuccess && (
              <span className="text-accept text-[11px] font-semibold">✓ Ingested into store!</span>
            )}
            <button
              onClick={handleCommitIngest}
              disabled={!validationResult || !validationResult.requiredColumnsFound}
              className="bg-toprail text-white text-xs px-3 py-1 font-mono disabled:opacity-40 hover:bg-toprail/90 ml-auto"
            >
              Ingest Lot into Store
            </button>
          </div>
        </div>
      </div>

      {/* 3. Split View: Raw CSV / Parsed Data / Issues */}
      <div className="flex-1 min-h-0 flex flex-col bg-workspace overflow-hidden">
        {/* Sub-tabs */}
        <div className="h-[30px] border-b border-hairline px-4 flex items-center justify-between bg-panel shrink-0 font-mono text-xs">
          <div className="flex space-x-1">
            <button
              onClick={() => setSelectedSubTab('Raw CSV')}
              className={`px-3 py-1 border-b-2 font-medium ${
                selectedSubTab === 'Raw CSV'
                  ? 'border-toprail text-main bg-workspace'
                  : 'border-transparent text-muted hover:text-main'
              }`}
            >
              Raw CSV ({validationResult?.rawRows.length || 0} preview rows)
            </button>
            <button
              onClick={() => setSelectedSubTab('Parsed Data')}
              className={`px-3 py-1 border-b-2 font-medium ${
                selectedSubTab === 'Parsed Data'
                  ? 'border-toprail text-main bg-workspace'
                  : 'border-transparent text-muted hover:text-main'
              }`}
            >
              Parsed Data ({validationResult?.parsedParts.length || 0})
            </button>
            <button
              onClick={() => setSelectedSubTab('Issues')}
              className={`px-3 py-1 border-b-2 font-medium ${
                selectedSubTab === 'Issues'
                  ? 'border-toprail text-main bg-workspace'
                  : 'border-transparent text-muted hover:text-main'
              }`}
            >
              Issues ({validationResult?.issues.length || 0})
            </button>
          </div>
        </div>

        {/* Sub-Tab Contents */}
        <div className="flex-1 overflow-auto p-4 font-mono text-xs">
          {selectedSubTab === 'Raw CSV' && (
            <div className="border border-hairline overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <tbody>
                  {validationResult?.rawRows && validationResult.rawRows.length > 0 ? (
                    validationResult.rawRows.map((row, rIdx) => (
                      <tr
                        key={`raw-${rIdx}`}
                        className={`h-[28px] border-b border-hairline ${
                          rIdx === 0 ? 'bg-panel font-bold text-muted' : 'hover:bg-panel/40'
                        }`}
                      >
                        <td className="px-3 border-r border-hairline text-muted w-10 text-right">
                          {rIdx + 1}
                        </td>
                        {row.map((cell, cIdx) => (
                          <td key={`c-${cIdx}`} className="px-3 border-r border-hairline/40">
                            {cell || <span className="text-reject italic text-[10px]">&lt;empty&gt;</span>}
                          </td>
                        ))}
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td className="p-4 text-muted text-center italic">No CSV loaded yet</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}

          {selectedSubTab === 'Parsed Data' && (
            <div className="border border-hairline overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="h-[28px] bg-panel border-b border-hairline text-muted font-bold">
                    <th className="px-3">Row</th>
                    <th className="px-3">Part ID</th>
                    <th className="px-3 text-right">0h (µA)</th>
                    <th className="px-3 text-right">24h (µA)</th>
                    <th className="px-3 text-right">96h (µA)</th>
                    <th className="px-3 text-right">168h (µA)</th>
                    <th className="px-3 text-right">Slope</th>
                    <th className="px-3">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {validationResult?.parsedParts.map((p, idx) => (
                    <tr key={`parsed-${idx}`} className="h-[28px] border-b border-hairline/40 hover:bg-panel/40">
                      <td className="px-3 text-muted">{idx + 1}</td>
                      <td className="px-3 font-semibold">{p.partId}</td>
                      <td className="px-3 text-right tabular-nums text-muted">{p.readings?.[0]?.toFixed(2)}</td>
                      <td className="px-3 text-right tabular-nums text-muted">{p.readings?.[24]?.toFixed(2)}</td>
                      <td className="px-3 text-right tabular-nums text-muted">{p.readings?.[96]?.toFixed(2)}</td>
                      <td className="px-3 text-right tabular-nums font-semibold">{p.readings?.[168]?.toFixed(2)}</td>
                      <td className="px-3 text-right tabular-nums text-muted">{p.slope?.toFixed(3)}</td>
                      <td className="px-3">
                        <span className={p.status === 'Reject' ? 'text-reject font-bold' : p.status === 'Review' ? 'text-review' : 'text-accept'}>
                          {p.status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {selectedSubTab === 'Issues' && (
            <div className="space-y-1.5">
              {validationResult?.issues && validationResult.issues.length > 0 ? (
                validationResult.issues.map((iss, i) => (
                  <div
                    key={`iss-${i}`}
                    className={`p-2 border flex items-center justify-between ${
                      iss.severity === 'error'
                        ? 'border-reject/40 bg-reject-bg text-reject'
                        : 'border-review/40 bg-review-bg text-review'
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      {iss.severity === 'error' ? <AlertTriangle size={13} /> : <AlertTriangle size={13} />}
                      <span>
                        Row {iss.row}: {iss.message} {iss.partId ? `(Part: ${iss.partId})` : ''}
                      </span>
                    </div>
                    <span className="text-[10px] uppercase font-bold">{iss.severity}</span>
                  </div>
                ))
              ) : (
                <div className="p-4 text-accept text-center">✓ No validation issues detected!</div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
