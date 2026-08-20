import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { listArtifacts } from '../api';
import { ArtifactResult } from '../components/ArtifactResult';
import { Pager } from '../components/Pager';
import type { Artifact, Page } from '../types';

const LIMIT = 50;

export function ArtifactsPage() {
  const [searchParams] = useSearchParams();
  const q = searchParams.get('q') ?? '';
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<Page<Artifact> | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    setOffset(0);
  }, [q]);

  useEffect(() => {
    let active = true;
    setPage(null);
    setError(false);
    listArtifacts({ q: q || undefined, limit: LIMIT, offset })
      .then((value) => {
        if (active) {
          setPage(value);
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
  }, [q, offset]);

  return (
    <div className="page">
      <h1>Artifacts</h1>
      {q && <p className="muted">Search: {q}</p>}
      {error && <p className="error">Request failed</p>}
      {page === null && !error && <p className="muted">Loading</p>}
      {page && page.items.length === 0 && <p className="muted">No matches</p>}
      {page && page.total_count > 0 && (
        <>
          <p className="muted">{page.total_count} total</p>
          {page.items.map((artifact) => (
            <ArtifactResult key={artifact.artifact_id} artifact={artifact} />
          ))}
          <Pager
            offset={offset}
            limit={LIMIT}
            total={page.total_count}
            onPageChange={setOffset}
          />
        </>
      )}
    </div>
  );
}
