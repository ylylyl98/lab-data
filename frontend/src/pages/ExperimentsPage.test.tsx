import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { listExperiments } from '../api';
import type { Experiment, Page } from '../types';
import { ExperimentsPage } from './ExperimentsPage';

vi.mock('../api', () => ({
  listExperiments: vi.fn(),
}));

const listExperimentsMock = vi.mocked(listExperiments);

const experiment: Experiment = {
  experiment_id: 'exp-000000000000000000000001',
  metadata: {},
  files_by_role: {},
  lineage: [],
  warnings: [],
  confidence: 0.9,
  needs_review: false,
  review_state: 'unknown',
  measured_on: null,
};

function page(items: Experiment[], total: number): Page<Experiment> {
  return { items, total_count: total, limit: 50, offset: 0 };
}

function renderExperiments(initialEntry = '/experiments') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <ExperimentsPage />
    </MemoryRouter>,
  );
}

async function flush() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

describe('ExperimentsPage', () => {
  beforeEach(() => {
    listExperimentsMock.mockReset();
    listExperimentsMock.mockResolvedValue(page([experiment], 120));
  });

  it('renders total_count and pagination controls', async () => {
    renderExperiments();
    expect(await screen.findByText('120 total')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Prev' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Next' })).toBeEnabled();
    expect(listExperimentsMock).toHaveBeenCalledWith({
      q: undefined,
      limit: 50,
      offset: 0,
      measurement_type: undefined,
      temperature_K: undefined,
      magnetic_field_T: undefined,
      measurement_point_label: undefined,
      excitation_wavelength_nm: undefined,
    });
  });

  it('passes measurement type and temperature filters to listExperiments', async () => {
    renderExperiments();
    fireEvent.change(screen.getByLabelText('Measurement type'), {
      target: { value: 'photoluminescence' },
    });
    fireEvent.change(screen.getByLabelText('Temperature (K)'), {
      target: { value: '298' },
    });
    await flush();
    expect(listExperimentsMock).toHaveBeenLastCalledWith({
      q: undefined,
      limit: 50,
      offset: 0,
      measurement_type: 'photoluminescence',
      temperature_K: 298,
      magnetic_field_T: undefined,
      measurement_point_label: undefined,
      excitation_wavelength_nm: undefined,
    });
  });

  it('resets offset to 0 when a filter changes', async () => {
    renderExperiments();
    await screen.findByText('120 total');
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await flush();
    expect(listExperimentsMock).toHaveBeenLastCalledWith(
      expect.objectContaining({ offset: 50 }),
    );

    fireEvent.change(screen.getByLabelText('Temperature (K)'), {
      target: { value: '300' },
    });
    await flush();
    expect(listExperimentsMock).toHaveBeenLastCalledWith(
      expect.objectContaining({
        temperature_K: 300,
        offset: 0,
      }),
    );
  });

  it('clears all active filters on reset', async () => {
    renderExperiments();
    fireEvent.change(screen.getByLabelText('Measurement type'), {
      target: { value: 'absorption' },
    });
    fireEvent.change(screen.getByLabelText('Position / location'), {
      target: { value: 'p1' },
    });
    await flush();
    expect(screen.getByText('2 active')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Reset filters' }));
    await flush();
    expect(screen.getByRole('button', { name: 'Reset filters' })).toBeDisabled();
    expect(listExperimentsMock).toHaveBeenLastCalledWith({
      q: undefined,
      limit: 50,
      offset: 0,
      measurement_type: undefined,
      temperature_K: undefined,
      magnetic_field_T: undefined,
      measurement_point_label: undefined,
      excitation_wavelength_nm: undefined,
    });
  });
});
