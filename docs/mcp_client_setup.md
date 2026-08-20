# MCP Client Setup (Local, stdio)

This page explains how to point an MCP-capable client (Claude Desktop,
ChatGPT, or any generic stdio MCP client) at the local `lab-data` scientific
tools server. The server is read-only, runs over stdio, and never binds a
network port. There are no secrets in any of these examples, and nothing here
enables remote or authenticated access.

## Launch Contract

The client launches one Python process per server entry. The process contract
is:

```text
command:  <repo>\.venv\Scripts\python.exe
args:     -m lab_data.mcp_adapter
env:      LAB_DATA_CATALOG_PATH=<catalog .sqlite>
          LAB_DATA_PREVIEW_ROOT=<preview cache directory>
cwd:      <repo>
```

On the current host, `<repo>` is `C:\CodexRepos\lab-data` and the interpreter
is `C:\CodexRepos\lab-data\.venv\Scripts\python.exe`. The source code reads
everything from environment variables, so these host-specific paths appear
only in the client configuration, never in the repository code.

## Generic stdio Client Configuration

Most MCP clients accept a JSON config with an `mcpServers` map. Use this exact
shape:

```json
{
  "mcpServers": {
    "lab-data": {
      "command": "<repo>\\.venv\\Scripts\\python.exe",
      "args": ["-m", "lab_data.mcp_adapter"],
      "env": {
        "LAB_DATA_CATALOG_PATH": "...",
        "LAB_DATA_PREVIEW_ROOT": "..."
      },
      "cwd": "<repo>"
    }
  }
}
```

Replace `<repo>` with the repository path and the two `env` values with the
catalog file and preview cache directory used by the browser deployment (see
[MCP Adapter: Local Start](mcp_adapter.md)).

Some clients do not inherit the parent shell's environment when they launch
the server process, so always set `LAB_DATA_CATALOG_PATH` and
`LAB_DATA_PREVIEW_ROOT` explicitly inside `env`. Missing either variable makes
the server exit immediately with a clear message on stderr.

`LAB_DATA_HOST`, `LAB_DATA_PORT`, and `FRONTEND_DIST` are browser-deployment
settings and are not needed for MCP. The stdio server ignores them.

## Claude Desktop Configuration

Claude Desktop uses the same shape in its own config file
(`claude_desktop_config.json`, normally under
`%APPDATA%\Claude\claude_desktop_config.json` on Windows):

```json
{
  "mcpServers": {
    "lab-data": {
      "command": "<repo>\\.venv\\Scripts\\python.exe",
      "args": ["-m", "lab_data.mcp_adapter"],
      "env": {
        "LAB_DATA_CATALOG_PATH": "...",
        "LAB_DATA_PREVIEW_ROOT": "..."
      },
      "cwd": "<repo>"
    }
  }
}
```

After adding the entry, fully restart Claude Desktop (quit and reopen, not
just a new conversation) so it spawns the stdio server.

## Tool Guidance for Clients

The server exposes 11 read-only tools. To use them well:

- Search before guessing: `search_devices`, `search_experiments`, and
  `search_artifacts` take `q` as a search string and return pages. Once a
  result shows a canonical ID, call the exact `get_*` tool with that ID
  instead of re-searching.
- Use `get_provenance` for why/how: it returns persisted metadata claims with
  source, extraction method, evidence, and review status. Nothing is inferred
  on the fly.
- Use `get_lineage` for file relationships: edges are persisted and oriented
  with `source` upstream and `target` downstream, normally raw -> processed ->
  figure.
- Preserve review state: `needs_review`, `review_state`, and
  `review_status` may be `unknown` or `accepted`. Report them as returned;
  never present an unresolved experiment as resolved.
- Never infer a relationship from a filename. Filenames are sources of
  metadata claims; relationships must come from the persisted lineage or
  claims returned by the tools.
- Position labels such as `p1` or `pX2` in `measurement_point_label` are
  sample measurement positions/locations, not wiring or contact
  configurations. Electrical configuration, when known, is described by
  separate metadata fields such as `electrical_connections`,
  `gate_constraints`, and `active_gate_configuration`.

## End-to-End Workflows

