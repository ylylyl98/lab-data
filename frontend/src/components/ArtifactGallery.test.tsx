import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getPreview } from '../api';
import type { Artifact } from '../types';
import { ArtifactGallery } from './ArtifactGallery';

vi.mock('../api', () => ({
  getPreview: vi.fn(),
  assetUrl: vi.fn(
    (id: string, path: string) => `/artifacts/${id}/preview/assets/${path}`,
  ),
  fetchAssetText: vi.fn(),
}));

const getPreviewMock = vi.mocked(getPreview);

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

function renderGallery() {
  return render(
    <MemoryRouter>
      <ArtifactGallery artifacts={[artifact]} />
    </MemoryRouter>,
  );
}

describe('ArtifactGallery', () => {
  beforeEach(() => {
    getPreviewMock.mockReset();
    getPreviewMock.mockResolvedValue(null);
  });

  it('renders the filename as the primary label and id as secondary', () => {
    renderGallery();
    const label = screen.getByText('deck.pptx');
    const id = screen.getByText('art-000000000000000000000001');
    expect(label.className).toBe('artifact-card-label');
    expect(id.className).toBe('artifact-card-id');
  });

  it('opens the preview modal when a card is clicked', async () => {
    renderGallery();
    const card = screen.getByText('deck.pptx').closest('.artifact-card');
    expect(card).toBeTruthy();
    fireEvent.click(card!);
    expect(screen.getByRole('button', { name: 'Close preview' })).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Open detail' })).toBeTruthy();
    expect(await screen.findByText('No preview available')).toBeTruthy();
  });
});
