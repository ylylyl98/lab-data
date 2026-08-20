import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { getExperiment, getExperimentArtifacts } from '../api';
import { ArtifactResult } from '../components/ArtifactResult';
import { MetadataList } from '../components/MetadataList';
import { Pager } from '../components/Pager';
import { TypeBadge } from '../components/TypeBadge';
import { displayValue } from '../format';
import type {
  Artifact,
  Experiment,
  LineageEdge,
  Page,
} from '../types';

const LIMIT = 50;

const ROLE_LABELS: Record<string, string> = {
  raw: 'Raw data',
  processed: 'Processed data',
  figure: 'Figures',
  intermediate: 'Intermediate',
  artifact: 'Other',
};

const ROLE_ORDER = ['raw', 'processed', 'figure', 'intermediate', 'artifact'];

function basename(path: string): string {
  return path.split('/').filter(Boolean).pop() ?? path;
}

function lineageRows(
  lineage: LineageEdge[],
): { text: string; relation: string }[] {
  const bySource = new Map<string, LineageEdge>();
  for (const edge of lineage) {
    bySource.set(basename(edge.source), edge);
  }
  const keyFor = (edge: LineageEdge) => `${edge.source}\u0000${edge.target}`;
  const nextFor = (edge: LineageEdge) => bySource.get(basename(edge.target));
  const rows: { text: string; relation: string }[] = [];
  const emitted = new Set<string>();
  for (const edge of lineage) {
    const key = keyFor(edge);
    const next = nextFor(edge);
    if (emitted.has(key) || next === undefined || next === edge) {
      continue;
    }
    rows.push({
      text: [
        basename(edge.source),
        basename(edge.target),
        basename(next.target),
      ].join(' -> '),
      relation: edge.relation,
    });
    emitted.add(key);
    emitted.add(keyFor(next));
  }
  for (const edge of lineage) {
    const key = keyFor(edge);
    if (emitted.has(key)) {
      continue;
    }
    rows.push({
      text: `${basename(edge.source)} -> ${basename(edge.target)}`,
      relation: edge.relation,
    });
    emitted.add(key);
  }
  return rows;
}

function SciSummary({ experiment }: { experiment: Experiment }) {
  const metadata = experiment.metadata;
  const measuredOn = experiment.measured_on;
  return (
    <dl className="sci-summary">
      <div className="sci-summary-cell">
        <dt>Experiment ID</dt>
        <dd>{experiment.experiment_id}</dd>
      </div>
      <div className="sci-summary-cell">
        <dt>Device</dt>
        <dd>
          {measuredOn ? (
            <Link className="id-link" to={`/devices/${measuredOn.device_id}`}>
              {measuredOn.device_id}
            </Link>
          ) : (
            <span className="muted">not explicitly linked</span>
          )}
        </dd>
      </div>
      <div className="sci-summary-cell">
        <dt>Measurement type</dt>
        <dd>{displayValue(metadata.measurement_type)}</dd>
      </div>
      <div className="sci-summary-cell">
        <dt>Sample position</dt>
        <dd>{displayValue(metadata.measurement_point_label)}</dd>
      </div>
      <div className="sci-summary-cell">
        <dt>Temperature</dt>
        <dd>{displayValue(metadata.temperature_K)}</dd>
      </div>
      <div className="sci-summary-cell">
        <dt>Magnetic field</dt>
        <dd>{displayValue(metadata.magnetic_field_T)}</dd>
      </div>
      <div className="sci-summary-cell">
        <dt>Excitation wavelength</dt>
        <dd>{displayValue(metadata.excitation_wavelength_nm)}</dd>
      </div>
      <div className="sci-summary-cell">
        <dt>Review state</dt>
        <dd>
          {experiment.review_state}
          {experiment.needs_review && (
            <span className="review-flag">needs review</span>
          )}
        </dd>
      </div>
      <div className="sci-summary-cell">
        <dt>Confidence</dt>
        <dd>{displayValue(experiment.confidence)}</dd>
      </div>
    </dl>
  );
}

