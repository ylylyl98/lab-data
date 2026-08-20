import { useState } from 'react';
import { artifactLabel } from '../format';
import type { Artifact } from '../types';
import PreviewThumbnail from './PreviewThumbnail';
import { PreviewModal } from './PreviewModal';

export function ArtifactGallery({ artifacts }: { artifacts: Artifact[] }) {
  const [selected, setSelected] = useState<Artifact | null>(null);

  return (
    <>
      <div className="artifact-gallery">
        {artifacts.map((artifact) => (
          <div
            key={artifact.artifact_id}
            className="artifact-card"
            role="button"
            tabIndex={0}
            onClick={() => setSelected(artifact)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                setSelected(artifact);
              }
            }}
          >
            <PreviewThumbnail artifact={artifact} />
            <span className="artifact-card-label">{artifactLabel(artifact)}</span>
            <span className="artifact-card-id">{artifact.artifact_id}</span>
          </div>
        ))}
      </div>
      <PreviewModal artifact={selected} onClose={() => setSelected(null)} />
    </>
  );
}
