import type { EntityType } from '../types';

const LABELS: Record<EntityType, string> = {
  devices: 'Device',
  experiments: 'Experiment',
  artifacts: 'Artifact',
};

export function TypeBadge({ type }: { type: EntityType }) {
  return <span className={`type-badge type-badge--${type}`}>{LABELS[type]}</span>;
}
