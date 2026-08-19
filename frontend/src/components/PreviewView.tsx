import { useEffect, useState } from 'react';
import {
  assetUrl,
  fetchAssetText,
  getPreview,
} from '../api';
import type { Artifact, Preview, PreviewAsset } from '../types';

interface TablePayload {
  delimiter: string;
  headers: string[];
  rows: string[][];
}

function findAsset(
  preview: Preview,
  predicate: (asset: PreviewAsset) => boolean,
): PreviewAsset | undefined {
  return preview.assets.find(predicate);
}

function ImageView({ artifactId, preview }: { artifactId: string; preview: Preview }) {
  const asset = findAsset(preview, (item) => item.kind === 'image') ?? preview.assets[0];
  if (!asset) {
    return <p className="muted">No image asset</p>;
  }
  return (
    <img
      className="preview-image"
      src={assetUrl(artifactId, asset.path)}
      alt={asset.path}
    />
  );
}

function TableView({ artifactId, preview }: { artifactId: string; preview: Preview }) {
  const plot = findAsset(
    preview,
    (item) => item.kind === 'plot' || item.path.endsWith('plot.svg'),
  );
  const table = findAsset(preview, (item) => item.path === 'table.json');
  const [payload, setPayload] = useState<TablePayload | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!table) {
      return;
    }
    let active = true;
    fetchAssetText(artifactId, table.path)
      .then((text) => {
        if (active) {
          setPayload(JSON.parse(text) as TablePayload);
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
  }, [artifactId, table?.path]);

  if (!plot && !table) {
    return <p className="muted">No preview available</p>;
  }

  return (
    <div className="preview-table">
      {plot && (
        <img
          className="preview-image"
          src={assetUrl(artifactId, plot.path)}
          alt={plot.path}
        />
      )}
      {error && <p className="error">Table data unavailable</p>}
      {payload && (
        <table className="data-table">
          <thead>
            <tr>
              {payload.headers.map((header, index) => (
                <th key={`${header}-${index}`}>{header}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {payload.rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {row.map((cell, cellIndex) => (
                  <td key={cellIndex}>{cell}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function SlideView({ artifactId, preview }: { artifactId: string; preview: Preview }) {
  const slides = preview.assets.filter((item) =>
    /^slides\/\d+\.svg$/.test(item.path),
  );
  const searchText = findAsset(preview, (item) => item.path === 'search_text.txt');
  const [text, setText] = useState<string | null>(null);

  useEffect(() => {
    if (!searchText) {
      return;
    }
    let active = true;
    fetchAssetText(artifactId, searchText.path)
      .then((value) => {
        if (active) {
          setText(value);
        }
      })
      .catch(() => {
        if (active) {
          setText(null);
        }
      });
    return () => {
      active = false;
    };
  }, [artifactId, searchText?.path]);

  if (slides.length === 0 && !searchText) {
    return <p className="muted">No preview available</p>;
  }

  return (
    <div className="preview-slides">
      <div className="slide-gallery">
        {slides.map((slide) => (
          <img
            key={slide.path}
            className="slide-thumb"
            src={assetUrl(artifactId, slide.path)}
            alt={slide.path}
          />
        ))}
      </div>
      {text && <pre className="slide-text">{text}</pre>}
    </div>
  );
}

export function PreviewView({ artifact }: { artifact: Artifact }) {
  const [preview, setPreview] = useState<Preview | null | undefined>(undefined);
  const [error, setError] = useState(false);

  useEffect(() => {
    let active = true;
    setPreview(undefined);
    setError(false);
    getPreview(artifact.artifact_id)
      .then((value) => {
        if (active) {
          setPreview(value);
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
  }, [artifact.artifact_id]);

  if (error) {
    return <p className="error">Preview request failed</p>;
  }
  if (preview === undefined) {
    return <p className="muted">Loading</p>;
  }
  if (preview === null) {
    return <p className="muted">No preview available</p>;
  }
  if (preview.status !== 'ready') {
    return (
      <div className="preview-status">
        <p>Status: {preview.status}</p>
        {preview.warnings.length > 0 && (
          <ul>
            {preview.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        )}
      </div>
    );
  }
  if (preview.kind === 'image') {
    return <ImageView artifactId={artifact.artifact_id} preview={preview} />;
  }
  if (preview.kind === 'table') {
    return <TableView artifactId={artifact.artifact_id} preview={preview} />;
  }
  if (preview.kind === 'slide') {
    return <SlideView artifactId={artifact.artifact_id} preview={preview} />;
  }
  const placeholder = preview.assets[0];
  return placeholder ? (
    <img
      className="preview-image"
      src={assetUrl(artifact.artifact_id, placeholder.path)}
      alt={placeholder.path}
    />
  ) : (
    <p className="muted">No preview available</p>
  );
}
