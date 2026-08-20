import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getArtifact } from '../api';
import type { Artifact } from '../types';
import { ArtifactDetailPage } from './ArtifactDetailPage';

vi.mock('../api', () => ({
  getArtifact: vi.fn(),
  getPreview: vi.fn().mockResolvedValue(null),
  assetUrl: vi.fn(
    (id: string, path: string) => `/artifacts/${id}/preview/assets/${path}`,
  ),
  fetchAssetText: vi.fn(),
}));

const getArtifactMock = vi.mocked(getArtifact);

const artifact: Artifact = {
  artifact_id: 'art-000000000000000000000001',
  device_id: 'D356',
  experiment_id: 'D356-0000',
  role: 'figure',
  category: 'image',
  extension: 'png',
  media_type: 'image/png',
  review_state: 'unknown',
  storage_source_id: 'dropbox_device_docs',
  relative_path:
    'D356 WSe2_AuSplitGate/Processed Data/YZ356_BG1only_PL_linear.png',
  filename: 'YZ356_BG1only_PL_linear.png',
  size_bytes: 100,
  mtime_ns: 123,
  metadata: {},
  derived_from: [
    {
      source:
        'D356 WSe2_AuSplitGate/Processed Data/YZ356_BG1only_PL_linear.png',
      target: 'D356 WSe2_AuSplitGate/Processed Data/YZ356_BG1only_PL.dat',
      relation: 'derived_from',
    },
  ],
};

function renderArtifact() {
  return render(
    <MemoryRouter initialEntries={['/artifacts/art-000000000000000000000001']}>
      <Routes>
        <Route path="/artifacts/:id" element={<ArtifactDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('ArtifactDetailPage', () => {
  beforeEach(() => {
    getArtifactMock.mockResolvedValue(artifact);
  });

  it('renders the human-readable filename as the primary heading', async () => {
    renderArtifact();
    const heading = await screen.findByRole('heading', {
      level: 1,
      name: 'YZ356_BG1only_PL_linear.png',
    });
    expect(heading).toBeTruthy();
  });

  it('renders role, category, and review state', async () => {
    renderArtifact();
    expect(await screen.findByText('figure')).toBeTruthy();
    expect(screen.getByText('image')).toBeTruthy();
    expect(screen.getAllByText('unknown').length).toBeGreaterThan(0);
  });

  it('renders derived lineage edges', async () => {
    renderArtifact();
    expect(await screen.findByText('Derived')).toBeTruthy();
    expect(
      screen.getByText(
        'D356 WSe2_AuSplitGate/Processed Data/YZ356_BG1only_PL_linear.png -> D356 WSe2_AuSplitGate/Processed Data/YZ356_BG1only_PL.dat (derived_from)',
      ),
    ).toBeTruthy();
  });

  it('renders the canonical relative path and linked device/experiment', async () => {
    renderArtifact();
    expect(
      await screen.findByText(
        'D356 WSe2_AuSplitGate/Processed Data/YZ356_BG1only_PL_linear.png',
      ),
    ).toBeTruthy();
    expect(screen.getByRole('link', { name: 'D356' }).getAttribute('href')).toBe(
      '/devices/D356',
    );
    expect(
      screen.getByRole('link', { name: 'D356-0000' }).getAttribute('href'),
    ).toBe('/experiments/D356-0000');
  });

  it('moves artifact_id into the muted Details block', async () => {
    renderArtifact();
    expect(await screen.findByText('Details')).toBeTruthy();
    expect(screen.getByText('art-000000000000000000000001')).toBeTruthy();
  });
});
