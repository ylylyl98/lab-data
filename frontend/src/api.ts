import type { Artifact, Device, Experiment, Preview } from './types';

function buildQuery(params: Record<string, string>): string {
  const query = new URLSearchParams(params).toString();
  return query ? `?${query}` : '';
}

async function request<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

export function listDevices(): Promise<Device[]> {
  return request<Device[]>('/devices');
}

export function searchDevices(deviceId: string): Promise<Device[]> {
  return request<Device[]>(`/devices${buildQuery({ device_id: deviceId })}`);
}

export function getDevice(deviceId: string): Promise<Device | undefined> {
  return searchDevices(deviceId).then((items) => items[0]);
}

export function listExperiments(): Promise<Experiment[]> {
  return request<Experiment[]>('/experiments');
}

export function searchExperiments(experimentId: string): Promise<Experiment[]> {
  return request<Experiment[]>(
    `/experiments${buildQuery({ experiment_id: experimentId })}`,
  );
}

export function getExperiment(
  experimentId: string,
): Promise<Experiment | undefined> {
  return searchExperiments(experimentId).then((items) => items[0]);
}

export function listArtifacts(): Promise<Artifact[]> {
  return request<Artifact[]>('/artifacts');
}

export function searchArtifacts(artifactId: string): Promise<Artifact[]> {
  return request<Artifact[]>(`/artifacts${buildQuery({ artifact_id: artifactId })}`);
}

export function getArtifact(artifactId: string): Promise<Artifact | undefined> {
  return searchArtifacts(artifactId).then((items) => items[0]);
}

export function getDeviceArtifacts(deviceId: string): Promise<Artifact[]> {
  return request<Artifact[]>(`/artifacts${buildQuery({ device_id: deviceId })}`);
}

export function getDeviceDocuments(deviceId: string): Promise<Artifact[]> {
  return request<Artifact[]>(`/devices/${deviceId}/documents`);
}

export function getDeviceExperiments(deviceId: string): Promise<Experiment[]> {
  return request<Experiment[]>(`/devices/${deviceId}/experiments`);
}

export function getExperimentArtifacts(
  experimentId: string,
): Promise<Artifact[]> {
  return request<Artifact[]>(
    `/artifacts${buildQuery({ experiment_id: experimentId })}`,
  );
}

export function getPreview(artifactId: string): Promise<Preview | null> {
  return request<Preview | null>(`/artifacts/${artifactId}/preview`);
}

export function assetUrl(artifactId: string, path: string): string {
  return `/artifacts/${artifactId}/preview/assets/${path}`;
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
