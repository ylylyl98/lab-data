import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { getExperiment, getExperimentArtifacts } from '../api';
import { ArtifactResult } from '../components/ArtifactResult';
import { MetadataList } from '../components/MetadataList';
import { TypeBadge } from '../components/TypeBadge';
import { displayValue } from '../format';
import type { Artifact, Experiment } from '../types';

export function ExperimentDetailPage() {
  const { id = '' } = useParams();
  const [experiment, setExperiment] = useState<Experiment | null | undefined>(
    undefined,
  );
  const [artifacts, setArtifacts] = useState<Artifact[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let active = true;
    setExperiment(undefined);
    setArtifacts(null);
    setError(false);
    Promise.all([getExperiment(id), getExperimentArtifacts(id)])
      .then(([experimentValue, artifactValue]) => {
        if (!active) {
          return;
        }
        setExperiment(experimentValue ?? null);
        setArtifacts(artifactValue);
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
  if (experiment === undefined) {
    return <p className="muted">Loading</p>;
  }
  if (experiment === null) {
    return <p className="muted">Experiment not found</p>;
  }

  const roles = Object.keys(experiment.files_by_role);

  return (
    <div className="page">
      <div className="page-head">
        <TypeBadge type="experiments" />
        <h1>{experiment.experiment_id}</h1>
      </div>
      <section className="panel">
        <dl className="kv-list">
          <div className="kv-row">
            <dt>Experiment ID</dt>
            <dd>{experiment.experiment_id}</dd>
          </div>
          <div className="kv-row">
            <dt>Confidence</dt>
            <dd>{displayValue(experiment.confidence)}</dd>
          </div>
          <div className="kv-row">
            <dt>Needs review</dt>
            <dd>{displayValue(experiment.needs_review)}</dd>
          </div>
        </dl>
        <h2>Metadata</h2>
        <MetadataList metadata={experiment.metadata} />
      </section>

      <section className="panel">
        <h2>Files by role</h2>
        {roles.length === 0 ? (
          <p className="muted">(empty)</p>
        ) : (
          roles.map((role) => (
            <div className="kv-row" key={role}>
              <dt>{role}</dt>
              <dd>
                {experiment.files_by_role[role].length === 0
                  ? '(empty)'
                  : experiment.files_by_role[role].map((path) => (
                      <div key={path}>{path}</div>
                    ))}
              </dd>
            </div>
          ))
        )}
      </section>

      <section className="panel">
        <h2>Lineage</h2>
        {experiment.lineage.length === 0 ? (
          <p className="muted">(empty)</p>
        ) : (
          <ul className="link-list">
            {experiment.lineage.map((edge, index) => (
              <li key={`${edge.source}-${edge.target}-${edge.relation}-${index}`}>
                {edge.source} {'->'} {edge.target} ({edge.relation})
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="panel">
        <h2>Warnings</h2>
        {experiment.warnings.length === 0 ? (
          <p className="muted">(empty)</p>
        ) : (
          <ul className="link-list">
            {experiment.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        )}
      </section>

      <section className="panel">
        <h2>Artifacts</h2>
        {artifacts === null ? (
          <p className="muted">Loading</p>
        ) : artifacts.length === 0 ? (
          <p className="muted">(empty)</p>
        ) : (
          artifacts.map((artifact) => (
            <ArtifactResult key={artifact.artifact_id} artifact={artifact} showPreview />
          ))
        )}
      </section>
    </div>
  );
}
