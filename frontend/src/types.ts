export interface Device {
  device_id: string;
  display_label: string;
  maker_namespace: string | null;
  local_device_id: string | null;
  device_type: string;
  review_state: string;
  aliases: string[];
  metadata: Record<string, unknown>;
}

export interface LineageEdge {
  source: string;
  target: string;
  relation: string;
}

export interface Experiment {
  experiment_id: string;
  metadata: Record<string, unknown>;
  files_by_role: Record<string, string[]>;
  lineage: LineageEdge[];
  warnings: string[];
  confidence: number;
  needs_review: boolean;
}

export interface Artifact {
  artifact_id: string;
  device_id: string | null;
  experiment_id: string | null;
  role: string;
  category: string;
  extension: string;
  media_type: string;
  review_state: string;
  storage_source_id: string | null;
  relative_path: string | null;
  size_bytes: number | null;
  mtime_ns: number | null;
  metadata: Record<string, unknown>;
}

export interface PreviewAsset {
  path: string;
  kind: string;
  media_type: string;
  size_bytes: number;
  sha256: string;
}

export interface SearchMatch {
  query: string | null;
  matched: boolean | null;
  text_available: boolean;
}

export interface Preview {
  artifact_id: string;
  preview_id: string;
  status: string;
  kind: string;
  fresh: boolean;
  source_freshness_checked: boolean;
  assets: PreviewAsset[];
  warnings: string[];
  search_match: SearchMatch;
}

export type EntityType = 'devices' | 'experiments' | 'artifacts';
