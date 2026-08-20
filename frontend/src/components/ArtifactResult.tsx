import { Link } from 'react-router-dom';
import { artifactLabel } from '../format';
import type { Artifact } from '../types';
import { PreviewView } from './PreviewView';
import { TypeBadge } from './TypeBadge';

export function ArtifactResult({
  artifact,
  showPreview = false,
}: {
  artifact: Artifact;
  showPreview?: boolean;
}) {
  return (
    <article className="panel">
      <div className="panel-head">
        <TypeBadge type="artifacts" />
        <Link
          className="id-link"
          to={`/artifacts/${artifact.artifact_id}`}
          title={artifact.relative_path ?? artifact.artifact_id}
        >
          {artifactLabel(artifact)}
        </Link>
        <span className="muted">{artifact.artifact_id}</span>
      </div>
      <div className="panel-meta">
        <span>{artifact.role}</span>
        <span>{artifact.category}</span>
        <span>{artifact.extension}</span>
        <span>{artifact.review_state}</span>
      </div>
      {showPreview && <PreviewView artifact={artifact} />}
    </article>
  );
}
