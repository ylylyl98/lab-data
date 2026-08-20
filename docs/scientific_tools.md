# Scientific Tool Layer

`lab_data.scientific_tools.ScientificToolLayer` is a provider-neutral,
deterministic, read-only facade over the existing catalog retrieval
contracts.  It exists so a future MCP adapter or AI client can call the
scientific search logic without duplicating it.  Canonical truth stays in the
catalog layer; the tool layer performs no inference, no natural-language
interpretation, and no external AI calls.

Every tool is bounded (limits are validated to `1..200`), JSON-safe (no
absolute paths, plain dict/list output), and model-independent.

## Construction

```python
from lab_data.scientific_tools import ScientificToolLayer

layer = ScientificToolLayer.from_catalog(
    r"C:\NOMAD_Test_Output\scientific_catalog_readiness\yz247_yzdev_catalog.sqlite",
    preview_root=r"C:\NOMAD_Test_Output\scientific_catalog_readiness\artifact_previews",
)
layer.close()
```

`preview_root` is configuration for the preview tool, never a per-call
caller-supplied path.  A layer built without it can use every tool except
`get_artifact_preview`.  The catalog is opened read-only and no caller-supplied
filesystem path reaches any tool.

## Tools

| Tool | Signature | Purpose |
|---|---|---|
| `search_devices` | `(q=None, *, limit=50, offset=0, filters=None)` | Bounded, stably ordered device search |
| `search_experiments` | `(q=None, *, limit=50, offset=0, filters=None)` | Canonically ordered experiment search |
| `search_artifacts` | `(q=None, *, limit=50, offset=0, kind=None, filters=None)` | Artifact search with kind filtering |
| `get_device` | `(device_id)` | Exact device by ID, or `None` |
| `get_experiment` | `(experiment_id)` | Exact experiment with review state and measured-on data |
| `get_artifact` | `(artifact_id)` | Exact artifact including `derived_from` |
| `find_device_experiments` | `(device_id, *, limit=50, offset=0, q=None)` | Explicit device-measured experiments |
| `find_device_documents` | `(device_id, *, limit=50, offset=0, q=None)` | Device PDF/PPT/PPTX documents |
| `get_artifact_preview` | `(artifact_id)` | Validated cache-only preview report |
| `get_provenance` | `(subject_type, subject_id)` | Persisted metadata claims for one subject |
| `get_lineage` | `(entity_type, entity_id)` | Persisted relationship edges touching one entity |

Search tools return `{"items": [...], "total_count": N, "limit": L,
"offset": O}`.  Unknown filters, invalid IDs, out-of-range limits, and
negative offsets raise `ValueError` with a clear message.

## Deterministic Example Workflows

These workflows need no AI model; every call is deterministic over the
verified YZ247/YZDEV corpus.

### Device: D356

```python
layer.search_devices("356")
# items == [{"device_id": "D356", "aliases": ["D356 WSe2_AuSplitGate"], ...}]

layer.find_device_experiments("D356")
# total_count == 317, explicit measured_on experiments only

layer.find_device_documents("D356")
# PPT/PPTX/PDF documents bound to D356 (slide-category decks excluded)
```

### Experiment: YZ247-0432 and D356-0316

```python
layer.get_experiment("YZ247-0432")
# metadata, files_by_role (raw/processed/figure), lineage,
# measured_on (YZ247), review state

layer.get_experiment("D356-0316")
# review_state == "accepted", needs_review == False
# files_by_role has exactly one raw, one processed, one figure file
# review_evidence holds the human-reviewed raw match claim

layer.get_experiment("D356-0317")
# needs_review == True, review_state == "unknown"
# unresolved_processed_files / resolved_unresolved_history pass through
```

### Provenance and lineage

```python
layer.get_provenance("experiment", "D356-0316")
# measured_on_device claim (storage_directory) plus a measured_on_raw_match
# claim with source_type "human_review",
# extraction_method "human_reviewed_match", review_status "accepted"

layer.get_lineage("file", "<deterministic file id>")
# persisted derived_from edges, source upstream -> target downstream:
# raw CSV -> processed DAT -> figure PNG
```

Only persisted edges and claims are exposed; nothing is inferred.  File entity
IDs are also resolved to storage-relative paths when the store knows them.

### Preview

```python
layer.get_artifact_preview("<D356 figure artifact id>")
# {"artifact_id": ..., "status": "ready", "kind": "image",
#  "assets": [{"path": "image.png", ...}], ...}
```

The report is cache-only and manifest-validated; asset bytes are read by
`lab_data.artifact_previews.read_artifact_preview_asset` under the same
validated preview root, never from a caller-supplied path.

## MCP Readiness

Status: the tool layer is implemented and the thin MCP adapter ships in
`lab_data.mcp_adapter` (see [MCP Adapter](mcp_adapter.md)).  The adapter shape
is:

```text
MCP tools -> ScientificToolLayer -> CatalogStore
```

The adapter maps each MCP tool to one `ScientificToolLayer` method and returns
the JSON-safe payload verbatim over stdio.  It is local-only and
unauthenticated; it must never be exposed unauthenticated on the CMU-Secure
deployment or the Internet.

Future auth boundary: any MCP/tool endpoint must use the same access control
as the browser UI (the read-only catalog browser), which today means campus
or VPN reachability only.  Unauthenticated tool exposure is not allowed.

## Invariants

The layer is read-only: no upload, delete, metadata mutation, relationship
mutation, review editing, source modification, or NOMAD write.  Catalog and
preview cache file mtimes are unchanged by tool calls.
