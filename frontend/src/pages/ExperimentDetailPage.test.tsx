import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getExperiment, getExperimentArtifacts } from '../api';
import type { Experiment, MeasuredOn, Page } from '../types';
import { ExperimentDetailPage } from './ExperimentDetailPage';

vi.mock('../api', () => ({
  getExperiment: vi.fn(),
  getExperimentArtifacts: vi.fn(),
  getPreview: vi.fn().mockResolvedValue(null),
  assetUrl: vi.fn(
    (id: string, path: string) => `/artifacts/${id}/preview/assets/${path}`,
  ),
  fetchAssetText: vi.fn(),
}));

const getExperimentMock = vi.mocked(getExperiment);
const getExperimentArtifactsMock = vi.mocked(getExperimentArtifacts);

const measuredOn: MeasuredOn = {
  device_id: 'D356',
  evidence: 'explicit device-directory context',
  source_reference: 'D356 WSe2_AuSplitGate',
  extraction_method: 'device_directory_context',
  review_status: 'unknown',
};

function makeExperiment(overrides: Partial<Experiment> = {}): Experiment {
  return {
    experiment_id: 'YZ247-0432',
    metadata: {
      sample_id: 'SAMPLE-X',
      temperature_K: 4.2,
      measurement_type: 'photoluminescence',
    },
    files_by_role: { raw: ['D356/raw-YZ247-0432.dat'] },
    lineage: [],
    warnings: [],
    confidence: 0.82,
    needs_review: false,
    review_state: 'unknown',
    measured_on: null,
    ...overrides,
  };
}

function page<T>(items: T[]): Page<T> {
  return { items, total_count: items.length, limit: 50, offset: 0 };
}

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
    getExperimentMock.mockResolvedValue(makeExperiment());
    getExperimentArtifactsMock.mockResolvedValue(page([]));
  });

  it('renders the scientific summary first', async () => {
    renderExperiment();
    expect(await screen.findByText('Summary')).toBeTruthy();
    expect(screen.getAllByText('photoluminescence').length).toBeGreaterThan(0);
    expect(screen.getAllByText('4.2').length).toBeGreaterThan(0);
    expect(screen.getAllByText('SAMPLE-X').length).toBeGreaterThan(0);
  });

  it('renders files grouped by role labels', async () => {
    renderExperiment();
    expect(await screen.findByText('Raw data')).toBeTruthy();
    expect(screen.getByText('D356/raw-YZ247-0432.dat')).toBeTruthy();
  });

  it('renders measured_on with expandable provenance evidence', async () => {
    getExperimentMock.mockResolvedValue(makeExperiment({ measured_on: measuredOn }));
    renderExperiment();
    expect(await screen.findByText('Measured on')).toBeTruthy();
    const deviceLinks = screen.getAllByRole('link', { name: 'D356' });
    expect(
      deviceLinks.some((link) => link.getAttribute('href') === '/devices/D356'),
    ).toBe(true);
    expect(
      screen.getByText('Evidence: explicit device-directory context'),
    ).toBeTruthy();
    expect(screen.getByText('Provenance details')).toBeTruthy();
    expect(screen.getByText('D356 WSe2_AuSplitGate')).toBeTruthy();
    expect(screen.getByText('device_directory_context')).toBeTruthy();
  });

  it('shows no device linkage without measured_on', async () => {
    renderExperiment();
    expect(await screen.findByText('not explicitly linked')).toBeTruthy();
    expect(screen.queryByText('Measured on')).toBeNull();
    expect(screen.queryByText('Provenance details')).toBeNull();
  });

  it('shows review state and needs-review flag', async () => {
    getExperimentMock.mockResolvedValue(
      makeExperiment({ review_state: 'unknown', needs_review: true }),
    );
    renderExperiment();
    expect(await screen.findByText('needs review')).toBeTruthy();
  });

  it('shows a calm review notice with warnings and unresolved files', async () => {
    getExperimentMock.mockResolvedValue(
      makeExperiment({
        needs_review: true,
        warnings: ['unsupported electrical expression: FixTG4V-SweepBG1=2'],
        metadata: {
          unresolved_processed_files: [
            'D356 WSe2_AuSplitGate/Processed Data/YZ356_FixTG4V_avg1_DR_R_Self.dat',
          ],
        },
      }),
    );
    renderExperiment();
    expect(await screen.findByText('Review needed')).toBeTruthy();
    expect(
      screen.getByText('unsupported electrical expression: FixTG4V-SweepBG1=2'),
    ).toBeTruthy();
    expect(
      screen.getAllByText(
        'D356 WSe2_AuSplitGate/Processed Data/YZ356_FixTG4V_avg1_DR_R_Self.dat',
      ).length,
    ).toBeGreaterThan(0);
  });

  it('renders persisted lineage as readable chains', async () => {
    getExperimentMock.mockResolvedValue(
      makeExperiment({
        lineage: [
          {
            source: 'D356 WSe2_AuSplitGate/Initial Data/YZ356_BG1only.csv',
            target:
              'D356 WSe2_AuSplitGate/Processed Data/YZ356_BG1only_PL.dat',
            relation: 'derived_from',
          },
          {
            source:
              'D356 WSe2_AuSplitGate/Processed Data/YZ356_BG1only_PL.dat',
            target:
              'D356 WSe2_AuSplitGate/Processed Data/YZ356_BG1only_PL_linear.png',
            relation: 'derived_from',
          },
        ],
      }),
    );
    renderExperiment();
    expect(
      await screen.findByText(
        'YZ356_BG1only.csv -> YZ356_BG1only_PL.dat -> YZ356_BG1only_PL_linear.png (derived_from)',
      ),
    ).toBeTruthy();
  });

  it('fetches artifacts as a bounded page', async () => {
    renderExperiment();
    expect(await screen.findByText('SAMPLE-X')).toBeTruthy();
    expect(getExperimentArtifactsMock).toHaveBeenCalledWith('YZ247-0432', {
      limit: 50,
      offset: 0,
    });
  });
});
