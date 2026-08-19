import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { Layout } from './components/Layout';
import { ArtifactDetailPage } from './pages/ArtifactDetailPage';
import { ArtifactsPage } from './pages/ArtifactsPage';
import { DeviceDetailPage } from './pages/DeviceDetailPage';
import { DevicesPage } from './pages/DevicesPage';
import { ExperimentDetailPage } from './pages/ExperimentDetailPage';
import { ExperimentsPage } from './pages/ExperimentsPage';
import { HomePage } from './pages/HomePage';

export default function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/devices" element={<DevicesPage />} />
          <Route path="/devices/:id" element={<DeviceDetailPage />} />
          <Route path="/experiments" element={<ExperimentsPage />} />
          <Route path="/experiments/:id" element={<ExperimentDetailPage />} />
          <Route path="/artifacts" element={<ArtifactsPage />} />
          <Route path="/artifacts/:id" element={<ArtifactDetailPage />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}
