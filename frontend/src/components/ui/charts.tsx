import React, { useEffect, useMemo, useRef, useState } from 'react';
import * as d3 from 'd3';

/** Width of a container, for responsive SVG charts. */
export function useWidth<T extends HTMLElement>(initial = 600): [React.RefObject<T>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(initial);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => el.clientWidth > 0 && setW(el.clientWidth));
    ro.observe(el);
    setW(el.clientWidth || initial);
    return () => ro.disconnect();
  }, [initial]);
  return [ref, w];
}

const C = {
  grid: 'var(--chart-grid)', neutral: 'var(--chart-neutral-light)', neutralDark: 'var(--chart-neutral)', text: 'var(--text-muted)',
  main: 'var(--text-main)', reject: 'var(--status-reject)', review: 'var(--status-review)', info: 'var(--status-info)',
  pass: 'var(--status-accept)', limit: 'var(--chart-limit-static)',
};

const Legend: React.FC<{ items: { label: string; color: string; kind?: 'bar' | 'line' | 'dash' | 'band' | 'dot' }[] }> = ({ items }) => (
  <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted mt-2" aria-label="Legend">
    {items.map(i => (
      <span key={i.label} className="inline-flex items-center gap-1.5">
        <svg width="18" height="10" aria-hidden>
          {i.kind === 'line' ? <line x1="0" x2="18" y1="5" y2="5" stroke={i.color} strokeWidth="2" />
            : i.kind === 'dash' ? <line x1="0" x2="18" y1="5" y2="5" stroke={i.color} strokeWidth="2" strokeDasharray="4 3" />
              : i.kind === 'band' ? <rect width="18" height="10" fill={i.color} opacity="0.25" />
                : i.kind === 'dot' ? <circle cx="9" cy="5" r="3.5" fill={i.color} />
                  : <rect width="18" height="10" rx="2" fill={i.color} />}
        </svg>
        {i.label}
      </span>
    ))}
  </div>
);

// ------------------------------------------------------------------ Histogram
export interface HistValue { v: number; status: 'PASS' | 'REVIEW' | 'REJECT' | null }

/** Neutral bars; a bin is coloured only if it contains flagged parts (REJECT red, else REVIEW amber).
 * Median line, median ± MAD band and the static limit are drawn. */
export const Histogram: React.FC<{ values: HistValue[]; xLabel: string; unit: string; limit: number | null; height?: number; bins?: number; testId?: string }> = ({
  values, xLabel, unit, limit, height = 260, bins = 24, testId,
}) => {
  const [ref, width] = useWidth<HTMLDivElement>();
  const m = { top: 14, right: 16, bottom: 44, left: 48 };
  const data = useMemo(() => {
    const vs = values.map(d => d.v).filter(Number.isFinite);
    if (vs.length === 0) return null;
    const med = d3.median(vs) as number;
    const mad = d3.median(vs.map(v => Math.abs(v - med))) as number;
    const dmax = d3.max(vs) as number;
    const dmin = d3.min(vs) as number;
    // Keep the axis on the data; a static limit far beyond it is marked "off scale" instead of squashing the bins.
    const limitOnScale = limit != null && limit <= dmax + 0.5 * (dmax - dmin + 1e-9) * 2;
    const hi = limitOnScale ? Math.max(dmax, limit as number) : dmax;
    const lo = dmin;
    const pad = (hi - lo) * 0.04 || Math.abs(hi) * 0.05 || 1;
    const x = d3.scaleLinear().domain([lo - pad, hi + pad]).nice().range([m.left, width - m.right]);
    const bin = d3.bin<HistValue, number>().value(d => d.v).domain(x.domain() as [number, number]).thresholds(x.ticks(bins));
    const bs = bin(values.filter(d => Number.isFinite(d.v)));
    const y = d3.scaleLinear().domain([0, d3.max(bs, b => b.length) ?? 1]).nice().range([height - m.bottom, m.top]);
    return { med, mad, x, y, bs, limitOnScale };
  }, [values, limit, width, height, bins]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!data) return <div ref={ref} className="text-sm text-muted py-6 text-center">No readings at this time point.</div>;
  const { med, mad, x, y, bs, limitOnScale } = data;
  const color = (b: d3.Bin<HistValue, number>) => (b.some(d => d.status === 'REJECT') ? C.reject : b.some(d => d.status === 'REVIEW') ? C.review : C.neutral);
  return (
    <div ref={ref} data-testid={testId}>
      <svg width={width} height={height} role="img" aria-label={`Histogram of ${xLabel}`}>
        {y.ticks(5).map(t => (
          <g key={t}><line x1={m.left} x2={width - m.right} y1={y(t)} y2={y(t)} stroke={C.grid} />
            <text x={m.left - 6} y={y(t) + 4} textAnchor="end" fontSize="11" fill={C.text}>{t}</text></g>
        ))}
        <rect x={x(med - mad)} width={Math.max(1, x(med + mad) - x(med - mad))} y={m.top} height={height - m.bottom - m.top} fill={C.info} opacity={0.08} />
        {bs.map((b, i) => (
          <rect key={i} x={x(b.x0 ?? 0) + 1} width={Math.max(1, x(b.x1 ?? 0) - x(b.x0 ?? 0) - 2)} y={y(b.length)}
            height={Math.max(0, height - m.bottom - y(b.length))} rx={2} fill={color(b)}>
            <title>{`${(b.x0 ?? 0).toFixed(2)}–${(b.x1 ?? 0).toFixed(2)} ${unit}: ${b.length} parts`}</title>
          </rect>
        ))}
        <line x1={x(med)} x2={x(med)} y1={m.top} y2={height - m.bottom} stroke={C.info} strokeWidth={2} />
        {limit != null && limitOnScale && <line x1={x(limit)} x2={x(limit)} y1={m.top} y2={height - m.bottom} stroke={C.limit} strokeWidth={1.5} strokeDasharray="5 3" />}
        {limit != null && !limitOnScale && <text x={width - m.right} y={m.top + 10} textAnchor="end" fontSize="11" fill={C.limit}>static limit {limit} {unit} (off scale →)</text>}
        {x.ticks(8).map(t => <text key={t} x={x(t)} y={height - m.bottom + 16} textAnchor="middle" fontSize="11" fill={C.text}>{t}</text>)}
        <text x={(m.left + width - m.right) / 2} y={height - 6} textAnchor="middle" fontSize="12" fill={C.text}>{xLabel} ({unit})</text>
        <text transform="rotate(-90)" x={-(height - m.bottom + m.top) / 2} y={13} textAnchor="middle" fontSize="12" fill={C.text}>parts</text>
      </svg>
      <Legend items={[
        { label: 'parts per bin', color: C.neutral }, { label: 'bin has REVIEW parts', color: C.review }, { label: 'bin has REJECT parts', color: C.reject },
        { label: `median ${med.toFixed(2)} ${unit}`, color: C.info, kind: 'line' }, { label: `± MAD ${mad.toFixed(2)} ${unit}`, color: C.info, kind: 'band' },
        ...(limit != null ? [{ label: `static limit ${limit} ${unit}`, color: C.limit, kind: 'dash' as const }] : []),
      ]} />
    </div>
  );
};

