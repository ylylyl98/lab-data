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

## Campus/VPN access

Off-campus users should connect through the CMU VPN to the campus network and
then to the lab server. A future authentication/SSO boundary will gate
access. Campus routing and firewall rules are not approved or tested here.

## Read-only guarantee

The API exposes only GET endpoints. The catalog is opened read-only and the
deployment never writes to the catalog, preview cache, or frontend build.
No write endpoints are registered.
