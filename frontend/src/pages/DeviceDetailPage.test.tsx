import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  getDevice,
  getDeviceArtifacts,
  getDeviceExperiments,
  getPreview,
} from '../api';
import type { Artifact, Device, Page } from '../types';
import { DeviceDetailPage } from './DeviceDetailPage';

vi.mock('../api', () => ({
  getDevice: vi.fn(),
  getDeviceArtifacts: vi.fn(),
  getDeviceExperiments: vi.fn(),
  getPreview: vi.fn(),
  assetUrl: vi.fn(
    (id: string, path: string) => `/artifacts/${id}/preview/assets/${path}`,
  ),
  fetchAssetText: vi.fn(),
}));

const getDeviceMock = vi.mocked(getDevice);
const getDeviceArtifactsMock = vi.mocked(getDeviceArtifacts);
const getDeviceExperimentsMock = vi.mocked(getDeviceExperiments);
const getPreviewMock = vi.mocked(getPreview);

const device: Device = {
  device_id: 'D356',
  display_label: 'D356 Spectrometer',
  maker_namespace: null,
  local_device_id: null,
  device_type: 'spectrometer',
  review_state: 'unknown',
  aliases: ['YZ-D356'],
  metadata: { manufacturer: 'YZ Optics' },
};

const document: Artifact = {
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

function page<T>(items: T[]): Page<T> {
  return { items, total_count: items.length, limit: 50, offset: 0 };
}

function renderDevice() {
  return render(
    <MemoryRouter initialEntries={['/devices/D356']}>
      <Routes>
        <Route path="/devices/:id" element={<DeviceDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('DeviceDetailPage', () => {
  beforeEach(() => {
    getDeviceMock.mockResolvedValue(device);
    getDeviceArtifactsMock.mockResolvedValue(page([document]));
    getDeviceExperimentsMock.mockResolvedValue(page([]));
    getPreviewMock.mockResolvedValue(null);
  });

  it('shows artifact-kind tabs with Documents active by default', async () => {
    renderDevice();
    const documentsTab = await screen.findByRole('tab', { name: 'Documents' });
    expect(documentsTab.getAttribute('aria-selected')).toBe('true');
    expect(screen.getByRole('tab', { name: 'Images' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'Data' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'Other' })).toBeTruthy();
  });

  it('fetches and renders the bounded Documents tab by default', async () => {
    renderDevice();
    expect(await screen.findByText('deck.pptx')).toBeTruthy();
    expect(getDeviceArtifactsMock).toHaveBeenCalledWith('D356', {
      kind: 'document',
      limit: 24,
      offset: 0,
    });
  });

  it('renders a preview gallery for the Documents tab', async () => {
    renderDevice();
    expect(await screen.findByText('deck.pptx')).toBeTruthy();
    expect(getPreviewMock).toHaveBeenCalledWith(
      'art-000000000000000000000001',
    );
  });

  it('shows the explicit no-experiments state without inference', async () => {
    renderDevice();
    expect(await screen.findByText('No explicit device experiments')).toBeTruthy();
  });
});