// ------------------------------------------------------------------ Line chart (continuous lines + markers)
export interface Series { id: string; label: string; color: string; points: { x: number; y: number | null }[]; dashed?: boolean; width?: number }
export interface Band { id: string; label: string; color: string; points: { x: number; lo: number; hi: number }[] }

export const LineChart: React.FC<{
  series: Series[]; bands?: Band[]; hLines?: { y: number; label: string; color: string }[]; xTicks: { x: number; label: string }[];
  xLabel: string; yLabel: string; height?: number; yMin?: number; testId?: string; extraLegend?: { label: string; color: string; kind?: 'bar' | 'line' | 'dash' | 'band' | 'dot' }[];
}> = ({ series, bands = [], hLines = [], xTicks, xLabel, yLabel, height = 280, yMin, testId, extraLegend = [] }) => {
  const [ref, width] = useWidth<HTMLDivElement>();
  const m = { top: 16, right: 20, bottom: 44, left: 56 };
  const ys = [...series.flatMap(s => s.points.map(p => p.y)), ...bands.flatMap(b => b.points.flatMap(p => [p.lo, p.hi])), ...hLines.map(h => h.y)]
    .filter((v): v is number => v != null && Number.isFinite(v));
  const xs = [...xTicks.map(t => t.x), ...series.flatMap(s => s.points.map(p => p.x))];
  if (ys.length === 0) return <div ref={ref} className="text-sm text-muted py-6 text-center">No data to plot.</div>;
  const lo = yMin ?? Math.min(0, d3.min(ys) as number);
  const x = d3.scaleLinear().domain([d3.min(xs) as number, d3.max(xs) as number]).range([m.left, width - m.right]);
  const y = d3.scaleLinear().domain([lo, (d3.max(ys) as number) * 1.08 || 1]).nice().range([height - m.bottom, m.top]);
  const line = d3.line<{ x: number; y: number | null }>().defined(p => p.y != null && Number.isFinite(p.y)).x(p => x(p.x)).y(p => y(p.y as number));
  const area = d3.area<{ x: number; lo: number; hi: number }>().x(p => x(p.x)).y0(p => y(p.lo)).y1(p => y(p.hi));
  return (
    <div ref={ref} data-testid={testId}>
      <svg width={width} height={height} role="img" aria-label={`${yLabel} vs ${xLabel}`}>
        {y.ticks(5).map(t => (
          <g key={t}><line x1={m.left} x2={width - m.right} y1={y(t)} y2={y(t)} stroke={C.grid} />
            <text x={m.left - 6} y={y(t) + 4} textAnchor="end" fontSize="11" fill={C.text}>{t}</text></g>
        ))}
        {xTicks.map(t => <text key={t.x} x={x(t.x)} y={height - m.bottom + 18} textAnchor="middle" fontSize="12" fill={C.text}>{t.label}</text>)}
        {bands.map(b => <path key={b.id} d={area(b.points) ?? ''} fill={b.color} opacity={0.15} />)}
        {hLines.map(h => <line key={h.label} x1={m.left} x2={width - m.right} y1={y(h.y)} y2={y(h.y)} stroke={h.color} strokeWidth={1.5} strokeDasharray="5 3" />)}
        {series.map(s => (
          <g key={s.id}>
            <path d={line(s.points) ?? ''} fill="none" stroke={s.color} strokeWidth={s.width ?? 2.25} strokeDasharray={s.dashed ? '6 4' : undefined} strokeLinejoin="round" />
            {s.points.filter(p => p.y != null && Number.isFinite(p.y)).map(p => (
              <circle key={p.x} cx={x(p.x)} cy={y(p.y as number)} r={s.dashed ? 3 : 4} fill={s.dashed ? 'white' : s.color} stroke={s.color} strokeWidth={1.75}>
                <title>{`${s.label}: ${(p.y as number).toFixed(3)}`}</title>
              </circle>
            ))}
          </g>
        ))}
        <text x={(m.left + width - m.right) / 2} y={height - 6} textAnchor="middle" fontSize="12" fill={C.text}>{xLabel}</text>
        <text transform="rotate(-90)" x={-(height - m.bottom + m.top) / 2} y={14} textAnchor="middle" fontSize="12" fill={C.text}>{yLabel}</text>
      </svg>
      <Legend items={[
        ...series.map(s => ({ label: s.label, color: s.color, kind: (s.dashed ? 'dash' : 'line') as 'dash' | 'line' })),
        ...bands.map(b => ({ label: b.label, color: b.color, kind: 'band' as const })),
        ...hLines.map(h => ({ label: h.label, color: h.color, kind: 'dash' as const })),
        ...extraLegend,
      ]} />
    </div>
  );
};

