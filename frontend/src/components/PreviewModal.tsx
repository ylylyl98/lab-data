import { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { X } from 'lucide-react';
import { artifactLabel } from '../format';
import type { Artifact } from '../types';
import { PreviewView } from './PreviewView';

export function PreviewModal({
  artifact,
  onClose,
}: {
  artifact: Artifact | null;
  onClose: () => void;
}) {
  useEffect(() => {
    if (!artifact) {
      return;
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        onClose();
      }
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [artifact, onClose]);

  if (!artifact) {
    return null;
  }

  return (
    <div
      className="modal-overlay"
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div className="modal-dialog" role="dialog" aria-modal="true">
        <div className="modal-head">
          <div>
            <h2>{artifactLabel(artifact)}</h2>
            <span className="muted">{artifact.artifact_id}</span>
          </div>
          <button
            type="button"
            className="modal-close"
            aria-label="Close preview"
            onClick={onClose}
          >
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        <PreviewView artifact={artifact} />
        <div className="modal-foot">
          <Link className="id-link" to={`/artifacts/${artifact.artifact_id}`}>
            Open detail
          </Link>
        </div>
      </div>
    </div>
  );
}
