# Deployment

The lab-data scientific browser is served from a single origin: one FastAPI
process serves both the read-only catalog API and the built React frontend.

## Development workflow

Run the API backend (requires the catalog and preview environment variables):

```sh
set LAB_DATA_CATALOG_PATH=C:\path\to\catalog.sqlite
set LAB_DATA_PREVIEW_ROOT=C:\path\to\artifact_previews
python scripts/serve_local_api.py
```

Run the Vite dev server with the API proxy:

```sh
cd frontend
npm install
npm run dev
```

The Vite server listens on `http://127.0.0.1:5173` and proxies `/api` requests
(all catalog API calls) to the FastAPI backend on `http://127.0.0.1:8000`.

## Local production-style serving

Build the frontend once:

```sh
cd frontend
npm run build
```

Then serve the app from one host and port:

```sh
set LAB_DATA_CATALOG_PATH=C:\path\to\catalog.sqlite
set LAB_DATA_PREVIEW_ROOT=C:\path\to\artifact_previews
python scripts/serve_lab_data.py
```

The server validates that the catalog, preview root, and frontend build
(`frontend/dist` under the repository by default) exist, then serves the API
and the SPA together. FastAPI routes are matched before the SPA fallback, so
API paths and artifact preview assets are never served as HTML.

## Routes

The catalog API lives under `/api/...`; every other top-level path is a React
SPA route (or a built asset) served from `index.html`.

| Path | Served by | Purpose |
|---|---|---|
| `/` | FastAPI | SPA entry (`index.html`) |
| `/devices`, `/experiments`, `/artifacts` | SPA fallback | List pages |
| `/devices/{id}`, `/experiments/{id}`, `/artifacts/{id}` | SPA fallback | Detail pages |
| `/assets/*` | FastAPI | Built frontend assets |
| `/api/summary`, `/api/devices`, `/api/experiments`, `/api/artifacts` | FastAPI | Catalog list/search |
| `/api/devices/{id}/experiments`, `/api/devices/{id}/documents` | FastAPI | Device relations |
| `/api/artifacts/{id}/preview` and `/api/artifacts/{id}/preview/assets/*` | FastAPI | Artifact previews |

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `LAB_DATA_CATALOG_PATH` | required | Read-only SQLite catalog file |
| `LAB_DATA_PREVIEW_ROOT` | required | Preview cache directory |
| `LAB_DATA_HOST` | `127.0.0.1` | Bind address |
| `LAB_DATA_PORT` | `8000` | Bind port |
| `FRONTEND_DIST` | `<repo>/frontend/dist` | Built frontend directory |

`scripts/serve_lab_data.py` also accepts `--frontend-dir <path>` to override
the frontend build location (CLI value wins over `FRONTEND_DIST`, which wins
over the repository default).

`127.0.0.1` binds to this computer only. Set `LAB_DATA_HOST=0.0.0.0` to bind
all interfaces; use that only when the campus or VPN network policy allows
exposing the lab server.

## Operational deployment on CMU-Secure

`scripts/start_lab_data.ps1` is the startup entry point for serving the
browser to lab members on the campus network. It resolves the repository root
from its own location, so it works from any caller working directory:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_lab_data.ps1
```

The default host is `0.0.0.0` and the default port is `8765`, matching the
existing inbound firewall rule for TCP 8765 (display name
`lab-data server inbound TCP 8765 (CMU-Secure Public)`, Public profile) that
already allows campus access. This script never modifies firewall rules,
network policy, VPN state, or credentials. Campus policy beyond the existence
of that rule is not claimed here.

### Parameters

| Parameter | Default | Meaning |
|---|---|---|
| `-Host` | `0.0.0.0` | Bind address; `127.0.0.1` for local-only serving |
| `-Port` | `8765` | Listen port |
| `-Catalog` | `LAB_DATA_CATALOG_PATH` | Read-only SQLite catalog file (required) |
| `-PreviewRoot` | `LAB_DATA_PREVIEW_ROOT` | Preview cache directory (required) |
| `-FrontendDir` | `FRONTEND_DIST`, else `<repo>/frontend/dist` | Built frontend |
| `-DryRun` / `-NoLaunch` | off | Validate config and print URLs, do not start |
| `-ShowAddress` | off | Print candidate URLs and exit (no validation) |

Environment variables are used as fallbacks when parameters are omitted:
`LAB_DATA_HOST`, `LAB_DATA_PORT`, `LAB_DATA_CATALOG_PATH`,
`LAB_DATA_PREVIEW_ROOT`, and `FRONTEND_DIST`.

### Validation and port conflicts

Before starting, the script verifies that the catalog file, preview
directory, and frontend `index.html` exist, and that the chosen port is free.
Failures print a clear message to stderr and exit non-zero:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_lab_data.ps1 -DryRun
# error: port 8765 is already in use by python (PID 31432) ...; exit code 1
```

When the port is occupied the script reports the owning process (name and
PID) and stops; it never kills or steals the port. Re-run with `-Port` set to
another port.

### URL discovery

When bound to `0.0.0.0`, the script prints `http://<ip>:<port>/` for each
connected IPv4 interface, ordered so interfaces carrying the default route
(typically the campus `CMU-SECURE` Wi-Fi link) appear first, followed by
`http://127.0.0.1:<port>/`. Addresses are discovered at runtime, so they stay
correct if DHCP changes them.

`scripts/show_lab_data_url.ps1` is the read-only address helper: it prints
the same candidate URLs for a host/port without touching configuration,
network, or firewall state:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/show_lab_data_url.ps1
```

### Lab-member flow

1. On the lab host, run `scripts/start_lab_data.ps1` (or first `-DryRun` to
   inspect the URLs, then start for real).
2. Note the campus URL shown first (for example
   `http://172.26.65.61:8765/`); this is the address lab members use.
3. From another PC on CMU-Secure, open that URL in a browser. The catalog
   browser is read-only: every API route is GET and the deployment never
   writes to the catalog, preview cache, or frontend build.

Off-campus users should connect through the CMU VPN to the campus network
before using the lab URL.

## Campus/VPN access

Off-campus users should connect through the CMU VPN to the campus network and
then to the lab server. A future authentication/SSO boundary will gate
access. Campus routing and firewall rules beyond the existing inbound TCP
8765 rule are not approved or tested here.

## Read-only guarantee

The API exposes only GET endpoints. The catalog is opened read-only and the
deployment never writes to the catalog, preview cache, or frontend build.
No write endpoints are registered.