// ------------------------------------------------------------------ Scatter (predicted vs actual)
export const ScatterPlot: React.FC<{ points: { x: number; y: number; title?: string }[]; xLabel: string; yLabel: string; height?: number; testId?: string }> = ({
  points, xLabel, yLabel, height = 300, testId,
}) => {
  const [ref, width] = useWidth<HTMLDivElement>();
  const m = { top: 14, right: 16, bottom: 44, left: 56 };
  if (points.length === 0) return <div ref={ref} className="text-sm text-muted py-6 text-center">No points.</div>;
  const hi = (d3.max(points, p => Math.max(p.x, p.y)) as number) * 1.05;
  const lo = Math.min(0, d3.min(points, p => Math.min(p.x, p.y)) as number);
  const x = d3.scaleLinear().domain([lo, hi]).nice().range([m.left, width - m.right]);
  const y = d3.scaleLinear().domain(x.domain()).range([height - m.bottom, m.top]);
  const [d0, d1] = x.domain();
  return (
    <div ref={ref} data-testid={testId}>
      <svg width={width} height={height} role="img" aria-label={`${yLabel} vs ${xLabel}`}>
        {y.ticks(5).map(t => (
          <g key={t}><line x1={m.left} x2={width - m.right} y1={y(t)} y2={y(t)} stroke={C.grid} />
            <text x={m.left - 6} y={y(t) + 4} textAnchor="end" fontSize="11" fill={C.text}>{t}</text></g>
        ))}
        {x.ticks(6).map(t => <text key={t} x={x(t)} y={height - m.bottom + 16} textAnchor="middle" fontSize="11" fill={C.text}>{t}</text>)}
        <line x1={x(d0)} y1={y(d0)} x2={x(d1)} y2={y(d1)} stroke={C.limit} strokeDasharray="5 3" />
        {points.map((p, i) => <circle key={i} cx={x(p.x)} cy={y(p.y)} r={2.2} fill={C.info} opacity={0.45}>{p.title && <title>{p.title}</title>}</circle>)}
        <text x={(m.left + width - m.right) / 2} y={height - 6} textAnchor="middle" fontSize="12" fill={C.text}>{xLabel}</text>
        <text transform="rotate(-90)" x={-(height - m.bottom + m.top) / 2} y={14} textAnchor="middle" fontSize="12" fill={C.text}>{yLabel}</text>
      </svg>
      <Legend items={[{ label: 'part (held-out)', color: C.info, kind: 'dot' }, { label: 'identity (prediction = actual)', color: C.limit, kind: 'dash' }]} />
    </div>
  );
};

