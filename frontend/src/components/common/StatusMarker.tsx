import React from 'react';
import { PartStatus } from '../../data/types';

interface StatusMarkerProps {
  status: PartStatus;
  showText?: boolean;
  className?: string;
}

export const StatusMarker: React.FC<StatusMarkerProps> = ({
  status,
  showText = true,
  className = '',
}) => {
  let colorClass = 'bg-accept text-accept';
  if (status === 'Reject') colorClass = 'bg-reject text-reject';
  if (status === 'Review') colorClass = 'bg-review text-review';

  return (
    <div className={`inline-flex items-center gap-1.5 font-mono text-xs ${className}`}>
      <span className={`inline-block w-2 h-2 shrink-0 ${colorClass.split(' ')[0]}`} />
      {showText && <span className={`font-medium ${colorClass.split(' ')[1]}`}>{status}</span>}
    </div>
  );
};
