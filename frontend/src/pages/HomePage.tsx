import { Search } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  listArtifacts,
  listDevices,
  listExperiments,
  searchArtifacts,
  searchDevices,
  searchExperiments,
} from '../api';
import { TypeBadge } from '../components/TypeBadge';
import type { Artifact, Device, EntityType, Experiment } from '../types';

const ENTITIES: EntityType[] = ['devices', 'experiments', 'artifacts'];

type Result =
  | { type: 'devices'; item: Device }
  | { type: 'experiments'; item: Experiment }
  | { type: 'artifacts'; item: Artifact };

function resultLink(result: Result): string {
  if (result.type === 'devices') {
    return `/devices/${result.item.device_id}`;
  }
  if (result.type === 'experiments') {
    return `/experiments/${result.item.experiment_id}`;
  }
  return `/artifacts/${result.item.artifact_id}`;
}

function resultLabel(result: Result): string {
  if (result.type === 'devices') {
    return result.item.device_id;
  }
  if (result.type === 'experiments') {
    return result.item.experiment_id;
  }
  return result.item.artifact_id;
}

export function HomePage() {
  const [entity, setEntity] = useState<EntityType>('devices');
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Result[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  const [devices, setDevices] = useState<Device[]>([]);
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);

  useEffect(() => {
    listDevices().then(setDevices).catch(() => setDevices([]));
    listExperiments().then(setExperiments).catch(() => setExperiments([]));
    listArtifacts().then(setArtifacts).catch(() => setArtifacts([]));
  }, []);

  function runSearch() {
    const trimmed = query.trim();
    if (!trimmed) {
      return;
    }
    setLoading(true);
    setError(false);
    const request =
      entity === 'devices'
        ? searchDevices(trimmed).then(
            (items): Result[] =>
              items.map((item) => ({ type: 'devices' as const, item })),
          )
        : entity === 'experiments'
          ? searchExperiments(trimmed).then(
              (items): Result[] =>
                items.map((item) => ({ type: 'experiments' as const, item })),
            )
          : searchArtifacts(trimmed).then(
              (items): Result[] =>
                items.map((item) => ({ type: 'artifacts' as const, item })),
            );
    request
      .then(setResults)
      .catch(() => setError(true))
      .finally(() => setLoading(false));
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
          <div className="segmented" role="tablist" aria-label="Entity type">
            {ENTITIES.map((value) => (
              <button
                key={value}
                type="button"
                role="tab"
                aria-selected={entity === value}
                className={entity === value ? 'segment active' : 'segment'}
                onClick={() => setEntity(value)}
              >
                {value[0].toUpperCase() + value.slice(1)}
              </button>
            ))}
          </div>
          <div className="search-row">
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="ID"
              aria-label="Search ID"
            />
            <button type="submit" className="icon-button" aria-label="Search">
              <Search size={16} />
            </button>
          </div>
        </form>
        {loading && <p className="muted">Loading</p>}
        {error && <p className="error">Search failed</p>}
        {results && results.length === 0 && <p className="muted">No matches</p>}
        {results && results.length > 0 && (
          <ul className="result-list">
            {results.map((result) => (
              <li key={resultLink(result)}>
                <TypeBadge type={result.type} />
                <Link className="id-link" to={resultLink(result)}>
                  {resultLabel(result)}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="browse">
        <BrowseColumn
          title="Devices"
          items={devices.map((item) => ({
            id: item.device_id,
            to: `/devices/${item.device_id}`,
          }))}
        />
        <BrowseColumn
          title="Experiments"
          items={experiments.map((item) => ({
            id: item.experiment_id,
            to: `/experiments/${item.experiment_id}`,
          }))}
        />
        <BrowseColumn
          title="Artifacts"
          items={artifacts.map((item) => ({
            id: item.artifact_id,
            to: `/artifacts/${item.artifact_id}`,
          }))}
        />
      </section>
    </div>
  );
}

function BrowseColumn({
  title,
  items,
}: {
  title: string;
  items: { id: string; to: string }[];
}) {
  return (
    <div className="panel">
      <h2>{title}</h2>
      {items.length === 0 ? (
        <p className="muted">(empty)</p>
      ) : (
        <ul className="link-list">
          {items.map((item) => (
            <li key={item.id}>
              <Link className="id-link" to={item.to}>
                {item.id}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
