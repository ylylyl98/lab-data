import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { listArtifacts } from '../api';
import type { Artifact, Page } from '../types';
import { ArtifactsPage } from './ArtifactsPage';

vi.mock('../api', () => ({
  listArtifacts: vi.fn(),
  getPreview: vi.fn(),
  assetUrl: vi.fn(
    (id: string, path: string) => `/artifacts/${id}/preview/assets/${path}`,
  ),
  fetchAssetText: vi.fn(),
}));

const listArtifactsMock = vi.mocked(listArtifacts);

const artifact: Artifact = {
  artifact_id: 'art-000000000000000000000001',
  device_id: 'D356',
  experiment_id: null,
  role: 'raw',
  category: 'document',
  extension: 'pptx',
  media_type:
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  review_state: 'unknown',
  storage_source_id: 'source',
  relative_path: 'D356/deck.pptx',
  filename: 'deck.pptx',
  size_bytes: null,
  mtime_ns: null,
  metadata: {},
  derived_from: [],
};

function page<T>(items: T[], total: number): Page<T> {
  return { items, total_count: total, limit: 50, offset: 0 };
}

function renderArtifacts() {
  return render(
    <MemoryRouter initialEntries={['/artifacts']}>
      <ArtifactsPage />
    </MemoryRouter>,
  );
}

describe('ArtifactsPage', () => {
  beforeEach(() => {
    listArtifactsMock.mockReset();
  });

  it('renders total_count and pagination controls', async () => {
    listArtifactsMock.mockResolvedValue(page([artifact], 120));
    renderArtifacts();
    expect(await screen.findByText('120 total')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Prev' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Next' })).toBeEnabled();
  });

  it('renders the filename as the primary artifact link label', async () => {
    listArtifactsMock.mockResolvedValue(page([artifact], 1));
    renderArtifacts();
    expect(await screen.findByRole('link', { name: 'deck.pptx' })).toBeTruthy();
    expect(screen.getByText('art-000000000000000000000001')).toBeTruthy();
  });
});