The following sequences map the Queries A-F onto the exposed tools, using the
real YZ247/YZDEV corpus. JSON snippets are abbreviated but exact.

### A. Device and its experiments

`search_devices` finds the device; `find_device_experiments` returns the
explicitly measured-on experiments.

```json
{"tool": "search_devices", "arguments": {"q": "356"}}
```

```json
{
  "items": [
    {
      "device_id": "D356",
      "display_label": "D356",
      "maker_namespace": "YZ",
      "local_device_id": "D356",
      "device_type": "UNKNOWN",
      "review_state": "unknown",
      "aliases": ["D356 WSe2_AuSplitGate"],
      "metadata": {}
    }
  ],
  "total_count": 1,
  "limit": 20,
  "offset": 0
}
```

```json
{"tool": "find_device_experiments", "arguments": {"device_id": "D356", "limit": 5}}
```

```json
{
  "items": [
    {
      "experiment_id": "D356-0199",
      "measurement_type": "absorption",
      "files_by_role": {"raw": ["D356 WSe2_AuSplitGate/Initial Data/YZ356_p1_3.6KREF_720nmc_0p06sx10_BG1only.csv"], "processed": ["D356 WSe2_AuSplitGate/Processed Data/YZ356_p1_3.6KREF_720nmc_0p06sx10_BG1only_avg1_DR_R_Self.dat"], "figure": ["D356 WSe2_AuSplitGate/Processed Data/YZ356_p1_3.6KREF_720nmc_0p06sx10_BG1only_avg1_DR_R_Self.png"]},
      "measured_on": {"device_id": "D356"},
      "needs_review": false,
      "review_state": "unknown"
    }
  ],
  "total_count": 317,
  "limit": 5,
  "offset": 0
}
```

The page explicitly shows `D356` as the device and `317` experiments
measured on it.

### B. One exact experiment

Once the ID is known, `get_experiment` returns the full record.

```json
{"tool": "get_experiment", "arguments": {"experiment_id": "YZ247-0432"}}
```

```json
{
  "experiment_id": "YZ247-0432",
  "confidence": 0.8,
  "metadata": {
    "sample_id": "YZ247",
    "measurement_type": "photoluminescence",
    "temperature_K": 3.6,
    "excitation_wavelength_nm": 730.0,
    "center_wavelength_nm": 865.0,
    "measurement_point_label": "pX2",
    "stage_position": 50,
    "back_gate_topology": "single"
  },
  "files_by_role": {
    "raw": ["Initial Data/YZ247_pX2_3.6KPL_730nm0.00uW_865nmc_5sx1_Rot1195p8deg_Rot295deg_Stage50_TG+BG=0.csv"],
    "intermediate": ["Initial data after processing/YZ247_pX2_3.6KPL_730nm0.00uW_865nmc_5sx1_Rot1195p8deg_Rot295deg_Stage50_TG+BG=0.csv"],
    "processed": [],
    "figure": []
  },
  "measured_on": null,
  "needs_review": false,
  "review_state": "unknown",
  "warnings": []
}
```

### C. Accepted human-reviewed raw match

`get_experiment` surfaces the accepted review evidence directly; `get_provenance`
returns the underlying persisted claims.

```json
{"tool": "get_experiment", "arguments": {"experiment_id": "D356-0316"}}
```

```json
{
  "experiment_id": "D356-0316",
  "needs_review": false,
  "review_state": "accepted",
  "review_evidence": [
    {
      "field": "measured_on_raw_match",
      "source_type": "human_review",
      "source_reference": "artifacts/d356_0316_human_review_packet.md",
      "extraction_method": "human_reviewed_match",
      "review_status": "accepted",
      "value": {
        "device_id": "D356",
        "experiment_id": "D356-0316",
        "raw_relative_path": "D356 WSe2_AuSplitGate/Initial Data/YZ356_pa_BG2-CG_3.6KREF_720nmc_0p06sx10_FixTG-SweepBG1=2_Vb+2to-8.csv"
      }
    }
  ]
}
```

```json
{"tool": "get_provenance", "arguments": {"subject_type": "experiment", "subject_id": "D356-0316"}}
```

