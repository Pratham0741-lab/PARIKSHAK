import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { WorkspaceLayout } from './components/layout/WorkspaceLayout';
import { DriftPredictorScreen } from './screens/DriftPredictorScreen';
import { LotOverviewScreen } from './screens/LotOverviewScreen';
import { DataIngestScreen } from './screens/DataIngestScreen';
import { OutlierDetectionScreen } from './screens/OutlierDetectionScreen';
import { ComponentDetailScreen } from './screens/ComponentDetailScreen';
import { DecisionQueueScreen } from './screens/DecisionQueueScreen';
import { ModelPerformanceScreen } from './screens/ModelPerformanceScreen';
import { AuditReportScreen } from './screens/AuditReportScreen';
import { JudgeScreen } from './screens/JudgeScreen';

export const App: React.FC = () => {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<WorkspaceLayout />}>
          <Route index element={<LotOverviewScreen />} />
          <Route path="lots" element={<LotOverviewScreen />} />
          <Route path="drift" element={<DriftPredictorScreen />} />
          <Route path="ingest" element={<DataIngestScreen />} />
          <Route path="outliers" element={<OutlierDetectionScreen />} />
          <Route path="components" element={<ComponentDetailScreen />} />
          <Route path="decisions" element={<DecisionQueueScreen />} />
          <Route path="model" element={<ModelPerformanceScreen />} />
          <Route path="reports" element={<AuditReportScreen />} />
          <Route path="judge" element={<JudgeScreen />} />
          <Route path="*" element={<Navigate to="/lots" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
};
