import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { getArtifact } from '../api';
import { MetadataList } from '../components/MetadataList';
import { PreviewView } from '../components/PreviewView';
import { TypeBadge } from '../components/TypeBadge';
import { displayValue } from '../format';
import type { Artifact } from '../types';

const FIELD_LABELS: { key: keyof Artifact; label: string }[] = [
  { key: 'artifact_id', label: 'Artifact ID' },
  { key: 'device_id', label: 'Device ID' },
  { key: 'experiment_id', label: 'Experiment ID' },
  { key: 'role', label: 'Role' },
  { key: 'category', label: 'Category' },
  { key: 'extension', label: 'Extension' },
  { key: 'media_type', label: 'Media type' },
  { key: 'review_state', label: 'Review state' },
  { key: 'storage_source_id', label: 'Storage source ID' },
  { key: 'relative_path', label: 'Relative path' },
  { key: 'size_bytes', label: 'Size bytes' },
  { key: 'mtime_ns', label: 'Mtime (ns)' },
];

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
        <h1>{artifact.artifact_id}</h1>
      </div>
      <section className="panel">
        <dl className="kv-list">
          {FIELD_LABELS.map(({ key, label }) => (
            <div className="kv-row" key={key}>
              <dt>{label}</dt>
              <dd>
                {key === 'device_id' && artifact.device_id ? (
                  <Link className="id-link" to={`/devices/${artifact.device_id}`}>
                    {artifact.device_id}
                  </Link>
                ) : key === 'experiment_id' && artifact.experiment_id ? (
                  <Link
                    className="id-link"
                    to={`/experiments/${artifact.experiment_id}`}
                  >
                    {artifact.experiment_id}
                  </Link>
                ) : (
                  displayValue(artifact[key])
                )}
              </dd>
            </div>
          ))}
        </dl>
        <h2>Metadata</h2>
        <MetadataList metadata={artifact.metadata} />
      </section>
      <section className="panel">
        <h2>Preview</h2>
        <PreviewView artifact={artifact} />
      </section>
    </div>
  );
}