export function ExperimentDetailPage() {
  const { id = '' } = useParams();
  const [experiment, setExperiment] = useState<Experiment | null | undefined>(
    undefined,
  );
  const [experimentError, setExperimentError] = useState(false);

  const [artifacts, setArtifacts] = useState<Page<Artifact> | null>(null);
  const [offset, setOffset] = useState(0);
  const [artifactsError, setArtifactsError] = useState(false);

  useEffect(() => {
    let active = true;
    setExperiment(undefined);
    setExperimentError(false);
    getExperiment(id)
      .then((value) => {
        if (active) {
          setExperiment(value ?? null);
        }
      })
      .catch(() => {
        if (active) {
          setExperimentError(true);
        }
      });
    return () => {
      active = false;
    };
  }, [id]);

  useEffect(() => {
    let active = true;
    setArtifacts(null);
    setArtifactsError(false);
    getExperimentArtifacts(id, { limit: LIMIT, offset })
      .then((value) => {
        if (active) {
          setArtifacts(value);
        }
      })
      .catch(() => {
        if (active) {
          setArtifactsError(true);
        }
      });
    return () => {
      active = false;
    };
  }, [id, offset]);

  if (experimentError) {
    return <p className="error">Request failed</p>;
  }
  if (experiment === undefined) {
    return <p className="muted">Loading</p>;
  }
  if (experiment === null) {
    return <p className="muted">Experiment not found</p>;
  }

  const roles = ROLE_ORDER.filter(
    (role) => (experiment.files_by_role[role] ?? []).length > 0,
  );
  const unresolvedPaths = Array.isArray(
    experiment.metadata.unresolved_processed_files,
  )
    ? (experiment.metadata.unresolved_processed_files as string[])
    : [];
  const lineage = lineageRows(experiment.lineage);

  return (
    <div className="page">
      <div className="page-head">
        <TypeBadge type="experiments" />
        <h1>{experiment.experiment_id}</h1>
      </div>

      <section className="panel">
        <h2>Summary</h2>
        <SciSummary experiment={experiment} />
      </section>

      {experiment.measured_on && (
        <section className="panel">
          <h2>Device linkage</h2>
          <p>
            Measured on{' '}
            <Link
              className="id-link"
              to={`/devices/${experiment.measured_on.device_id}`}
            >
              {experiment.measured_on.device_id}
            </Link>
          </p>
          <p className="muted">Evidence: {experiment.measured_on.evidence}</p>
          <details className="provenance-details">
            <summary>Provenance details</summary>
            <dl className="kv-list">
              <div className="kv-row">
                <dt>Source reference</dt>
                <dd>{experiment.measured_on.source_reference}</dd>
              </div>
              <div className="kv-row">
                <dt>Extraction method</dt>
                <dd>{experiment.measured_on.extraction_method}</dd>
              </div>
              <div className="kv-row">
                <dt>Review status</dt>
                <dd>{experiment.measured_on.review_status}</dd>
              </div>
            </dl>
          </details>
        </section>
      )}

      <section className="panel">
        <h2>Files</h2>
        {roles.length === 0 && unresolvedPaths.length === 0 ? (
          <p className="muted">(empty)</p>
        ) : (
          <>
            {roles.map((role) => (
              <div className="role-group" key={role}>
                <h3>{ROLE_LABELS[role] ?? role}</h3>
                <ul className="file-list">
                  {experiment.files_by_role[role].map((path) => (
                    <li key={path}>{path}</li>
                  ))}
                </ul>
              </div>
            ))}
            {unresolvedPaths.length > 0 && (
              <div className="role-group">
                <h3>Unresolved or other</h3>
                <ul className="file-list">
                  {unresolvedPaths.map((path) => (
                    <li key={path}>{path}</li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </section>

      <section className="panel">
        <h2>Lineage</h2>
        {lineage.length === 0 ? (
          <p className="muted">(empty)</p>
        ) : (
          <ul className="link-list">
            {lineage.map((row, index) => (
              <li key={`${row.text}-${row.relation}-${index}`}>
                {row.text} ({row.relation})
              </li>
            ))}
          </ul>
        )}
      </section>

      {experiment.needs_review && (
        <section className="panel review-notice">
          <h2>Review needed</h2>
          <p className="muted">
            The deterministic parser could not confirm the measurement
            provenance for this experiment. It stays reviewable until a human
            decision is supplied.
          </p>
          {unresolvedPaths.length > 0 && (
            <div className="role-group">
              <h3>Unresolved processed files</h3>
              <ul className="file-list">
                {unresolvedPaths.map((path) => (
                  <li key={path}>{path}</li>
                ))}
              </ul>
            </div>
          )}
          {experiment.warnings.length > 0 && (
            <div className="role-group">
              <h3>Warnings</h3>
              <ul className="file-list">
                {experiment.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}

      {!experiment.needs_review && experiment.warnings.length > 0 && (
        <section className="panel">
          <h2>Warnings</h2>
          <ul className="link-list">
            {experiment.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </section>
      )}

      <section className="panel">
        <h2>Metadata</h2>
        <MetadataList metadata={experiment.metadata} />
      </section>

      <section className="panel">
        <h2>Artifacts</h2>
        {artifactsError ? (
          <p className="error">Request failed</p>
        ) : artifacts === null ? (
          <p className="muted">Loading</p>
        ) : artifacts.items.length === 0 ? (
          <p className="muted">(empty)</p>
        ) : (
          <>
            <p className="muted">{artifacts.total_count} total</p>
            {artifacts.items.map((artifact) => (
              <ArtifactResult
                key={artifact.artifact_id}
                artifact={artifact}
                showPreview
              />
            ))}
            <Pager
              offset={offset}
              limit={LIMIT}
              total={artifacts.total_count}
              onPageChange={setOffset}
            />
          </>
        )}
      </section>
    </div>
  );
}
