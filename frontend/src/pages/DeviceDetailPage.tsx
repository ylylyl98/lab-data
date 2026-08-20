import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { getDevice, getDeviceArtifacts, getDeviceExperiments } from '../api';
import { ArtifactGallery } from '../components/ArtifactGallery';
import { ArtifactResult } from '../components/ArtifactResult';
import { MetadataList } from '../components/MetadataList';
import { Pager } from '../components/Pager';
import { TypeBadge } from '../components/TypeBadge';
import { displayValue } from '../format';
import type {
  Artifact,
  ArtifactKind,
  Device,
  Experiment,
  Page,
} from '../types';

const LIMIT = 50;
// Cap artifact-kind tabs at 24 to bound preview-manifest and thumbnail asset
// requests per tab while still showing a useful gallery page.
const GALLERY_LIMIT = 24;

const FIELD_LABELS: { key: keyof Device; label: string }[] = [
  { key: 'device_id', label: 'Device ID' },
  { key: 'display_label', label: 'Display label' },
  { key: 'maker_namespace', label: 'Maker namespace' },
  { key: 'local_device_id', label: 'Local device ID' },
  { key: 'device_type', label: 'Device type' },
  { key: 'review_state', label: 'Review state' },
];

const ARTIFACT_KINDS: { kind: ArtifactKind; label: string }[] = [
  { kind: 'document', label: 'Documents' },
  { kind: 'image', label: 'Images' },
  { kind: 'data', label: 'Data' },
  { kind: 'other', label: 'Other' },
];

export function DeviceDetailPage() {
  const { id = '' } = useParams();
  const [device, setDevice] = useState<Device | null | undefined>(undefined);
  const [deviceError, setDeviceError] = useState(false);

  const [activeKind, setActiveKind] = useState<ArtifactKind>('document');
  const [artifacts, setArtifacts] = useState<Page<Artifact> | null>(null);
  const [artifactOffset, setArtifactOffset] = useState(0);
  const [artifactsError, setArtifactsError] = useState(false);

  const [experiments, setExperiments] = useState<Page<Experiment> | null>(null);
  const [experimentOffset, setExperimentOffset] = useState(0);
  const [experimentsError, setExperimentsError] = useState(false);

  useEffect(() => {
    let active = true;
    setDevice(undefined);
    setDeviceError(false);
    getDevice(id)
      .then((value) => {
        if (active) {
          setDevice(value ?? null);
        }
      })
      .catch(() => {
        if (active) {
          setDeviceError(true);
        }
      });
    return () => {
      active = false;
    };
  }, [id]);

  useEffect(() => {
    let active = true;
    setArtifacts(null);
    setArtifactsError(false);
    getDeviceArtifacts(id, {
      kind: activeKind,
      limit: GALLERY_LIMIT,
      offset: artifactOffset,
    })
      .then((value) => {
        if (active) {
          setArtifacts(value);
        }
      })
      .catch(() => {
        if (active) {
          setArtifactsError(true);
        }
      });
    return () => {
      active = false;
    };
  }, [id, activeKind, artifactOffset]);

  useEffect(() => {
    let active = true;
    setExperiments(null);
    setExperimentsError(false);
    getDeviceExperiments(id, { limit: LIMIT, offset: experimentOffset })
      .then((value) => {
        if (active) {
          setExperiments(value);
        }
      })
      .catch(() => {
        if (active) {
          setExperimentsError(true);
        }
      });
    return () => {
      active = false;
    };
  }, [id, experimentOffset]);

  function selectKind(kind: ArtifactKind) {
    setActiveKind(kind);
    setArtifactOffset(0);
  }

  if (deviceError) {
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
        <div className="tabs" role="tablist" aria-label="Artifact kinds">
          {ARTIFACT_KINDS.map(({ kind, label }) => (
            <button
              key={kind}
              type="button"
              role="tab"
              aria-selected={activeKind === kind}
              className={activeKind === kind ? 'tab active' : 'tab'}
              onClick={() => selectKind(kind)}
            >
              {label}
            </button>
          ))}
        </div>
        {artifactsError ? (
          <p className="error">Request failed</p>
        ) : artifacts === null ? (
          <p className="muted">Loading</p>
        ) : artifacts.items.length === 0 ? (
          <p className="muted">(empty)</p>
        ) : (
          <>
            <p className="muted">{artifacts.total_count} total</p>
            {activeKind === 'other' ? (
              artifacts.items.map((artifact) => (
                <ArtifactResult key={artifact.artifact_id} artifact={artifact} />
              ))
            ) : (
              <ArtifactGallery artifacts={artifacts.items} />
            )}
            <Pager
              offset={artifactOffset}
              limit={GALLERY_LIMIT}
              total={artifacts.total_count}
              onPageChange={setArtifactOffset}
            />
          </>
        )}
      </section>

      <section className="panel">
        <h2>Experiments</h2>
        {experimentsError ? (
          <p className="error">Request failed</p>
        ) : experiments === null ? (
          <p className="muted">Loading</p>
        ) : experiments.items.length === 0 ? (
          <p className="muted">No explicit device experiments</p>
        ) : (
          <>
            <p className="muted">{experiments.total_count} total</p>
            <ul className="result-list">
              {experiments.items.map((experiment) => (
                <li key={experiment.experiment_id}>
                  <TypeBadge type="experiments" />
                  <Link
                    className="id-link"
                    to={`/experiments/${experiment.experiment_id}`}
                  >
                    {experiment.experiment_id}
                  </Link>
                </li>
              ))}
            </ul>
            <Pager
              offset={experimentOffset}
              limit={LIMIT}
              total={experiments.total_count}
              onPageChange={setExperimentOffset}
            />
          </>
        )}
      </section>
    </div>
  );
}