// ------------------------------------------------------------------ Vertical bars (anomaly rate by lot)
export const BarChart: React.FC<{
  bars: { key: string; label: string; value: number; highlight: boolean; title?: string }[]; yLabel: string; xLabel: string;
  threshold?: { value: number; label: string }; height?: number; format?: (v: number) => string; onClick?: (key: string) => void; testId?: string;
}> = ({ bars, yLabel, xLabel, threshold, height = 280, format = v => String(v), onClick, testId }) => {
  const [ref, width] = useWidth<HTMLDivElement>();
  const m = { top: 14, right: 16, bottom: 56, left: 52 };
  if (bars.length === 0) return <div ref={ref} className="text-sm text-muted py-6 text-center">No lots.</div>;
  const x = d3.scaleBand().domain(bars.map(b => b.key)).range([m.left, width - m.right]).padding(0.25);
  const y = d3.scaleLinear().domain([0, Math.max(d3.max(bars, b => b.value) ?? 0, threshold?.value ?? 0) * 1.1 || 1]).nice().range([height - m.bottom, m.top]);
  const every = Math.ceil(bars.length / Math.max(1, Math.floor((width - m.left) / 46)));
  return (
    <div ref={ref} data-testid={testId}>
      <svg width={width} height={height} role="img" aria-label={`${yLabel} by ${xLabel}`}>
        {y.ticks(5).map(t => (
          <g key={t}><line x1={m.left} x2={width - m.right} y1={y(t)} y2={y(t)} stroke={C.grid} />
            <text x={m.left - 6} y={y(t) + 4} textAnchor="end" fontSize="11" fill={C.text}>{format(t)}</text></g>
        ))}
        {bars.map((b, i) => (
          <g key={b.key} className={onClick ? 'cursor-pointer' : undefined} onClick={() => onClick?.(b.key)}>
            <rect x={x(b.key)} width={x.bandwidth()} y={y(b.value)} height={Math.max(0, height - m.bottom - y(b.value))} rx={3}
              fill={b.highlight ? C.reject : C.neutralDark}><title>{b.title ?? `${b.label}: ${format(b.value)}`}</title></rect>
            {i % every === 0 && (
              <text x={(x(b.key) ?? 0) + x.bandwidth() / 2} y={height - m.bottom + 14} textAnchor="end" fontSize="10" fill={C.text}
                transform={`rotate(-35 ${(x(b.key) ?? 0) + x.bandwidth() / 2} ${height - m.bottom + 14})`}>{b.label}</text>
            )}
          </g>
        ))}
        {threshold && <line x1={m.left} x2={width - m.right} y1={y(threshold.value)} y2={y(threshold.value)} stroke={C.reject} strokeDasharray="5 3" />}
        <text transform="rotate(-90)" x={-(height - m.bottom + m.top) / 2} y={13} textAnchor="middle" fontSize="12" fill={C.text}>{yLabel}</text>
        <text x={(m.left + width - m.right) / 2} y={height - 4} textAnchor="middle" fontSize="12" fill={C.text}>{xLabel}</text>
      </svg>
      <Legend items={[{ label: 'lot', color: C.neutralDark }, ...(threshold ? [{ label: `above ${threshold.label}`, color: C.reject }, { label: threshold.label, color: C.reject, kind: 'dash' as const }] : [])]} />
    </div>
  );
};

// ------------------------------------------------------------------ Heatmap (Low / Watch / High)
export type RiskLevel = 'Low' | 'Watch' | 'High' | 'n/a';
export const Heatmap: React.FC<{ rows: string[]; cols: string[]; cell: (r: string, c: string) => { level: RiskLevel; title: string }; testId?: string }> = ({ rows, cols, cell, testId }) => {
  const cls: Record<RiskLevel, string> = { Low: 'bg-accept-bg text-accept', Watch: 'bg-review-bg text-review', High: 'bg-reject-bg text-reject', 'n/a': 'bg-panel text-dim' };
  return (
    <table className="w-full text-sm" data-testid={testId}>
      <thead><tr><th />{cols.map(c => <th key={c} className="py-1 font-semibold text-muted">{c}</th>)}</tr></thead>
      <tbody>
        {rows.map(r => (
          <tr key={r}>
            <th scope="row" className="text-left font-medium text-main py-1 pr-3">{r}</th>
            {cols.map(c => { const v = cell(r, c); return (
              <td key={c} className="p-1"><div className={`rounded-md text-center py-1.5 font-semibold ${cls[v.level]}`} title={v.title}>{v.level}</div></td>
            ); })}
          </tr>
        ))}
      </tbody>
    </table>
  );
};
