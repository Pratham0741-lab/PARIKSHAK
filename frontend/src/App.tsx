import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AppShell } from './components/layout/AppShell';
import { OverviewScreen } from './screens/OverviewScreen';
import { LotAnalysisScreen } from './screens/LotAnalysisScreen';
import { ComponentDetailScreen } from './screens/ComponentDetailScreen';
import { DecisionQueueScreen } from './screens/DecisionQueueScreen';
import { ModelPerformanceScreen } from './screens/ModelPerformanceScreen';
import { DataIngestScreen } from './screens/DataIngestScreen';
import { AuditReportScreen } from './screens/AuditReportScreen';
import { OutlierDetectionScreen } from './screens/OutlierDetectionScreen';

export const App: React.FC = () => (
  <BrowserRouter>
    <Routes>
      <Route path="/" element={<AppShell />}>
        <Route index element={<OverviewScreen />} />
        <Route path="lot" element={<LotAnalysisScreen />} />
        <Route path="part" element={<ComponentDetailScreen />} />
        <Route path="part/:id" element={<ComponentDetailScreen />} />
        <Route path="review" element={<DecisionQueueScreen />} />
        <Route path="trends" element={<OutlierDetectionScreen />} />
        <Route path="model" element={<ModelPerformanceScreen />} />
        <Route path="ingest" element={<DataIngestScreen />} />
        <Route path="reports" element={<AuditReportScreen />} />
        {/* old routes */}
        <Route path="lots" element={<Navigate to="/" replace />} />
        <Route path="outliers" element={<Navigate to="/lot" replace />} />
        <Route path="drift" element={<Navigate to="/part" replace />} />
        <Route path="components" element={<Navigate to="/part" replace />} />
        <Route path="decisions" element={<Navigate to="/review" replace />} />
        <Route path="judge" element={<Navigate to="/model" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  </BrowserRouter>
);
