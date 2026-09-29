import React, { useMemo, useRef, useState, useEffect } from 'react';
import * as d3 from 'd3';
import { Part, Prediction } from '../../data/types';

interface DriftTracePlotProps {
  parts: Part[];
  selectedPart: Part | null;
  prediction: Prediction | null;
  staticLimit: number;
  safetySlopeLimit: number;
  xAxisMode: 'linear' | 'log';
  yAxisMode: 'linear' | 'log';
  showPredicted: boolean;
  showConfidenceBand: boolean;
  showSafetySlope: boolean;
  onSelectPart: (partId: string) => void;
}

export const DriftTracePlot: React.FC<DriftTracePlotProps> = ({
  parts,
  selectedPart,
  prediction,
  staticLimit,
  safetySlopeLimit,
  yAxisMode,
  showPredicted,
  showConfidenceBand,
  showSafetySlope,
  onSelectPart,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 700, height: 420 });

  useEffect(() => {
    const handleResize = () => {
      if (containerRef.current) {
        const { clientWidth, clientHeight } = containerRef.current;
        if (clientWidth > 0 && clientHeight > 0) {
          setDimensions({ width: clientWidth, height: clientHeight });
        }
      }
    };
    handleResize();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const intervals = [0, 24, 96, 168];
  const margin = { top: 30, right: 35, bottom: 40, left: 55 };
  const innerWidth = Math.max(100, dimensions.width - margin.left - margin.right);
  const innerHeight = Math.max(100, dimensions.height - margin.top - margin.bottom);

  // Scales calculation
  const { xScale, yScale, yTicks } = useMemo(() => {
    // X scale
    const xs = d3.scaleLinear().domain([0, 168]).range([margin.left, margin.left + innerWidth]);

    // Calculate Y domain
    let minY = 0.5;
    let maxY = Math.max(staticLimit * 1.2, 60);

    for (const p of parts) {
      for (const t of intervals) {
        const v = p.readings[t] || 0;
        if (v > maxY) maxY = v * 1.1;
      }
    }

    if (prediction && prediction.predicted168h > maxY) {
      maxY = prediction.predicted168h * 1.1;
    }

    let ys: d3.ScaleContinuousNumeric<number, number>;
    let ticks: number[] = [];

    if (yAxisMode === 'log') {
      minY = 0.1;
      maxY = Math.max(maxY, 100);
      ys = d3.scaleLog().clamp(true).domain([minY, maxY]).range([margin.top + innerHeight, margin.top]);
      ticks = [0.1, 1, 10, 100, 1000].filter(t => t >= minY && t <= maxY * 1.2);
    } else {
      minY = 0;
      ys = d3.scaleLinear().domain([minY, maxY]).range([margin.top + innerHeight, margin.top]);
      ticks = ys.ticks(6);
    }

    return { xScale: xs, yScale: ys, yTicks: ticks };
  }, [parts, prediction, staticLimit, yAxisMode, innerWidth, innerHeight, margin.left, margin.top]);

  // Line generator
  const lineGenerator = d3
    .line<{ t: number; v: number }>()
    .x(d => xScale(d.t))
    .y(d => yScale(Math.max(0.1, d.v)));

  // Selected part trace data
  const selectedPoints = useMemo(() => {
    if (!selectedPart) return [];
    return intervals.map(t => ({ t, v: selectedPart.readings[t] || 0 }));
  }, [selectedPart]);

  // Forecast path
  const forecastPoints = useMemo(() => {
    if (!selectedPart || !prediction) return [];
    return [
      { t: 24, v: selectedPart.readings[24] || 0 },
      { t: 168, v: prediction.predicted168h },
    ];
  }, [selectedPart, prediction]);

  // Confidence band polygon points
  const confidencePolygonD = useMemo(() => {
    if (!selectedPart || !prediction || !showConfidenceBand) return '';
    const p24 = selectedPart.readings[24] || 0;
    const x24 = xScale(24);
    const y24 = yScale(p24);
    const x168 = xScale(168);
    const yLower = yScale(Math.max(0.1, prediction.ciLowerUa));
    const yUpper = yScale(Math.max(0.1, prediction.ciUpperUa));

    return `M ${x24} ${y24} L ${x168} ${yUpper} L ${x168} ${yLower} Z`;
  }, [selectedPart, prediction, showConfidenceBand, xScale, yScale]);

  // Safety slope reference line points
  const safetyLinePoints = useMemo(() => {
    if (!selectedPart || !showSafetySlope) return null;
    const v0 = selectedPart.readings[0] || 0;
    const v168Safety = v0 + safetySlopeLimit * 168;
    return {
      x1: xScale(0),
      y1: yScale(v0),
      x2: xScale(168),
      y2: yScale(v168Safety),
      v168Safety,
    };
  }, [selectedPart, showSafetySlope, safetySlopeLimit, xScale, yScale]);

  // Static limit y-coordinate
  const staticLimitY = yScale(staticLimit);

  // Callout positioning
  const calloutPos = useMemo(() => {
    if (!selectedPart || !prediction) return null;
    const x = xScale(96);
    const yTarget = yScale(prediction.predicted168h);
    const y = Math.max(margin.top + 10, yTarget - 65);
    return { x, y };
  }, [selectedPart, prediction, xScale, yScale, margin.top]);

  return (
    <div ref={containerRef} className="w-full h-full relative select-none bg-workspace flex flex-col">
      <svg width={dimensions.width} height={dimensions.height} className="w-full h-full block">
        <defs>
          {/* Diagonal hatch pattern for confidence interval */}
          <pattern
            id="confidenceHatch"
            width="6"
            height="6"
            patternTransform="rotate(45 0 0)"
            patternUnits="userSpaceOnUse"
          >
            <line x1="0" y1="0" x2="0" y2="6" stroke="#D63A2F" strokeWidth="1.5" strokeOpacity="0.3" />
          </pattern>
        </defs>

        {/* Gridlines */}
        {yTicks.map(t => (
          <g key={`grid-${t}`}>
            <line
              x1={margin.left}
              x2={margin.left + innerWidth}
              y1={yScale(t)}
              y2={yScale(t)}
              stroke="#E5E8EB"
              strokeWidth={1}
            />
            <text
              x={margin.left - 8}
              y={yScale(t) + 3}
              textAnchor="end"
              className="text-[11px] font-mono fill-muted"
            >
              {t}
            </text>
          </g>
        ))}

        {intervals.map(t => (
          <g key={`x-grid-${t}`}>
            <line
              x1={xScale(t)}
              x2={xScale(t)}
              y1={margin.top}
              y2={margin.top + innerHeight}
              stroke="#E5E8EB"
              strokeWidth={1}
            />
            <text
              x={xScale(t)}
              y={margin.top + innerHeight + 18}
              textAnchor="middle"
              className="text-[11px] font-mono fill-muted"
            >
              {t}h
            </text>
          </g>
        ))}

        {/* X and Y Axis titles */}
        <text
          x={margin.left + innerWidth / 2}
          y={dimensions.height - 10}
          textAnchor="middle"
          className="text-xs font-sans fill-muted font-medium"
        >
          Time (hours)
        </text>
        <text
          transform={`rotate(-90)`}
          x={-(margin.top + innerHeight / 2)}
          y={16}
          textAnchor="middle"
          className="text-xs font-sans fill-muted font-medium"
        >
          Iddq (µA)
        </text>

        {/* Static Limit Line */}
        {staticLimitY >= margin.top && staticLimitY <= margin.top + innerHeight && (
          <g>
            <line
              x1={margin.left}
              x2={margin.left + innerWidth}
              y1={staticLimitY}
              y2={staticLimitY}
              stroke="#5F6B73"
              strokeWidth={1.5}
              strokeDasharray="4 3"
            />
            <text
              x={margin.left + 8}
              y={staticLimitY - 5}
              className="text-[11px] font-mono fill-muted font-semibold"
            >
              Static limit: {staticLimit} µA
            </text>
          </g>
        )}

        {/* Background Neutral Part Traces */}
        <g>
          {parts.map(p => {
            if (p.id === selectedPart?.id) return null;
            const pts = intervals.map(t => ({ t, v: p.readings[t] || 0 }));
            return (
              <path
                key={p.id}
                d={lineGenerator(pts) || ''}
                fill="none"
                stroke="#B0B7BC"
                strokeWidth={1}
                strokeOpacity={0.35}
                className="cursor-pointer hover:stroke-[#1C2328] hover:stroke-opacity-80 transition-colors"
                onClick={() => onSelectPart(p.partId)}
              />
            );
          })}
        </g>

        {/* Safety Slope Reference Line */}
        {safetyLinePoints && (
          <g>
            <line
              x1={safetyLinePoints.x1}
              y1={safetyLinePoints.y1}
              x2={safetyLinePoints.x2}
              y2={safetyLinePoints.y2}
              stroke="#1C2328"
              strokeWidth={1.25}
              strokeDasharray="4 3"
            />
            <text
              x={safetyLinePoints.x2}
              y={safetyLinePoints.y2 + 16}
              textAnchor="end"
              className="text-[10px] font-mono fill-main"
            >
              Safety slope {safetySlopeLimit} µA/h
            </text>
          </g>
        )}

        {/* Confidence Band Polygon */}
        {confidencePolygonD && (
          <g>
            <path d={confidencePolygonD} fill="url(#confidenceHatch)" />
            <path d={confidencePolygonD} fill="#D63A2F" fillOpacity={0.08} />
          </g>
        )}

        {/* Dashed Forecast Line */}
        {showPredicted && forecastPoints.length > 0 && (
          <path
            d={lineGenerator(forecastPoints) || ''}
            fill="none"
            stroke="#D63A2F"
            strokeWidth={2}
            strokeDasharray="4 3"
          />
        )}

        {/* Saturated Selected Part Line */}
        {selectedPart && selectedPoints.length > 0 && (
          <g>
            <path
              d={lineGenerator(selectedPoints) || ''}
              fill="none"
              stroke="#D63A2F"
              strokeWidth={2.5}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            {selectedPoints.map((pt, idx) => (
              <circle
                key={`sel-pt-${idx}`}
                cx={xScale(pt.t)}
                cy={yScale(Math.max(0.1, pt.v))}
                r={4}
                fill="#D63A2F"
                stroke="#FFFFFF"
                strokeWidth={1.5}
              />
            ))}
          </g>
        )}

        {/* Dynamic Callout Box near 168h point */}
        {calloutPos && selectedPart && prediction && (
          <g transform={`translate(${calloutPos.x}, ${calloutPos.y})`}>
            <rect
              width={160}
              height={58}
              fill="#FFFFFF"
              stroke="#D63A2F"
              strokeWidth={1.2}
              rx={2}
            />
            <text x={8} y={15} className="font-mono text-xs font-bold fill-reject">
              {selectedPart.partId}
            </text>
            <text x={8} y={29} className="font-mono text-[11px] fill-main">
              Predicted 168h: <tspan className="font-bold">{prediction.predicted168h} µA</tspan>
            </text>
            <text x={8} y={42} className="font-mono text-[10px] fill-muted">
              {Math.abs(prediction.robustZScore).toFixed(1)}σ above lot trend
            </text>
            <text x={8} y={53} className="font-mono text-[10px] fill-muted">
              {prediction.passesStaticLimit
                ? `Passes static limit (${staticLimit} µA)`
                : `Exceeds static limit (${staticLimit} µA)`}
            </text>
          </g>
        )}
      </svg>
    </div>
  );
};
