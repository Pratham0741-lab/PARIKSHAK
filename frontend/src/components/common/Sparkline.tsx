import React, { useMemo } from 'react';
import * as d3 from 'd3';

interface SparklineProps {
  readings: Record<number, number | null>; // 0, 24, 96, 168 (null = no reading)
  isFlagged?: boolean;
  width?: number;
  height?: number;
}

export const Sparkline: React.FC<SparklineProps> = ({ readings, isFlagged = false, width = 44, height = 14 }) => {
  const pathD = useMemo(() => {
    const data = [0, 24, 96, 168]
      .map(t => ({ t, v: readings[t] }))
      .filter((d): d is { t: number; v: number } => d.v != null);
    if (data.length < 2) return '';
    const minV = d3.min(data, d => d.v) ?? 0;
    const maxV = d3.max(data, d => d.v) ?? 1;
    const x = d3.scaleLinear().domain([0, 168]).range([2, width - 2]);
    const y = d3.scaleLinear().domain([minV * 0.95, maxV * 1.05 || 1]).range([height - 2, 2]);
    return d3.line<{ t: number; v: number }>().x(d => x(d.t)).y(d => y(d.v))(data) || '';
  }, [readings, width, height]);

  return (
    <svg width={width} height={height} className="overflow-visible block">
      <path d={pathD} fill="none" stroke={isFlagged ? '#D63A2F' : '#8A949B'} strokeWidth={1.25} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
};
