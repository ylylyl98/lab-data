import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { listExperiments } from '../api';
import { TypeBadge } from '../components/TypeBadge';
import type { Experiment } from '../types';

export function ExperimentsPage() {
  const [experiments, setExperiments] = useState<Experiment[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    listExperiments()
      .then(setExperiments)
      .catch(() => setError(true));
  }, []);

  return (
    <div className="page">
      <h1>Experiments</h1>
      {error && <p className="error">Request failed</p>}
      {experiments === null && !error && <p className="muted">Loading</p>}
      {experiments && experiments.length === 0 && <p className="muted">(empty)</p>}
      <ul className="result-list">
        {experiments?.map((experiment) => (
          <li key={experiment.experiment_id}>
            <TypeBadge type="experiments" />
            <Link className="id-link" to={`/experiments/${experiment.experiment_id}`}>
              {experiment.experiment_id}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
