import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  searchArtifacts,
  searchDevices,
  searchExperiments,
} from '../api';
import { HomePage } from './HomePage';

vi.mock('../api', () => ({
  listDevices: vi.fn().mockResolvedValue([]),
  listExperiments: vi.fn().mockResolvedValue([]),
  listArtifacts: vi.fn().mockResolvedValue([]),
  searchDevices: vi.fn().mockResolvedValue([]),
  searchExperiments: vi.fn().mockResolvedValue([]),
  searchArtifacts: vi.fn().mockResolvedValue([]),
}));

const searchDevicesMock = vi.mocked(searchDevices);
const searchExperimentsMock = vi.mocked(searchExperiments);
const searchArtifactsMock = vi.mocked(searchArtifacts);

function renderHome() {
  return render(
    <MemoryRouter>
      <HomePage />
    </MemoryRouter>,
  );
}

function submit(segment: string, query: string) {
  fireEvent.click(screen.getByRole('tab', { name: segment }));
  fireEvent.change(screen.getByLabelText('Search ID'), {
    target: { value: query },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Search' }));
}

async function flush() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

describe('HomePage search', () => {
  beforeEach(() => {
    searchDevicesMock.mockClear();
    searchExperimentsMock.mockClear();
    searchArtifactsMock.mockClear();
  });

  it('searches devices by device_id', async () => {
    renderHome();
    submit('Devices', 'D356');
    expect(searchDevicesMock).toHaveBeenCalledWith('D356');
    await flush();
  });

  it('searches experiments by experiment_id', async () => {
    renderHome();
    submit('Experiments', 'YZ247-0432');
    expect(searchExperimentsMock).toHaveBeenCalledWith('YZ247-0432');
    await flush();
  });

  it('searches artifacts by artifact_id', async () => {
    renderHome();
    submit('Artifacts', 'art-1');
    expect(searchArtifactsMock).toHaveBeenCalledWith('art-1');
    await flush();
  });
});
