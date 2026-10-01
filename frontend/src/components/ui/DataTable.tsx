import React, { useMemo, useRef, useState } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { ArrowDown, ArrowUp } from 'lucide-react';

export interface Column<T> {
  key: string;
  header: React.ReactNode;
  width: string; // CSS grid track, e.g. '120px' or '1fr'
  align?: 'left' | 'right' | 'center';
  render: (row: T) => React.ReactNode;
  sortValue?: (row: T) => number | string | null;
}

/** Virtualised, sortable, keyboard-navigable table (smooth with thousands of rows). */
export function DataTable<T>({
  columns, rows, rowKey, onOpen, selectedKey, height = 520, emptyText = 'No rows.', rowHeight = 44,
  initialSort, testId, selectable,
}: {
  columns: Column<T>[]; rows: T[]; rowKey: (r: T) => string; onOpen?: (r: T) => void; selectedKey?: string | null;
  height?: number | string; emptyText?: React.ReactNode; rowHeight?: number; initialSort?: { key: string; dir: 'asc' | 'desc' };
  testId?: string; selectable?: { selected: Set<string>; toggle: (k: string) => void; setAll: (keys: string[]) => void };
}) {
  const [sort, setSort] = useState(initialSort ?? null);
  const sorted = useMemo(() => {
    if (!sort) return rows;
    const col = columns.find(c => c.key === sort.key);
    if (!col?.sortValue) return rows;
    const sv = col.sortValue;
    const dir = sort.dir === 'asc' ? 1 : -1;
    return [...rows].sort((a, b) => {
      const x = sv(a), y = sv(b);
      if (x == null && y == null) return 0;
      if (x == null) return 1;
      if (y == null) return -1;
      return (x < y ? -1 : x > y ? 1 : 0) * dir;
    });
  }, [rows, sort, columns]);

  const parentRef = useRef<HTMLDivElement>(null);
  const v = useVirtualizer({ count: sorted.length, getScrollElement: () => parentRef.current, estimateSize: () => rowHeight, overscan: 12 });
  const template = (selectable ? '36px ' : '') + columns.map(c => c.width).join(' ');
  const align = (a?: string) => (a === 'right' ? 'justify-end text-right' : a === 'center' ? 'justify-center' : '');
  const allKeys = sorted.map(rowKey);
  const allOn = selectable && allKeys.length > 0 && allKeys.every(k => selectable.selected.has(k));

  return (
    <div className="flex flex-col min-h-0" data-testid={testId}>
      <div className="grid items-center border-b border-hairline px-3 h-10 text-sm font-semibold text-muted" style={{ gridTemplateColumns: template }} role="row">
        {selectable && (
          <input type="checkbox" aria-label="Select all rows" checked={!!allOn}
            onChange={() => selectable.setAll(allOn ? [] : allKeys)} />
        )}
        {columns.map(c => (
          <button key={c.key} disabled={!c.sortValue} role="columnheader"
            aria-sort={sort?.key === c.key ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}
            onClick={() => c.sortValue && setSort(s => (s?.key === c.key ? { key: c.key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key: c.key, dir: 'desc' }))}
            className={`flex items-center gap-1 ${align(c.align)} disabled:cursor-default hover:text-main focus:outline-none focus-visible:underline`}>
            {c.header}{sort?.key === c.key && (sort.dir === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />)}
          </button>
        ))}
      </div>
      {sorted.length === 0 ? <div className="py-8 text-center text-muted text-sm">{emptyText}</div> : (
        <div ref={parentRef} className="overflow-auto" style={{ height }} role="rowgroup">
          <div style={{ height: v.getTotalSize(), position: 'relative' }}>
            {v.getVirtualItems().map(vi => {
              const r = sorted[vi.index];
              const k = rowKey(r);
              return (
                <div key={k} role="row" tabIndex={0} aria-selected={selectedKey === k}
                  onKeyDown={e => { if (e.key === 'Enter') onOpen?.(r); }}
                  onDoubleClick={() => onOpen?.(r)}
                  className={`grid items-center px-3 border-b border-hairline-subtle text-md focus:outline-none focus-visible:bg-info-bg ${selectedKey === k ? 'bg-info-bg' : 'hover:bg-panel'}`}
                  style={{ gridTemplateColumns: template, position: 'absolute', top: 0, left: 0, right: 0, height: vi.size, transform: `translateY(${vi.start}px)` }}>
                  {selectable && (
                    <input type="checkbox" aria-label={`Select ${k}`} checked={selectable.selected.has(k)} onChange={() => selectable.toggle(k)} />
                  )}
                  {columns.map(c => <div key={c.key} className={`flex items-center min-w-0 ${align(c.align)}`}>{c.render(r)}</div>)}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
