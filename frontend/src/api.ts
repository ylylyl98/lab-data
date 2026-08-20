import type {
  Artifact,
  ArtifactKind,
  Device,
  Experiment,
  ExperimentFilterParams,
  ListParams,
  Page,
  Preview,
  Summary,
} from './types';

const DEFAULT_PAGE_SIZE = 50;
const API_BASE = '/api';

type QueryValue = string | number | undefined;

function buildQuery(params: Record<string, QueryValue>): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === '' || Number.isNaN(value)) {
      continue;
    }
    query.set(key, String(value));
  }
  const text = query.toString();
  return text ? `?${text}` : '';
}

async function request<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

export function listDevices(
  params: ListParams & { device_id?: string } = {},
): Promise<Page<Device>> {
  return request<Page<Device>>(
    `/devices${buildQuery({
      q: params.q,
      limit: params.limit ?? DEFAULT_PAGE_SIZE,
      offset: params.offset,
      device_id: params.device_id,
    })}`,
  );
}

export function listExperiments(
  params: ListParams & { experiment_id?: string } & ExperimentFilterParams = {},
): Promise<Page<Experiment>> {
  return request<Page<Experiment>>(
    `/experiments${buildQuery({
      q: params.q,
      limit: params.limit ?? DEFAULT_PAGE_SIZE,
      offset: params.offset,
      experiment_id: params.experiment_id,
      measurement_type: params.measurement_type,
      temperature_K: params.temperature_K,
      magnetic_field_T: params.magnetic_field_T,
      measurement_point_label: params.measurement_point_label,
      excitation_wavelength_nm: params.excitation_wavelength_nm,
    })}`,
  );
}

export function listArtifacts(
  params: ListParams & {
    artifact_id?: string;
    device_id?: string;
    experiment_id?: string;
    kind?: ArtifactKind;
  } = {},
): Promise<Page<Artifact>> {
  return request<Page<Artifact>>(
    `/artifacts${buildQuery({
      q: params.q,
      limit: params.limit ?? DEFAULT_PAGE_SIZE,
      offset: params.offset,
      artifact_id: params.artifact_id,
      device_id: params.device_id,
      experiment_id: params.experiment_id,
      kind: params.kind,
    })}`,
  );
}

export function getSummary(): Promise<Summary> {
  return request<Summary>('/summary');
}

export function searchDevices(
  q: string,
  params: ListParams = {},
): Promise<Page<Device>> {
  return listDevices({ q, ...params });
}

export function searchExperiments(
  q: string,
  params: ListParams & ExperimentFilterParams = {},
): Promise<Page<Experiment>> {
  return listExperiments({ q, ...params });
}

export function searchArtifacts(
  q: string,
  params: ListParams = {},
): Promise<Page<Artifact>> {
  return listArtifacts({ q, ...params });
}

export function getDevice(deviceId: string): Promise<Device | undefined> {
  return listDevices({ device_id: deviceId }).then((page) => page.items[0]);
}

export function getExperiment(
  experimentId: string,
): Promise<Experiment | undefined> {
  return listExperiments({ experiment_id: experimentId }).then(
    (page) => page.items[0],
  );
}

export function getArtifact(artifactId: string): Promise<Artifact | undefined> {
  return listArtifacts({ artifact_id: artifactId }).then(
    (page) => page.items[0],
  );
}

export function getDeviceArtifacts(
  deviceId: string,
  params: {
    kind?: ArtifactKind;
    q?: string;
    limit?: number;
    offset?: number;
  } = {},
): Promise<Page<Artifact>> {
  return listArtifacts({ device_id: deviceId, ...params });
}

export function getDeviceDocuments(
  deviceId: string,
  params: { q?: string; limit?: number; offset?: number } = {},
): Promise<Page<Artifact>> {
  return request<Page<Artifact>>(
    `/devices/${deviceId}/documents${buildQuery({
      q: params.q,
      limit: params.limit ?? DEFAULT_PAGE_SIZE,
      offset: params.offset,
    })}`,
  );
}

export function getDeviceExperiments(
  deviceId: string,
  params: { q?: string; limit?: number; offset?: number } = {},
): Promise<Page<Experiment>> {
  return request<Page<Experiment>>(
    `/devices/${deviceId}/experiments${buildQuery({
      q: params.q,
      limit: params.limit ?? DEFAULT_PAGE_SIZE,
      offset: params.offset,
    })}`,
  );
}

export function getExperimentArtifacts(
  experimentId: string,
  params: { q?: string; limit?: number; offset?: number } = {},
): Promise<Page<Artifact>> {
  return listArtifacts({ experiment_id: experimentId, ...params });
}

export function getPreview(artifactId: string): Promise<Preview | null> {
  return request<Preview | null>(`/artifacts/${artifactId}/preview`);
}

export function assetUrl(artifactId: string, path: string): string {
  return `${API_BASE}/artifacts/${artifactId}/preview/assets/${path}`;
}

export async function fetchAssetText(
  artifactId: string,
  path: string,
): Promise<string> {
  const response = await fetch(assetUrl(artifactId, path));
  if (!response.ok) {
    throw new Error(`Asset request failed: ${response.status}`);
  }
  return response.text();
}
