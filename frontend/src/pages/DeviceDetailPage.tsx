import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  getDevice,
  getDeviceArtifacts,
  getDeviceDocuments,
  getDeviceExperiments,
} from '../api';
import { ArtifactResult } from '../components/ArtifactResult';
import { MetadataList } from '../components/MetadataList';
import { TypeBadge } from '../components/TypeBadge';
import { displayValue } from '../format';
import type { Artifact, Device, Experiment } from '../types';

const FIELD_LABELS: { key: keyof Device; label: string }[] = [
  { key: 'device_id', label: 'Device ID' },
  { key: 'display_label', label: 'Display label' },
  { key: 'maker_namespace', label: 'Maker namespace' },
  { key: 'local_device_id', label: 'Local device ID' },
  { key: 'device_type', label: 'Device type' },
  { key: 'review_state', label: 'Review state' },
];

export function DeviceDetailPage() {
  const { id = '' } = useParams();
  const [device, setDevice] = useState<Device | null | undefined>(undefined);
  const [artifacts, setArtifacts] = useState<Artifact[] | null>(null);
  const [documents, setDocuments] = useState<Artifact[] | null>(null);
  const [experiments, setExperiments] = useState<Experiment[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let active = true;
    setDevice(undefined);
    setArtifacts(null);
    setDocuments(null);
    setExperiments(null);
    setError(false);
    Promise.all([
      getDevice(id),
      getDeviceArtifacts(id),
      getDeviceDocuments(id),
      getDeviceExperiments(id),
    ])
      .then(([deviceValue, artifactValue, documentValue, experimentValue]) => {
        if (!active) {
          return;
        }
        setDevice(deviceValue ?? null);
        setArtifacts(artifactValue);
        setDocuments(documentValue);
        setExperiments(experimentValue);
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
  if (device === undefined) {
    return <p className="muted">Loading</p>;
  }
  if (device === null) {
    return <p className="muted">Device not found</p>;
  }

  return (
    <div className="page">
      <div className="page-head">
        <TypeBadge type="devices" />
        <h1>{device.device_id}</h1>
      </div>
      <section className="panel">
        <dl className="kv-list">
          {FIELD_LABELS.map(({ key, label }) => (
            <div className="kv-row" key={key}>
              <dt>{label}</dt>
              <dd>{displayValue(device[key])}</dd>
            </div>
          ))}
          <div className="kv-row">
            <dt>Aliases</dt>
            <dd>{displayValue(device.aliases)}</dd>
          </div>
        </dl>
        <h2>Metadata</h2>
        <MetadataList metadata={device.metadata} />
      </section>

      <section className="panel">
        <h2>Artifacts</h2>
        {artifacts === null ? (
          <p className="muted">Loading</p>
        ) : artifacts.length === 0 ? (
          <p className="muted">(empty)</p>
        ) : (
          artifacts.map((artifact) => (
            <ArtifactResult key={artifact.artifact_id} artifact={artifact} />
          ))
        )}
      </section>

      <section className="panel">
        <h2>Documents</h2>
        {documents === null ? (
          <p className="muted">Loading</p>
        ) : documents.length === 0 ? (
          <p className="muted">(empty)</p>
        ) : (
          documents.map((artifact) => (
            <ArtifactResult key={artifact.artifact_id} artifact={artifact} />
          ))
        )}
      </section>

      <section className="panel">
        <h2>Experiments</h2>
        {experiments === null ? (
          <p className="muted">Loading</p>
        ) : experiments.length === 0 ? (
          <p className="muted">No explicit device experiments</p>
        ) : (
          experiments.map((experiment) => (
            <div className="kv-row" key={experiment.experiment_id}>
              <TypeBadge type="experiments" />
              <Link
                className="id-link"
                to={`/experiments/${experiment.experiment_id}`}
              >
                {experiment.experiment_id}
              </Link>
            </div>
          ))
        )}
      </section>
    </div>
  );
}
