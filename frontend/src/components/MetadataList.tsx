import { displayValue } from '../format';

export function MetadataList({ metadata }: { metadata: Record<string, unknown> }) {
  const entries = Object.entries(metadata);
  if (entries.length === 0) {
    return <p className="muted">(empty)</p>;
  }
  return (
    <dl className="kv-list">
      {entries.map(([key, value]) => (
        <div className="kv-row" key={key}>
          <dt>{key}</dt>
          <dd>{displayValue(value)}</dd>
        </div>
      ))}
    </dl>
  );
}
