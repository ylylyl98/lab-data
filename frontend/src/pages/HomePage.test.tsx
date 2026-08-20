import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  getSummary,
  listArtifacts,
  listDevices,
  listExperiments,
  searchArtifacts,
  searchDevices,
  searchExperiments,
} from '../api';
import type { Page } from '../types';
import { HomePage } from './HomePage';

vi.mock('../api', () => ({
  getSummary: vi.fn(),
  listDevices: vi.fn(),
  listExperiments: vi.fn(),
  listArtifacts: vi.fn(),
  searchDevices: vi.fn(),
  searchExperiments: vi.fn(),
  searchArtifacts: vi.fn(),
}));

const getSummaryMock = vi.mocked(getSummary);
const listDevicesMock = vi.mocked(listDevices);
const listExperimentsMock = vi.mocked(listExperiments);
const listArtifactsMock = vi.mocked(listArtifacts);
const searchDevicesMock = vi.mocked(searchDevices);
const searchExperimentsMock = vi.mocked(searchExperiments);
const searchArtifactsMock = vi.mocked(searchArtifacts);

function page<T>(items: T[]): Page<T> {
  return { items, total_count: items.length, limit: 50, offset: 0 };
}

function renderHome() {
  return render(
    <MemoryRouter>
      <HomePage />
    </MemoryRouter>,
  );
}

async function flush() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

describe('HomePage', () => {
  beforeEach(() => {
    getSummaryMock.mockReset();
    listDevicesMock.mockReset();
    listExperimentsMock.mockReset();
    listArtifactsMock.mockReset();
    searchDevicesMock.mockReset();
    searchExperimentsMock.mockReset();
    searchArtifactsMock.mockReset();

    getSummaryMock.mockResolvedValue({
      devices: 3,
      experiments: 5,
      artifacts: 9,
    });
    listDevicesMock.mockResolvedValue(page([]));
    listExperimentsMock.mockResolvedValue(page([]));
    listArtifactsMock.mockResolvedValue(page([]));
    searchDevicesMock.mockResolvedValue(page([]));
    searchExperimentsMock.mockResolvedValue(page([]));
    searchArtifactsMock.mockResolvedValue(page([]));
  });

  it('loads the summary without fetching full catalogs on mount', async () => {
    renderHome();
    await flush();
    expect(getSummaryMock).toHaveBeenCalledTimes(1);
    expect(listDevicesMock).not.toHaveBeenCalled();
    expect(listExperimentsMock).not.toHaveBeenCalled();
    expect(listArtifactsMock).not.toHaveBeenCalled();
    expect(searchDevicesMock).not.toHaveBeenCalled();
    expect(searchExperimentsMock).not.toHaveBeenCalled();
    expect(searchArtifactsMock).not.toHaveBeenCalled();
  });

  it('runs a global search across all three entities', async () => {
    renderHome();
    fireEvent.change(screen.getByLabelText('Search query'), {
      target: { value: 'D356' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    expect(searchDevicesMock).toHaveBeenCalledWith('D356');
    expect(searchExperimentsMock).toHaveBeenCalledWith('D356');
    expect(searchArtifactsMock).toHaveBeenCalledWith('D356');
    await flush();
  });
});
