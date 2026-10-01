import React from 'react';
import { AlertTriangle, Inbox, Loader2 } from 'lucide-react';
import { PartStatus, Verdict } from '../../data/types';

/** Shared formatting: never invents a value; missing numbers render as "n/a". */
export const fmt = (x: number | null | undefined, d = 2): string => (x == null || !Number.isFinite(x) ? 'n/a' : x.toFixed(d));
export const pct = (x: number | null | undefined, d = 1): string => (x == null || !Number.isFinite(x) ? 'n/a' : `${(100 * x).toFixed(d)}%`);
export const int = (x: number | null | undefined): string => (x == null || !Number.isFinite(x) ? 'n/a' : Math.round(x).toLocaleString());

export type Tone = 'neutral' | 'pass' | 'review' | 'reject' | 'info';
const TONE_BORDER: Record<Tone, string> = {
  neutral: 'border-l-hairline', pass: 'border-l-accept', review: 'border-l-review', reject: 'border-l-reject', info: 'border-l-info',
};
const TONE_TEXT: Record<Tone, string> = { neutral: 'text-main', pass: 'text-accept', review: 'text-review', reject: 'text-reject', info: 'text-info' };

export const Card: React.FC<{
  title?: React.ReactNode; subtitle?: React.ReactNode; actions?: React.ReactNode; className?: string; bodyClassName?: string;
  children: React.ReactNode; testId?: string;
}> = ({ title, subtitle, actions, className = '', bodyClassName = '', children, testId }) => (
  <section className={`bg-workspace border border-hairline rounded-card ${className}`} data-testid={testId}>
    {(title || actions) && (
      <header className="flex items-start justify-between gap-4 px-5 pt-4">
        <div>
          {title && <h2 className="text-card font-semibold text-main">{title}</h2>}
          {subtitle && <p className="text-sm text-muted mt-0.5">{subtitle}</p>}
        </div>
        {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
      </header>
    )}
    <div className={`px-5 pb-5 pt-3 ${bodyClassName}`}>{children}</div>
  </section>
);

/** One neutral tile style; status is shown by a coloured left border and/or value colour, never a fill. */
export const StatTile: React.FC<{
  label: string; value: React.ReactNode; sub?: React.ReactNode; tone?: Tone; colorValue?: boolean; badge?: React.ReactNode; testId?: string;
}> = ({ label, value, sub, tone = 'neutral', colorValue = false, badge, testId }) => (
  <div className={`bg-workspace border border-hairline border-l-4 ${TONE_BORDER[tone]} rounded-card px-4 py-3 min-w-0`} data-testid={testId}>
    <div className="flex items-start justify-between gap-2">
      <span className="text-sm text-muted font-medium">{label}</span>
      {badge}
    </div>
    <div className={`text-[26px] leading-8 font-semibold tabular-nums mt-1 ${colorValue ? TONE_TEXT[tone] : 'text-main'}`}>{value}</div>
    {sub && <div className="text-xs text-muted mt-0.5">{sub}</div>}
  </div>
);

const VERDICT_TONE: Record<string, Tone> = { PASS: 'pass', Accept: 'pass', REVIEW: 'review', Review: 'review', REJECT: 'reject', Reject: 'reject' };
const PILL: Record<Tone, string> = {
  pass: 'bg-accept-bg text-accept', review: 'bg-review-bg text-review', reject: 'bg-reject-bg text-reject',
  info: 'bg-info-bg text-info', neutral: 'bg-panel text-muted',
};
export const StatusPill: React.FC<{ status: Verdict | PartStatus | string | null | undefined; label?: string; tone?: Tone; className?: string }> = ({ status, label, tone, className = '' }) => {
  const t = tone ?? VERDICT_TONE[status ?? ''] ?? 'neutral';
  const text = label ?? (status === 'Accept' ? 'PASS' : status ? String(status).toUpperCase() : 'n/a');
  return <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold tracking-wide ${PILL[t]} ${className}`}>{text}</span>;
};
export const toneOf = (status: string | null | undefined): Tone => VERDICT_TONE[status ?? ''] ?? 'neutral';

export const EmptyState: React.FC<{ title: string; reason?: React.ReactNode; icon?: React.ReactNode; className?: string }> = ({ title, reason, icon, className = '' }) => (
  <div className={`flex flex-col items-center justify-center text-center py-8 px-4 text-muted ${className}`} role="status">
    <div className="mb-2 text-dim">{icon ?? <Inbox size={22} />}</div>
    <div className="text-md font-medium text-main">{title}</div>
    {reason && <div className="text-sm mt-1 max-w-[520px]">{reason}</div>}
  </div>
);

export const LoadingState: React.FC<{ what?: string }> = ({ what = 'data' }) => (
  <div className="flex items-center justify-center gap-2 py-10 text-muted text-sm" role="status"><Loader2 size={16} className="animate-spin" /> Loading {what}…</div>
);

export const ErrorState: React.FC<{ message: string; onRetry?: () => void }> = ({ message, onRetry }) => (
  <div className="flex items-start gap-2 p-3 rounded-lg border border-reject/30 bg-reject-bg text-reject text-sm" role="alert">
    <AlertTriangle size={16} className="shrink-0 mt-0.5" />
    <span className="flex-1">{message}</span>
    {onRetry && <button className="underline" onClick={onRetry}>Retry</button>}
  </div>
);

export const Button: React.FC<React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'ghost' }> = ({ variant = 'secondary', className = '', ...rest }) => {
  const v = variant === 'primary' ? 'bg-accent hover:bg-accent-hover text-white border-transparent'
    : variant === 'ghost' ? 'bg-transparent border-transparent text-muted hover:text-main' : 'bg-workspace border-hairline text-main hover:bg-panel';
  return <button {...rest} className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-sm font-medium disabled:opacity-40 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan ${v} ${className}`} />;
};

export const Chip: React.FC<{ active?: boolean; tone?: Tone; onClick?: () => void; children: React.ReactNode; testId?: string }> = ({ active, tone = 'info', onClick, children, testId }) => (
  <button onClick={onClick} data-testid={testId} aria-pressed={!!active}
    className={`px-3 py-1 rounded-full text-sm font-semibold border focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan ${active ? `${PILL[tone]} border-current` : 'bg-panel text-muted border-transparent hover:text-main'}`}>
    {children}
  </button>
);

/** Horizontal bar with a label and value (Module A bars, feature importance, supplier rates). */
export const BarRow: React.FC<{ label: React.ReactNode; value: number; max?: number; text: React.ReactNode; tone?: Tone }> = ({ label, value, max = 1, text, tone = 'info' }) => {
  const color = { neutral: 'bg-[var(--chart-neutral)]', pass: 'bg-accept', review: 'bg-review', reject: 'bg-reject', info: 'bg-info' }[tone];
  const w = Math.max(0, Math.min(1, max > 0 ? value / max : 0));
  return (
    <div className="grid grid-cols-[minmax(120px,38%)_1fr_70px] items-center gap-3 py-1.5 text-sm">
      <span className="text-main truncate" title={typeof label === 'string' ? label : undefined}>{label}</span>
      <div className="h-2 bg-panel rounded-full overflow-hidden"><div className={`h-full rounded-full ${color}`} style={{ width: `${100 * w}%` }} /></div>
      <span className="text-right tabular-nums text-main">{text}</span>
    </div>
  );
};
