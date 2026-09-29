import React, { useMemo } from 'react';
import * as d3 from 'd3';

interface SparklineProps {
  readings: Record<number, number>; // 0, 24, 96, 168
  isFlagged?: boolean;
  width?: number;
  height?: number;
}

export const Sparkline: React.FC<SparklineProps> = ({
  readings,
  isFlagged = false,
  width = 44,
  height = 14,
}) => {
  const pathD = useMemo(() => {
    const intervals = [0, 24, 96, 168];
    const data = intervals.map(t => ({ t, v: readings[t] ?? 0 }));

    const minV = d3.min(data, d => d.v) ?? 0;
    const maxV = d3.max(data, d => d.v) ?? 1;
    const padding = 2;

    const xScale = d3.scaleLinear().domain([0, 168]).range([padding, width - padding]);
    const yScale = d3
      .scaleLinear()
      .domain([minV * 0.95, maxV * 1.05 || 1])
      .range([height - padding, padding]);

    const lineGen = d3
      .line<{ t: number; v: number }>()
      .x(d => xScale(d.t))
      .y(d => yScale(d.v));

    return lineGen(data) || '';
  }, [readings, width, height]);

  const strokeColor = isFlagged ? '#D63A2F' : '#8A949B';

  return (
    <svg width={width} height={height} className="overflow-visible block">
      <path
        d={pathD}
        fill="none"
        stroke={strokeColor}
        strokeWidth={1.25}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
};
