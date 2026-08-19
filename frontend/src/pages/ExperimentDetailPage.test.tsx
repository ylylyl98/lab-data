import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getExperiment, getExperimentArtifacts } from '../api';
import type { Experiment } from '../types';
import { ExperimentDetailPage } from './ExperimentDetailPage';

vi.mock('../api', () => ({
  getExperiment: vi.fn(),
  getExperimentArtifacts: vi.fn(),
  getPreview: vi.fn(),
  assetUrl: vi.fn((id: string, path: string) => `/artifacts/${id}/preview/assets/${path}`),
  fetchAssetText: vi.fn(),
}));

const getExperimentMock = vi.mocked(getExperiment);
const getExperimentArtifactsMock = vi.mocked(getExperimentArtifacts);

const experiment: Experiment = {
  experiment_id: 'YZ247-0432',
  metadata: { sample_id: 'SAMPLE-X', temperature_K: 4.2 },
  files_by_role: { raw: ['D356/raw-YZ247-0432.dat'] },
  lineage: [],
  warnings: [],
  confidence: 0.82,
  needs_review: false,
};

function renderExperiment() {
  return render(
    <MemoryRouter initialEntries={['/experiments/YZ247-0432']}>
      <Routes>
        <Route path="/experiments/:id" element={<ExperimentDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('ExperimentDetailPage', () => {
  beforeEach(() => {
    getExperimentMock.mockResolvedValue(experiment);
    getExperimentArtifactsMock.mockResolvedValue([]);
  });

  it('renders metadata values', async () => {
    renderExperiment();
    expect(await screen.findByText('SAMPLE-X')).toBeTruthy();
  });

  it('renders files_by_role paths', async () => {
    renderExperiment();
    expect(await screen.findByText('raw')).toBeTruthy();
    expect(await screen.findByText('D356/raw-YZ247-0432.dat')).toBeTruthy();
  });
});
