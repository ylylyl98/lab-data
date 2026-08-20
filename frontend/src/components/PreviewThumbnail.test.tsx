import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getPreview } from '../api';
import type { Artifact, Preview, PreviewAsset } from '../types';
import PreviewThumbnail, { resolveThumbnailAsset } from './PreviewThumbnail';

vi.mock('../api', () => ({
  getPreview: vi.fn(),
  assetUrl: vi.fn(
    (id: string, path: string) => `/artifacts/${id}/preview/assets/${path}`,
  ),
  fetchAssetText: vi.fn(),
}));

const getPreviewMock = vi.mocked(getPreview);

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
  filename: 'figure.png',
  size_bytes: null,
  mtime_ns: null,
  metadata: {},
  derived_from: [],
};

function asset(overrides: Partial<PreviewAsset> = {}): PreviewAsset {
  return {
    path: 'asset',
    kind: 'image',
    media_type: 'image/png',
    size_bytes: 1,
    sha256: 'x',
    ...overrides,
  };
}

function preview(overrides: Partial<Preview> = {}): Preview {
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

describe('resolveThumbnailAsset', () => {
  it('prefers an image-kind asset for image previews', () => {
    const image = asset({ path: 'image.png', kind: 'image' });
    const other = asset({ path: 'other.png', kind: 'other' });
    expect(
      resolveThumbnailAsset(preview({ kind: 'image', assets: [other, image] })),
    ).toBe(image);
  });

  it('falls back to the first asset for image previews without an image kind', () => {
    const first = asset({ path: 'first.png', kind: 'other' });
    expect(resolveThumbnailAsset(preview({ kind: 'image', assets: [first] }))).toBe(
      first,
    );
  });

  it('prefers the plot asset for table previews', () => {
    const search = asset({ path: 'search', kind: 'search' });
    const plot = asset({ path: 'plot.svg', kind: 'plot' });
    expect(
      resolveThumbnailAsset(preview({ kind: 'table', assets: [search, plot] })),
    ).toBe(plot);
  });

  it('resolves a plot.svg path for table previews without a plot kind', () => {
    const plot = asset({ path: 'plot.svg', kind: 'other' });
    expect(
      resolveThumbnailAsset(preview({ kind: 'table', assets: [plot] })),
    ).toBe(plot);
  });

  it('prefers the first slide asset for slide previews', () => {
    const search = asset({ path: 'search', kind: 'search' });
    const slide1 = asset({ path: 'slides/0001.svg', kind: 'slide' });
    const slide2 = asset({ path: 'slides/0002.svg', kind: 'slide' });
    expect(
      resolveThumbnailAsset(
        preview({ kind: 'slide', assets: [search, slide1, slide2] }),
      ),
    ).toBe(slide1);
  });

  it('returns null for unknown kinds', () => {
    expect(
      resolveThumbnailAsset(
        preview({
          kind: 'placeholder',
          assets: [asset({ path: 'placeholder.svg', kind: 'placeholder' })],
        }),
      ),
    ).toBeNull();
  });
});

describe('PreviewThumbnail', () => {
  beforeEach(() => {
    getPreviewMock.mockReset();
  });

  it('renders an image thumbnail when a preview asset resolves', async () => {
    getPreviewMock.mockResolvedValue(
      preview({
        kind: 'image',
        assets: [asset({ path: 'image.png', kind: 'image' })],
      }),
    );
    render(<PreviewThumbnail artifact={artifact} />);
    const image = await screen.findByAltText('figure.png');
    expect(image.getAttribute('src')).toBe(
      '/artifacts/a1/preview/assets/image.png',
    );
    expect(image.getAttribute('loading')).toBe('lazy');
  });

  it('renders a placeholder when the preview is null', async () => {
    getPreviewMock.mockResolvedValue(null);
    const { container } = render(<PreviewThumbnail artifact={artifact} />);
    expect(await screen.findByText('PNG')).toBeTruthy();
    expect(container.querySelector('.thumb-placeholder')).toBeTruthy();
  });

  it('renders a placeholder when no thumbnail asset resolves', async () => {
    getPreviewMock.mockResolvedValue(
      preview({
        kind: 'placeholder',
        assets: [asset({ path: 'placeholder.svg', kind: 'placeholder' })],
      }),
    );
    render(<PreviewThumbnail artifact={artifact} />);
    expect(await screen.findByText('PNG')).toBeTruthy();
  });
});
