import { useEffect, useState } from 'react';
import { assetUrl, getPreview } from '../api';
import { artifactLabel } from '../format';
import type { Artifact, Preview, PreviewAsset } from '../types';

// Deterministic priority order for choosing the single asset shown in a
// thumbnail:
//   1. image: preview.kind === 'image' -> assets.find(kind === 'image') ?? assets[0]
//   2. table: preview.kind === 'table' -> assets.find(kind === 'plot' || path.endsWith('plot.svg'))
//   3. slide: preview.kind === 'slide' -> first asset whose path matches /^slides\/\d+\.svg$/
//   4. otherwise -> null
export function resolveThumbnailAsset(preview: Preview): PreviewAsset | null {
  if (preview.kind === 'image') {
    const image = preview.assets.find((item) => item.kind === 'image');
    return image ?? preview.assets[0] ?? null;
  }
  if (preview.kind === 'table') {
    return (
      preview.assets.find(
        (item) => item.kind === 'plot' || item.path.endsWith('plot.svg'),
      ) ?? null
    );
  }
  if (preview.kind === 'slide') {
    return (
      preview.assets.find((item) => /^slides\/\d+\.svg$/.test(item.path)) ?? null
    );
  }
  return null;
}

export default function PreviewThumbnail({ artifact }: { artifact: Artifact }) {
  const [asset, setAsset] = useState<PreviewAsset | null>(null);

  useEffect(() => {
    let active = true;
    getPreview(artifact.artifact_id)
      .then((preview) => {
        if (!active) {
          return;
        }
        setAsset(preview ? resolveThumbnailAsset(preview) : null);
      })
      .catch(() => {
        if (active) {
          setAsset(null);
        }
      });
    return () => {
      active = false;
    };
  }, [artifact.artifact_id]);

  if (asset) {
    return (
      <img
        className="thumb-image"
        loading="lazy"
        src={assetUrl(artifact.artifact_id, asset.path)}
        alt={artifactLabel(artifact)}
      />
    );
  }

  const extension = artifact.extension ? artifact.extension.toUpperCase() : '-';
  return <div className="thumb-placeholder">{extension}</div>;
}
