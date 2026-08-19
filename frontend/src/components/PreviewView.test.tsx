import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { assetUrl, fetchAssetText, getPreview } from '../api';
import type { Artifact, Preview } from '../types';
import { PreviewView } from './PreviewView';

vi.mock('../api', () => ({
  getPreview: vi.fn(),
  assetUrl: vi.fn((id: string, path: string) => `/artifacts/${id}/preview/assets/${path}`),
  fetchAssetText: vi.fn(),
}));

const getPreviewMock = vi.mocked(getPreview);
const assetUrlMock = vi.mocked(assetUrl);
const fetchAssetTextMock = vi.mocked(fetchAssetText);

const artifact: Artifact = {
  artifact_id: 'a1',
  device_id: null,
  experiment_id: null,
  role: 'raw',
  category: 'image',
  extension: 'png',
  media_type: 'image/png',
  review_state: 'unknown',
  storage_source_id: 'source',
  relative_path: 'figure.png',
  size_bytes: null,
  mtime_ns: null,
  metadata: {},
};

function preview(overrides: Partial<Preview>): Preview {
  return {
    artifact_id: 'a1',
    preview_id: 'p1',
    status: 'ready',
    kind: 'image',
    fresh: true,
    source_freshness_checked: true,
    assets: [],
    warnings: [],
    search_match: { query: null, matched: null, text_available: false },
    ...overrides,
  };
}

describe('PreviewView', () => {
  beforeEach(() => {
    getPreviewMock.mockReset();
    assetUrlMock.mockImplementation(
      (id: string, path: string) => `/artifacts/${id}/preview/assets/${path}`,
    );
    fetchAssetTextMock.mockReset();
  });

  it('renders an image asset for image previews', async () => {
    getPreviewMock.mockResolvedValue(
      preview({
        kind: 'image',
        assets: [
          {
            path: 'image.png',
            kind: 'image',
            media_type: 'image/png',
            size_bytes: 10,
            sha256: 'x',
          },
        ],
      }),
    );
    render(<PreviewView artifact={artifact} />);
    expect(await screen.findByAltText('image.png')).toBeTruthy();
  });

  it('renders the plot and table for table previews', async () => {
    getPreviewMock.mockResolvedValue(
      preview({
        kind: 'table',
        assets: [
          {
            path: 'plot.svg',
            kind: 'plot',
            media_type: 'image/svg+xml',
            size_bytes: 1,
            sha256: 'x',
          },
          {
            path: 'table.json',
            kind: 'table',
            media_type: 'application/json',
            size_bytes: 1,
            sha256: 'x',
          },
        ],
      }),
    );
    fetchAssetTextMock.mockResolvedValue(
      '{"delimiter":",","headers":["wavelength_nm","intensity"],"rows":[["532","0.42"]]}',
    );
    render(<PreviewView artifact={artifact} />);
    expect(await screen.findByAltText('plot.svg')).toBeTruthy();
    expect(await screen.findByText('wavelength_nm')).toBeTruthy();
    expect(await screen.findByText('532')).toBeTruthy();
  });

  it('renders slide thumbnails and search text for slide previews', async () => {
    getPreviewMock.mockResolvedValue(
      preview({
        kind: 'slide',
        assets: [
          {
            path: 'slides/0001.svg',
            kind: 'slide',
            media_type: 'image/svg+xml',
            size_bytes: 1,
            sha256: 'x',
          },
          {
            path: 'search_text.txt',
            kind: 'search',
            media_type: 'text/plain',
            size_bytes: 1,
            sha256: 'x',
          },
        ],
      }),
    );
    fetchAssetTextMock.mockResolvedValue('Deck title text');
    render(<PreviewView artifact={artifact} />);
    expect(await screen.findByAltText('slides/0001.svg')).toBeTruthy();
    expect(await screen.findByText('Deck title text')).toBeTruthy();
  });

  it('shows a non-ready status plainly', async () => {
    getPreviewMock.mockResolvedValue(
      preview({
        status: 'unsupported',
        kind: 'placeholder',
        warnings: ['preview unavailable: ValueError'],
        assets: [
          {
            path: 'placeholder.svg',
            kind: 'placeholder',
            media_type: 'image/svg+xml',
            size_bytes: 1,
            sha256: 'x',
          },
        ],
      }),
    );
    render(<PreviewView artifact={artifact} />);
    expect(await screen.findByText('Status: unsupported')).toBeTruthy();
  });

  it('shows no preview when the preview is null', async () => {
    getPreviewMock.mockResolvedValue(null);
    render(<PreviewView artifact={artifact} />);
    expect(await screen.findByText('No preview available')).toBeTruthy();
  });
});
