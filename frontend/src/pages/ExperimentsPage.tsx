import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { listExperiments } from '../api';
import { Pager } from '../components/Pager';
import { TypeBadge } from '../components/TypeBadge';
import type { Experiment, Page } from '../types';

const LIMIT = 50;

const FILTER_PARAM_KEYS = [
  'measurement_type',
  'temperature_K',
  'magnetic_field_T',
  'measurement_point_label',
  'excitation_wavelength_nm',
] as const;

function paramValue(searchParams: URLSearchParams, key: string): string {
  const value = searchParams.get(key);
  return value === null ? '' : value;
}

function parseNumber(value: string): number | undefined {
  if (value === '') {
    return undefined;
  }
  const parsed = Number(value);
  return Number.isNaN(parsed) ? undefined : parsed;
}

export function ExperimentsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const q = searchParams.get('q') ?? '';

  const measurementType = paramValue(searchParams, 'measurement_type');
  const temperatureRaw = paramValue(searchParams, 'temperature_K');
  const magneticFieldRaw = paramValue(searchParams, 'magnetic_field_T');
  const positionLabel = paramValue(searchParams, 'measurement_point_label');
  const excitationRaw = paramValue(searchParams, 'excitation_wavelength_nm');

  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<Page<Experiment> | null>(null);
  const [error, setError] = useState(false);

  function setFilterParam(key: string, value: string) {
    const next = new URLSearchParams(searchParams);
    if (value === '') {
      next.delete(key);
    } else {
      next.set(key, value);
    }
    setSearchParams(next, { replace: true });
  }

  function resetFilters() {
    const next = new URLSearchParams(searchParams);
    for (const key of FILTER_PARAM_KEYS) {
      next.delete(key);
    }
    setSearchParams(next, { replace: true });
  }

  const activeFilterCount = FILTER_PARAM_KEYS.filter(
    (key) => searchParams.get(key) !== null,
  ).length;

  useEffect(() => {
    setOffset(0);
  }, [
    q,
    measurementType,
    temperatureRaw,
    magneticFieldRaw,
    positionLabel,
    excitationRaw,
  ]);

  useEffect(() => {
    let active = true;
    setPage(null);
    setError(false);
    listExperiments({
      q: q || undefined,
      limit: LIMIT,
      offset,
      measurement_type: measurementType || undefined,
      temperature_K: parseNumber(temperatureRaw),
      magnetic_field_T: parseNumber(magneticFieldRaw),
      measurement_point_label: positionLabel || undefined,
      excitation_wavelength_nm: parseNumber(excitationRaw),
    })
      .then((value) => {
        if (active) {
          setPage(value);
        }
      })
      .catch(() => {
        if (active) {
          setError(true);
        }
      });
    return () => {
      active = false;
    };
  }, [
    q,
    offset,
    measurementType,
    temperatureRaw,
    magneticFieldRaw,
    positionLabel,
    excitationRaw,
  ]);

  return (
    <div className="page">
      <h1>Experiments</h1>
      {q && <p className="muted">Search: {q}</p>}

      <section className="panel filter-panel">
        <div className="filter-panel-head">
          <h2>Filters</h2>
          <button
            type="button"
            className="reset-filters"
            onClick={resetFilters}
            disabled={activeFilterCount === 0}
          >
            Reset filters
          </button>
          {activeFilterCount > 0 && (
            <span className="muted">{activeFilterCount} active</span>
          )}
        </div>
        <div className="filter-row">
          <label>
            <span>Measurement type</span>
            <select
              value={measurementType}
              onChange={(event) =>
                setFilterParam('measurement_type', event.target.value)
              }
            >
              <option value="">Any</option>
              <option value="photoluminescence">photoluminescence</option>
              <option value="absorption">absorption</option>
            </select>
          </label>
          <label>
            <span>Temperature (K)</span>
            <input
              type="number"
              step="any"
              value={temperatureRaw}
              onChange={(event) =>
                setFilterParam('temperature_K', event.target.value)
              }
            />
          </label>
          <label>
            <span>Magnetic field (T)</span>
            <input
              type="number"
              step="any"
              value={magneticFieldRaw}
              onChange={(event) =>
                setFilterParam('magnetic_field_T', event.target.value)
              }
            />
          </label>
          <label>
            <span>Position / location</span>
            <input
              type="text"
              value={positionLabel}
              onChange={(event) =>
                setFilterParam('measurement_point_label', event.target.value)
              }
            />
          </label>
          <label>
            <span>Excitation wavelength (nm)</span>
            <input
              type="number"
              step="any"
              value={excitationRaw}
              onChange={(event) =>
                setFilterParam('excitation_wavelength_nm', event.target.value)
              }
            />
          </label>
        </div>
      </section>

      {error && <p className="error">Request failed</p>}
      {page === null && !error && <p className="muted">Loading</p>}
      {page && page.items.length === 0 && <p className="muted">No matches</p>}
      {page && page.total_count > 0 && (
        <>
          <p className="muted">{page.total_count} total</p>
          <ul className="result-list">
            {page.items.map((experiment) => (
              <li key={experiment.experiment_id}>
                <TypeBadge type="experiments" />
                <Link
                  className="id-link"
                  to={`/experiments/${experiment.experiment_id}`}
                >
                  {experiment.experiment_id}
                </Link>
              </li>
            ))}
          </ul>
          <Pager
            offset={offset}
            limit={LIMIT}
            total={page.total_count}
            onPageChange={setOffset}
          />
        </>
      )}
    </div>
  );
}
