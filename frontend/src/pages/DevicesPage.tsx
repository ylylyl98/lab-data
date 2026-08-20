import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { listDevices } from '../api';
import { Pager } from '../components/Pager';
import { TypeBadge } from '../components/TypeBadge';
import type { Device, Page } from '../types';

const LIMIT = 50;

export function DevicesPage() {
  const [searchParams] = useSearchParams();
  const q = searchParams.get('q') ?? '';
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<Page<Device> | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    setOffset(0);
  }, [q]);

  useEffect(() => {
    let active = true;
    setPage(null);
    setError(false);
    listDevices({ q: q || undefined, limit: LIMIT, offset })
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
      <h1>Devices</h1>
      {q && <p className="muted">Search: {q}</p>}
      {error && <p className="error">Request failed</p>}
      {page === null && !error && <p className="muted">Loading</p>}
      {page && page.items.length === 0 && <p className="muted">No matches</p>}
      {page && page.total_count > 0 && (
        <>
          <p className="muted">{page.total_count} total</p>
          <ul className="result-list">
            {page.items.map((device) => (
              <li key={device.device_id}>
                <TypeBadge type="devices" />
                <Link className="id-link" to={`/devices/${device.device_id}`}>
                  {device.display_label || device.device_id}
                </Link>
                <span className="muted">{device.device_id}</span>
              </li>
            ))}
          </ul>
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
