import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { getArtifact } from '../api';
import { MetadataList } from '../components/MetadataList';
import { PreviewView } from '../components/PreviewView';
import { TypeBadge } from '../components/TypeBadge';
import { artifactLabel, displayValue } from '../format';
import type { Artifact } from '../types';

export function ArtifactDetailPage() {
  const { id = '' } = useParams();
  const [artifact, setArtifact] = useState<Artifact | null | undefined>(undefined);
  const [error, setError] = useState(false);

  useEffect(() => {
    let active = true;
    setArtifact(undefined);
    setError(false);
    getArtifact(id)
      .then((value) => {
        if (active) {
          setArtifact(value ?? null);
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
  }, [id]);

  if (error) {
    return <p className="error">Request failed</p>;
  }
  if (artifact === undefined) {
    return <p className="muted">Loading</p>;
  }
  if (artifact === null) {
    return <p className="muted">Artifact not found</p>;
  }

  return (
    <div className="page">
      <div className="page-head">
        <TypeBadge type="artifacts" />
        <h1>{artifactLabel(artifact)}</h1>
      </div>

      <section className="panel">
        <div className="panel-meta">
          <span>{artifact.role}</span>
          <span>{artifact.category}</span>
          <span>{artifact.extension}</span>
          <span>{artifact.review_state}</span>
        </div>
        {artifact.derived_from.length > 0 && (
          <div className="role-group">
            <h2>Derived</h2>
            <ul className="link-list">
              {artifact.derived_from.map((edge, index) => (
                <li key={`${edge.source}-${edge.target}-${index}`}>
                  {edge.source} {'->'} {edge.target} ({edge.relation})
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <section className="panel">
        <h2>Preview</h2>
        <PreviewView artifact={artifact} />
      </section>

      <section className="panel">
        <h2>Location</h2>
        <dl className="kv-list">
          <div className="kv-row">
            <dt>Relative path</dt>
            <dd>{artifact.relative_path ?? 'null'}</dd>
          </div>
          <div className="kv-row">
            <dt>Storage source</dt>
            <dd>{artifact.storage_source_id ?? 'null'}</dd>
          </div>
          <div className="kv-row">
            <dt>Device</dt>
            <dd>
              {artifact.device_id ? (
                <Link
                  className="id-link"
                  to={`/devices/${artifact.device_id}`}
                >
                  {artifact.device_id}
                </Link>
              ) : (
                <span className="muted">not linked</span>
              )}
            </dd>
          </div>
          <div className="kv-row">
            <dt>Experiment</dt>
            <dd>
              {artifact.experiment_id ? (
                <Link
                  className="id-link"
                  to={`/experiments/${artifact.experiment_id}`}
                >
                  {artifact.experiment_id}
                </Link>
              ) : (
                <span className="muted">not linked</span>
              )}
            </dd>
          </div>
          <div className="kv-row">
            <dt>Review state</dt>
            <dd>{artifact.review_state}</dd>
          </div>
        </dl>
      </section>

      <section className="panel">
        <h2>Metadata</h2>
        <MetadataList metadata={artifact.metadata} />
      </section>

      <section className="panel">
        <h2>Details</h2>
        <dl className="kv-list">
          <div className="kv-row">
            <dt>Artifact ID</dt>
            <dd className="muted">{artifact.artifact_id}</dd>
          </div>
          <div className="kv-row">
            <dt>Size (bytes)</dt>
            <dd>{displayValue(artifact.size_bytes)}</dd>
          </div>
          <div className="kv-row">
            <dt>Modified (ns)</dt>
            <dd>{displayValue(artifact.mtime_ns)}</dd>
          </div>
        </dl>
      </section>
    </div>
  );
}
