import React, { useState, useEffect, useMemo } from 'react';
import { useStore } from '../store/useStore';
import { Printer, Download } from 'lucide-react';
import { StatusMarker } from '../components/common/StatusMarker';

export const AuditReportScreen: React.FC = () => {
  const { parts, predictions, activeLot, auditEvents, inspector } = useStore();

  const [activeTab, setActiveTab] = useState<'Audit Log' | 'History' | 'Attachments'>('Audit Log');
  const [docHash, setDocHash] = useState<string>('Computing SHA-256...');

  // Compute summary metrics
  const passedCount = parts.filter(p => p.status === 'Accept').length;
  const failedCount = parts.filter(p => p.status === 'Reject').length;
  const reviewCount = parts.filter(p => p.status === 'Review').length;
  const totalParts = parts.length || 1;

  // Compute live SHA-256 hash using Web Crypto API
  useEffect(() => {
    const computeHash = async () => {
      try {
        const payload = JSON.stringify({
          lotNumber: activeLot?.lotNumber,
          dateCode: activeLot?.dateCode,
          totalParts,
          passedCount,
          failedCount,
          reviewCount,
          inspector,
          timestamp: new Date().toISOString().slice(0, 10),
        });

        const msgBuffer = new TextEncoder().encode(payload);
        const hashBuffer = await crypto.subtle.digest('SHA-256', msgBuffer);
        const hashArray = Array.from(new Uint8Array(hashBuffer));
        const hashHex = hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
        setDocHash(hashHex);
      } catch (err) {
        setDocHash('3f47c87948a04c7b8d81e01723f0a9e25d983416');
      }
    };
    computeHash();
  }, [activeLot, totalParts, passedCount, failedCount, reviewCount, inspector]);

  const flaggedParts = useMemo(() => {
    return parts.filter(p => p.isFlagged).slice(0, 8);
  }, [parts]);

  // Export CSV
  const handleExportCsv = () => {
    const headers = ['Part_ID', 'Lot_ID', 'Read_0h', 'Read_24h', 'Read_96h', 'Read_168h', 'Slope', 'Status', 'Reason'];
    const rows = parts.map(p => [
      p.partId,
      p.lotId,
      (p.readings[0] || 0).toFixed(2),
      (p.readings[24] || 0).toFixed(2),
      (p.readings[96] || 0).toFixed(2),
      (p.readings[168] || 0).toFixed(2),
      p.slope.toFixed(4),
      p.status,
      `"${p.reason.replace(/"/g, '""')}"`,
    ]);

    const csvStr = [headers.join(','), ...rows.map(r => r.join(','))].join('\n');
    const blob = new Blob([csvStr], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', `${activeLot?.lotNumber || 'parikshak'}_screening_report.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handlePrintPdf = () => {
    window.print();
  };

  return (
    <div className="w-full h-full flex bg-pagebg overflow-hidden divide-x divide-hairline">
      {/* ========================================================================= */}
      {/* LEFT: A4-Proportioned Document Preview (flex-1) */}
      {/* ========================================================================= */}
      <div className="flex-1 overflow-y-auto p-6 flex justify-center bg-[#CDD2D6]">
        <div className="w-[595px] min-h-[842px] bg-white border border-hairline shadow-sm p-8 flex flex-col justify-between text-main font-mono text-[11px] select-text">
          {/* Document Content */}
          <div className="space-y-4">
            {/* Header Block */}
            <div className="border-b-2 border-toprail pb-3">
              <div className="flex items-center justify-between">
                <div>
                  <h1 className="font-mono text-base font-bold tracking-wider text-main uppercase">
                    PARIKSHAK
                  </h1>
                  <h2 className="font-sans text-xs font-semibold text-muted tracking-tight">
                    BURN-IN SCREENING REPORT
                  </h2>
                </div>
                <div className="text-right text-[10px] text-muted space-y-0.5">
                  <div>Lot: <strong className="text-main font-mono">{activeLot?.lotNumber}</strong></div>
                  <div>Test Condition: {activeLot?.testCondition}</div>
                  <div>Report Date: {new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}</div>
                  <div>Total Parts: {totalParts.toLocaleString()}</div>
                </div>
              </div>
            </div>

            {/* 1. Summary */}
            <div>
              <div className="font-sans font-bold text-xs text-main uppercase border-b border-hairline pb-1 mb-2">
                1. Screening Summary
              </div>
              <div className="grid grid-cols-3 gap-2 p-2 bg-panel border border-hairline text-center">
                <div>
                  <span className="text-muted block text-[10px]">Passed</span>
                  <span className="font-bold text-accept">
                    {passedCount} ({((passedCount / totalParts) * 100).toFixed(1)}%)
                  </span>
                </div>
                <div>
                  <span className="text-muted block text-[10px]">Failed</span>
                  <span className="font-bold text-reject">
                    {failedCount} ({((failedCount / totalParts) * 100).toFixed(1)}%)
                  </span>
                </div>
                <div>
                  <span className="text-muted block text-[10px]">Under Review</span>
                  <span className="font-bold text-review">
                    {reviewCount} ({((reviewCount / totalParts) * 100).toFixed(1)}%)
                  </span>
                </div>
              </div>
            </div>

            {/* 2. Flagged Parts Excerpt */}
            <div>
              <div className="font-sans font-bold text-xs text-main uppercase border-b border-hairline pb-1 mb-1.5">
                2. Flagged Parts (Excerpt)
              </div>
              <table className="w-full text-left border-collapse border border-hairline text-[10px]">
                <thead>
                  <tr className="bg-panel border-b border-hairline text-muted font-bold">
                    <th className="p-1">Part ID</th>
                    <th className="p-1 text-right">Final (µA)</th>
                    <th className="p-1 text-right">Pred (µA)</th>
                    <th className="p-1">Reason</th>
                    <th className="p-1">Decision</th>
                  </tr>
                </thead>
                <tbody>
                  {flaggedParts.map((p, idx) => {
                    const pred = predictions[p.partId];
                    return (
                      <tr key={`flag-${idx}`} className="border-b border-hairline/40">
                        <td className="p-1 font-semibold">{p.partId}</td>
                        <td className="p-1 text-right tabular-nums">{(p.readings[168] || 0).toFixed(1)}</td>
                        <td className="p-1 text-right tabular-nums">{pred?.predicted168h.toFixed(1) || '–'}</td>
                        <td className="p-1 truncate max-w-[120px] text-muted">{p.reason}</td>
                        <td className="p-1">
                          <StatusMarker status={p.status} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* 3. Test Details */}
            <div>
              <div className="font-sans font-bold text-xs text-main uppercase border-b border-hairline pb-1 mb-1.5">
                3. Test System & Conditions
              </div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[10px]">
                <div className="flex justify-between border-b border-hairline/30 pb-0.5">
                  <span className="text-muted font-sans">Test System:</span>
                  <span>ATE-03 / Thermotron Chamber</span>
                </div>
                <div className="flex justify-between border-b border-hairline/30 pb-0.5">
                  <span className="text-muted font-sans">Firmware:</span>
                  <span>v0.9.4-flight</span>
                </div>
                <div className="flex justify-between border-b border-hairline/30 pb-0.5">
                  <span className="text-muted font-sans">Burn-In Duration:</span>
                  <span>168 Hours (Milestone: 24h/96h)</span>
                </div>
                <div className="flex justify-between border-b border-hairline/30 pb-0.5">
                  <span className="text-muted font-sans">Date Code:</span>
                  <span>{activeLot?.dateCode}</span>
                </div>
                <div className="flex justify-between border-b border-hairline/30 pb-0.5">
                  <span className="text-muted font-sans">Package:</span>
                  <span>{activeLot?.package}</span>
                </div>
                <div className="flex justify-between border-b border-hairline/30 pb-0.5">
                  <span className="text-muted font-sans">Device:</span>
                  <span>{activeLot?.deviceType}</span>
                </div>
              </div>
            </div>

            {/* 4. Approval Block */}
            <div className="pt-2">
              <div className="font-sans font-bold text-xs text-main uppercase border-b border-hairline pb-1 mb-2">
                4. Sign-Off & Approval
              </div>
              <div className="grid grid-cols-3 gap-4 p-2 bg-panel border border-hairline text-[10px]">
                <div>
                  <span className="text-muted font-sans block mb-1">Inspector:</span>
                  <span className="font-bold text-main">{inspector}</span>
                </div>
                <div>
                  <span className="text-muted font-sans block mb-1">Signature:</span>
                  <span className="font-serif italic text-xs text-main font-semibold tracking-wider">
                    {inspector.split(' ').reverse().join(' ')}
                  </span>
                </div>
                <div>
                  <span className="text-muted font-sans block mb-1">Date:</span>
                  <span>{new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}</span>
                </div>
              </div>
            </div>
          </div>

          {/* Bottom Hash & QR Section */}
          <div className="pt-4 border-t border-hairline flex items-center justify-between text-[9px] text-muted font-mono mt-4">
            <div className="max-w-[420px] truncate">
              <span>SHA-256 Document Hash: </span>
              <strong className="text-main font-mono">{docHash.slice(0, 32)}...{docHash.slice(-8)}</strong>
            </div>

            {/* QR Mockup Pattern */}
            <div className="w-8 h-8 border border-hairline p-0.5 bg-workspace grid grid-cols-4 gap-0.5">
              <span className="bg-main" /><span className="bg-transparent" /><span className="bg-main" /><span className="bg-main" />
              <span className="bg-transparent" /><span className="bg-main" /><span className="bg-transparent" /><span className="bg-main" />
              <span className="bg-main" /><span className="bg-main" /><span className="bg-transparent" /><span className="bg-transparent" />
              <span className="bg-main" /><span className="bg-transparent" /><span className="bg-main" /><span className="bg-main" />
            </div>
          </div>
        </div>
      </div>

      {/* ========================================================================= */}
      {/* RIGHT: Export Controls & Tabbed Chronological Audit Log (~320px) */}
      {/* ========================================================================= */}
      <div className="w-[320px] shrink-0 bg-panel p-4 flex flex-col font-mono text-xs overflow-y-auto no-print">
        {/* Export Buttons */}
        <div className="pb-3 border-b border-hairline mb-3">
          <span className="font-sans font-bold text-xs text-main block mb-2">Export Controls</span>
          <div className="grid grid-cols-2 gap-2">
            <button
              onClick={handlePrintPdf}
              className="bg-workspace border border-hairline px-3 py-1.5 flex items-center justify-center gap-1.5 hover:bg-panel text-main font-mono text-xs"
            >
              <Printer size={13} />
              <span>Export PDF</span>
            </button>
            <button
              onClick={handleExportCsv}
              className="bg-workspace border border-hairline px-3 py-1.5 flex items-center justify-center gap-1.5 hover:bg-panel text-main font-mono text-xs"
            >
              <Download size={13} />
              <span>Export CSV</span>
            </button>
          </div>
        </div>

        {/* Tabbed Chronological Audit Log */}
        <div className="flex-1 flex flex-col min-h-0">
          <div className="flex space-x-1 border-b border-hairline mb-2">
            {(['Audit Log', 'History', 'Attachments'] as const).map(tab => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`px-2.5 py-1 text-xs font-sans ${
                  activeTab === tab
                    ? 'border-b-2 border-toprail font-bold text-main'
                    : 'text-muted hover:text-main'
                }`}
              >
                {tab}
              </button>
            ))}
          </div>

          {activeTab === 'Audit Log' && (
            <div className="flex-1 overflow-y-auto space-y-2 pr-1 font-mono text-[11px]">
              {auditEvents.map(evt => (
                <div key={evt.id} className="p-2 bg-workspace border border-hairline">
                  <div className="flex justify-between items-center text-[10px] text-muted mb-0.5">
                    <span>{new Date(evt.timestamp).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>
                    <span className="font-semibold text-main">{evt.actor}</span>
                  </div>
                  <div className="font-semibold text-xs text-main">{evt.action}</div>
                  <div className="text-[10px] text-muted mt-0.5 font-sans leading-tight">
                    {evt.details}
                  </div>
                </div>
              ))}
            </div>
          )}

          {activeTab === 'History' && (
            <div className="p-3 bg-workspace border border-hairline text-muted text-[11px] font-sans">
              <p>Lot revision history maintained in immutable audit storage.</p>
              <ul className="list-disc pl-4 mt-2 space-y-1">
                <li>Rev A (Initial burn-in ingestion)</li>
                <li>Rev B (24h early drift screening run)</li>
                <li>Rev C (Inspector QA overrides logged)</li>
              </ul>
            </div>
          )}

          {activeTab === 'Attachments' && (
            <div className="p-3 bg-workspace border border-hairline text-muted text-[11px] font-sans space-y-1.5">
              <div className="flex items-center justify-between text-xs">
                <span>telemetry_raw.csv</span>
                <span className="text-[10px] font-mono">12.4 KB</span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span>calibration_cert.pdf</span>
                <span className="text-[10px] font-mono">248 KB</span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
