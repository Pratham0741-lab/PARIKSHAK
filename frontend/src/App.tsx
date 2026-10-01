import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AppShell } from './components/layout/AppShell';
import { OverviewScreen } from './screens/OverviewScreen';
import { LotAnalysisScreen } from './screens/LotAnalysisScreen';
import { PartDetailScreen } from './screens/PartDetailScreen';
import { ReviewQueueScreen } from './screens/ReviewQueueScreen';
import { ModelScreen } from './screens/ModelScreen';
import { DataIngestScreen } from './screens/DataIngestScreen';
import { AuditReportScreen } from './screens/AuditReportScreen';
import { TrendsScreen } from './screens/TrendsScreen';

export const App: React.FC = () => (
  <BrowserRouter>
    <Routes>
      <Route path="/" element={<AppShell />}>
        <Route index element={<OverviewScreen />} />
        <Route path="lot" element={<LotAnalysisScreen />} />
        <Route path="part" element={<PartDetailScreen />} />
        <Route path="part/:id" element={<PartDetailScreen />} />
        <Route path="review" element={<ReviewQueueScreen />} />
        <Route path="trends" element={<TrendsScreen />} />
        <Route path="model" element={<ModelScreen />} />
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
