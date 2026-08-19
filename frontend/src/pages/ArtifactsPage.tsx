import { useEffect, useState } from 'react';
import { listArtifacts } from '../api';
import { ArtifactResult } from '../components/ArtifactResult';
import type { Artifact } from '../types';

export function ArtifactsPage() {
  const [artifacts, setArtifacts] = useState<Artifact[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    listArtifacts()
      .then(setArtifacts)
      .catch(() => setError(true));
  }, []);

  return (
    <div className="page">
      <h1>Artifacts</h1>
      {error && <p className="error">Request failed</p>}
      {artifacts === null && !error && <p className="muted">Loading</p>}
      {artifacts && artifacts.length === 0 && <p className="muted">(empty)</p>}
      {artifacts?.map((artifact) => (
        <ArtifactResult key={artifact.artifact_id} artifact={artifact} />
      ))}
    </div>
  );
}
