import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  getDevice,
  getDeviceArtifacts,
  getDeviceDocuments,
  getDeviceExperiments,
} from '../api';
import type { Artifact, Device } from '../types';
import { DeviceDetailPage } from './DeviceDetailPage';

vi.mock('../api', () => ({
  getDevice: vi.fn(),
  getDeviceArtifacts: vi.fn(),
  getDeviceDocuments: vi.fn(),
  getDeviceExperiments: vi.fn(),
  getPreview: vi.fn(),
  assetUrl: vi.fn((id: string, path: string) => `/artifacts/${id}/preview/assets/${path}`),
  fetchAssetText: vi.fn(),
}));

const getDeviceMock = vi.mocked(getDevice);
const getDeviceArtifactsMock = vi.mocked(getDeviceArtifacts);
const getDeviceDocumentsMock = vi.mocked(getDeviceDocuments);
const getDeviceExperimentsMock = vi.mocked(getDeviceExperiments);

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

const artifact: Artifact = {
  artifact_id: 'art-1',
  device_id: 'D356',
  experiment_id: null,
  role: 'raw',
  category: 'table',
  extension: 'csv',
  media_type: 'text/csv',
  review_state: 'unknown',
  storage_source_id: 'source',
  relative_path: 'D356/a.csv',
  size_bytes: null,
  mtime_ns: null,
  metadata: {},
};

const document: Artifact = {
  ...artifact,
  artifact_id: 'doc-1',
  extension: 'pptx',
  media_type:
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  relative_path: 'D356/deck.pptx',
};

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
    getDeviceArtifactsMock.mockResolvedValue([artifact]);
    getDeviceDocumentsMock.mockResolvedValue([document]);
    getDeviceExperimentsMock.mockResolvedValue([]);
  });

  it('renders associated artifacts and documents', async () => {
    renderDevice();
    expect(await screen.findByText('art-1')).toBeTruthy();
    expect(await screen.findByText('doc-1')).toBeTruthy();
  });

  it('shows the explicit no-experiments state without inference', async () => {
    renderDevice();
    expect(await screen.findByText('No explicit device experiments')).toBeTruthy();
  });
});
