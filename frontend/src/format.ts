export function displayValue(value: unknown): string {
  if (value === null || value === undefined) {
    return 'null';
  }
  if (typeof value === 'string') {
    return value;
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value.length === 0 ? '(empty)' : JSON.stringify(value);
  }
  if (typeof value === 'object') {
    const text = JSON.stringify(value);
    return text === '{}' ? '(empty)' : text;
  }
  return String(value);
}