```json
[
  {
    "field": "measured_on_device",
    "source_type": "storage_directory",
    "source_reference": "D356 WSe2_AuSplitGate",
    "extraction_method": "device_directory_context",
    "review_status": "unknown",
    "value": {"device_id": "D356", "directory_context": "D356 WSe2_AuSplitGate"}
  },
  {
    "field": "measured_on_raw_match",
    "source_type": "human_review",
    "source_reference": "artifacts/d356_0316_human_review_packet.md",
    "extraction_method": "human_reviewed_match",
    "review_status": "accepted",
    "evidence": ["Vtg_set=4", "Vtg_meas=4", "raw filename omits FixTG value", "artifacts/d356_0316_human_review_packet.md"],
    "value": {
      "device_id": "D356",
      "experiment_id": "D356-0316",
      "raw_relative_path": "D356 WSe2_AuSplitGate/Initial Data/YZ356_pa_BG2-CG_3.6KREF_720nmc_0p06sx10_FixTG-SweepBG1=2_Vb+2to-8.csv"
    }
  }
]
```

The human-reviewed raw match is explicitly persisted with
`source_type: human_review`, `extraction_method: human_reviewed_match`, and
`review_status: accepted`.

### D. Unresolved, needs-review experiment

```json
{"tool": "get_experiment", "arguments": {"experiment_id": "D356-0317"}}
```

```json
{
  "experiment_id": "D356-0317",
  "needs_review": true,
  "review_state": "unknown",
  "measured_on": {
    "device_id": "D356",
    "evidence": "explicit device-directory context",
    "extraction_method": "device_directory_context",
    "review_status": "unknown"
  },
  "unresolved_processed_files": [
    "D356 WSe2_AuSplitGate/Processed Data/YZ356_pa_BG2-CG_3.6KREF_720nmc_0p1sx10_FixTG=-4-SweepBG1=2_Vb0to+12_001_avg1_DR_R_External.dat",
    "D356 WSe2_AuSplitGate/Processed Data/YZ356_pa_BG2-CG_3.6KREF_720nmc_0p1sx10_FixTG=-4-SweepBG1=2_Vb0to+12_001_avg1_DR_R_External.png"
  ],
  "warnings": [
    "unsupported electrical expression: SweepBG1=2",
    "processed files without a deterministically matching raw measurement: D356 WSe2_AuSplitGate/Processed Data/YZ356_pa_BG2-CG_3.6KREF_720nmc_0p1sx10_FixTG=-4-SweepBG1=2_Vb0to+12_001_avg1_DR_R_External.dat; D356 WSe2_AuSplitGate/Processed Data/YZ356_pa_BG2-CG_3.6KREF_720nmc_0p1sx10_FixTG=-4-SweepBG1=2_Vb0to+12_001_avg1_DR_R_External.png"
  ]
}
```

`needs_review: true` and `review_state: unknown` must be preserved; the tools
offer no way to resolve the experiment, and a client must not invent one.

### E. Lineage, canonical orientation

Lineage edges are persisted and oriented upstream -> downstream. For the
D356-0316 raw file, resolve the file ID first (via `search_artifacts` with a
`relative_path` filter) and then call `get_lineage`:

```json
{"tool": "get_lineage", "arguments": {"entity_type": "file", "entity_id": "file-52dd2a87366303adf167dd256bbf079d3cf518a09cb287e39cc98537dbd4a273"}}
```

```json
[
  {
    "predicate": "derived_from",
    "source_type": "file",
    "source_id": "file-52dd2a87366303adf167dd256bbf079d3cf518a09cb287e39cc98537dbd4a273",
    "source_path": "D356 WSe2_AuSplitGate/Initial Data/YZ356_pa_BG2-CG_3.6KREF_720nmc_0p06sx10_FixTG-SweepBG1=2_Vb+2to-8.csv",
    "target_type": "file",
    "target_id": "file-2a9a809be00890ec2ca6c6a08bf902551ab0f3dea1af4ef08982cee1ca217f7d",
    "target_path": "D356 WSe2_AuSplitGate/Processed Data/YZ356_pa_BG2-CG_3.6KREF_720nmc_0p06sx10_FixTG4V-SweepBG1=2_Vb+2to-8_avg1_DR_R_Self.dat",
    "provenance_source": null,
    "review_state": "unknown"
  }
]
```

