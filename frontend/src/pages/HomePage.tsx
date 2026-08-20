import { Search } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  getSummary,
  searchArtifacts,
  searchDevices,
  searchExperiments,
} from '../api';
import { TypeBadge } from '../components/TypeBadge';
import { artifactLabel } from '../format';
import type {
  Artifact,
  Device,
  EntityType,
  Experiment,
  Page,
  Summary,
} from '../types';

interface SearchResults {
  q: string;
  devices: Page<Device>;
  experiments: Page<Experiment>;
  artifacts: Page<Artifact>;
}

export function HomePage() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [summaryError, setSummaryError] = useState(false);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResults | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    let active = true;
    getSummary()
      .then((value) => {
        if (active) {
          setSummary(value);
        }
      })
      .catch(() => {
        if (active) {
          setSummaryError(true);
        }
      });
    return () => {
      active = false;
    };
  }, []);

  function runSearch() {
    const trimmed = query.trim();
    if (!trimmed) {
      return;
    }
    setLoading(true);
    setError(false);
    Promise.all([
      searchDevices(trimmed),
      searchExperiments(trimmed),
      searchArtifacts(trimmed),
    ])
      .then(([devices, experiments, artifacts]) => {
        setResults({ q: trimmed, devices, experiments, artifacts });
      })
      .catch(() => {
        setError(true);
      })
      .finally(() => {
        setLoading(false);
      });
  }

  return (
    <div className="page">
      <section className="search-panel">
        <form
          className="search-form"
          onSubmit={(event) => {
            event.preventDefault();
            runSearch();
          }}
        >
          <div className="search-row">
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search devices, experiments, and artifacts"
              aria-label="Search query"
            />
            <button type="submit" className="icon-button" aria-label="Search">
              <Search size={16} />
            </button>
          </div>
        </form>
        {loading && <p className="muted">Loading</p>}
        {error && <p className="error">Search failed</p>}
      </section>

      <section className="browse">
        <Link className="summary-card" to="/devices">
          <span className="summary-card-title">Devices</span>
          <span className="summary-card-count">
            {summary ? summary.devices : '...'}
          </span>
        </Link>
        <Link className="summary-card" to="/experiments">
          <span className="summary-card-title">Experiments</span>
          <span className="summary-card-count">
            {summary ? summary.experiments : '...'}
          </span>
        </Link>
        <Link className="summary-card" to="/artifacts">
          <span className="summary-card-title">Artifacts</span>
          <span className="summary-card-count">
            {summary ? summary.artifacts : '...'}
          </span>
        </Link>
      </section>

      {summaryError && <p className="error">Summary unavailable</p>}

      {results && (
        <section className="search-results">
          <ResultGroup
            type="devices"
            title="Devices"
            page={results.devices}
            viewAllTo={`/devices?q=${encodeURIComponent(results.q)}`}
            itemTo={(item) => `/devices/${item.device_id}`}
            itemLabel={(item) => item.display_label || item.device_id}
          />
          <ResultGroup
            type="experiments"
            title="Experiments"
            page={results.experiments}
            viewAllTo={`/experiments?q=${encodeURIComponent(results.q)}`}
            itemTo={(item) => `/experiments/${item.experiment_id}`}
            itemLabel={(item) => item.experiment_id}
          />
          <ResultGroup
            type="artifacts"
            title="Artifacts"
            page={results.artifacts}
            viewAllTo={`/artifacts?q=${encodeURIComponent(results.q)}`}
            itemTo={(item) => `/artifacts/${item.artifact_id}`}
            itemLabel={artifactLabel}
          />
        </section>
      )}
    </div>
  );
}

function ResultGroup<T>({
  type,
  title,
  page,
  viewAllTo,
  itemTo,
  itemLabel,
}: {
  type: EntityType;
  title: string;
  page: Page<T>;
  viewAllTo: string;
  itemTo: (item: T) => string;
  itemLabel: (item: T) => string;
}) {
  return (
    <section className="panel">
      <div className="panel-head">
        <TypeBadge type={type} />
        <h2>{title}</h2>
        <span className="muted">{page.total_count}</span>
      </div>
      {page.items.length === 0 ? (
        <p className="muted">No matches</p>
      ) : (
        <ul className="result-list">
          {page.items.map((item) => (
            <li key={itemTo(item)}>
              <TypeBadge type={type} />
              <Link className="id-link" to={itemTo(item)}>
                {itemLabel(item)}
              </Link>
            </li>
          ))}
        </ul>
      )}
      <Link className="view-all" to={viewAllTo}>
        View all
      </Link>
    </section>
  );
}
