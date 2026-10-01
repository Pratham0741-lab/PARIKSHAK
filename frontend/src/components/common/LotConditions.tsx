import React from 'react';
import { Lot } from '../../data/types';

const LABEL: Record<string, string> = { leakage_current_ua: 'leakage', iddq_ma: 'IDDQ', propagation_delay_ns: 'delay' };

/** Burn-in test conditions of a lot; defaulted (not supplied) values are tagged "assumed". */
export const LotConditions: React.FC<{ lot: Lot | null; className?: string }> = ({ lot, className = '' }) => {
  if (!lot) return null;
  const tag = (field: string) =>
    lot.conditionsAssumed.includes(field) ? (
      <span className="ml-1 px-1 border border-review text-review text-[9px] uppercase" title="Not supplied; documented default used">assumed</span>
    ) : null;
  return (
    <span className={`inline-flex flex-wrap gap-x-4 ${className}`}>
      <span>Temperature: <strong className="text-main font-mono">{lot.temperatureC == null ? 'unknown' : `${lot.temperatureC} °C`}</strong>{tag('temperature_c')}</span>
      <span>Parameter: <strong className="text-main font-mono">{lot.testParameter ? LABEL[lot.testParameter] ?? lot.testParameter : '–'}</strong>{tag('test_parameter')}</span>
      <span>Unit: <strong className="text-main font-mono">{lot.unit ?? '–'}</strong>{tag('unit')}</span>
      <span>Static limit: <strong className="text-main font-mono">{lot.staticLimit ?? '–'}</strong>{tag('static_limit')}</span>
    </span>
  );
};