The experiment's own `lineage` list gives the same chain compactly:

```json
[
  {"relation": "derived_from", "source": "D356 WSe2_AuSplitGate/Initial Data/YZ356_pa_BG2-CG_3.6KREF_720nmc_0p06sx10_FixTG-SweepBG1=2_Vb+2to-8.csv", "target": "D356 WSe2_AuSplitGate/Processed Data/YZ356_pa_BG2-CG_3.6KREF_720nmc_0p06sx10_FixTG4V-SweepBG1=2_Vb+2to-8_avg1_DR_R_Self.dat"},
  {"relation": "derived_from", "source": "D356 WSe2_AuSplitGate/Processed Data/YZ356_pa_BG2-CG_3.6KREF_720nmc_0p06sx10_FixTG4V-SweepBG1=2_Vb+2to-8_avg1_DR_R_Self.dat", "target": "D356 WSe2_AuSplitGate/Processed Data/YZ356_pa_BG2-CG_3.6KREF_720nmc_0p06sx10_FixTG4V-SweepBG1=2_Vb+2to-8_avg1_DR_R_Self.png"}
]
```

Read direction: raw CSV -> processed DAT -> figure PNG.

### F. Deterministic structured search

Experiment search accepts exact-equality structured filters. There is no
natural-language interpretation and no AI inference is persisted.

```json
{"tool": "search_experiments", "arguments": {"q": "0432", "filters": {"measurement_type": "photoluminescence"}, "limit": 10}}
```

```json
{
  "items": [
    {
      "experiment_id": "YZ247-0432",
      "confidence": 0.8,
      "metadata": {
        "sample_id": "YZ247",
        "measurement_type": "photoluminescence",
        "metadata_provenance": [
          {"field": "measurement_type", "method": "deterministic", "source_type": "filename", "value": "photoluminescence"},
          {"field": "sample_id", "method": "deterministic", "source_type": "filename", "value": "YZ247"}
        ]
      }
    }
  ],
  "total_count": 1,
  "limit": 10,
  "offset": 0
}
```

The `metadata_provenance` entries show that every persisted value is
deterministic (`method: deterministic`, e.g. `source_type: filename`); the
tools never persist model-derived values.

### Structured filters

All filters are exact equality, and unknown keys are rejected. Supported sets:

- Experiment: `experiment_id`, `needs_review`, `confidence`, plus parsed
  metadata fields such as `sample_id`, `measurement_type`, `temperature_K`,
  `magnetic_field_T`, `excitation_wavelength_nm`, `center_wavelength_nm`,
  `integration_time_s`, `averages`, `excitation_power_uW`,
  `grating_grooves_per_mm`, `stage_position`, `measurement_point_label`,
  `fixed_top_gate_V`, `bias_start_V`, `bias_stop_V`,
  `active_gate_configuration`, and `back_gate_topology`.
- Device: `device_id`, `display_label`, `maker_namespace`, `local_device_id`,
  `device_type`, `review_state`.
- Artifact: `artifact_id`, `device_id`, `experiment_id`, `role`, `category`,
  `extension`, `media_type`, `review_state`, `storage_source_id`,
  `relative_path`.

## Connecting a Real Client on This Machine

To add this stdio server to a real MCP-capable client on this Windows machine:

1. Install the MCP extra into the repository environment:
   `pip install -e ".[mcp]"` from `C:\CodexRepos\lab-data`.
2. Add the config block above to the client's server configuration (generic
   `mcpServers` JSON, or Claude Desktop's `claude_desktop_config.json`), with
   `command` set to `C:\CodexRepos\lab-data\.venv\Scripts\python.exe` and both
   `env` values set to the catalog file and preview cache directory.
3. Fully restart the client so it launches the server process.
4. Optional, and separate: the browser UI deployment stays untouched on
   `http://127.0.0.1:8765` and is configured independently.

This repository does not configure your client for you; the steps above are
the exact human actions.

## Security Boundary

The adapter runs stdio-only, binds no listening TCP port, never binds
`0.0.0.0`, and is not exposed to CMU-Secure or the Internet. Every tool is
read-only, there are no credentials, and validation performs no external model
calls. Keep it that way: do not add network transports or auth-free remote
exposure in this phase.
