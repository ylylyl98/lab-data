import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { listDevices } from '../api';
import { TypeBadge } from '../components/TypeBadge';
import type { Device } from '../types';

export function DevicesPage() {
  const [devices, setDevices] = useState<Device[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    listDevices()
      .then(setDevices)
      .catch(() => setError(true));
  }, []);

  return (
    <div className="page">
      <h1>Devices</h1>
      {error && <p className="error">Request failed</p>}
      {devices === null && !error && <p className="muted">Loading</p>}
      {devices && devices.length === 0 && <p className="muted">(empty)</p>}
      <ul className="result-list">
        {devices?.map((device) => (
          <li key={device.device_id}>
            <TypeBadge type="devices" />
            <Link className="id-link" to={`/devices/${device.device_id}`}>
              {device.device_id}
            </Link>
            <span className="muted">{device.display_label}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
