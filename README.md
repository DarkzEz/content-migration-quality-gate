# Content Migration Quality Gate

A small, independently implemented portfolio project demonstrating how to validate a content-migration and publishing flow across service boundaries.

> **Relationship to prior work:** The project is inspired by the problem space described in my QA work: migrating content from an older Tilda-based site to a new implementation, where CMS and an administrative layer were involved in content creation, validation, and publishing. The actual employer architecture, internal endpoints, code, policy rules, and production data are not reproduced here. This repository uses synthetic examples and a deliberately simplified topology.

## What this demonstrates

- Mapping a small exported legacy-content format into a strict destination content model.
- Preserving selected text-formatting metadata while converting legacy block types.
- Idempotent CMS draft creation keyed by a stable source reference.
- An admin/publishing API that loads drafts, runs illustrative policy checks, and publishes only valid content.
- A destination-site API with a public read endpoint and a restricted internal publishing endpoint.
- Explicit response-contract validation at HTTP service boundaries.
- Safe handling of dependency outages, invalid upstream payloads, slug collisions, and content-policy failures.
- Correlation-ID propagation across the admin, CMS, and destination-site calls.
- Unit/contract tests and black-box integration tests used as a CI quality gate.
- Container health checks, loopback-only host ports, non-root runtime, read-only root filesystems, and dropped Linux capabilities.

## Architecture

```text
examples/tilda-export.json
          |
          v
  migration CLI / mapper
          |
          | POST /v1/migrations
          v
   +----------------------+     POST /v1/drafts
   | Admin / publishing   | ----------------------> +--------------+
   | orchestration        |                          | CMS API      |
   +----------------------+ <---------------------- | draft store  |
          |             ^       GET /v1/drafts/{id} +--------------+
          |             |                                  ^
          |             +---- mark status published -------+
          |
          | POST /internal/v1/pages
          v
   +----------------------+
   | Destination Site API |
   | published page store |
   +----------------------+
          |
          | GET /v1/pages/{slug}
          v
     Public page response
```

There are three runtime services: **CMS**, **Admin/publishing**, and the **new destination site**. The legacy Tilda side is represented by a synthetic JSON export fixture rather than a running clone of Tilda. The CMS API models the backend used by a content-management UI; the UI itself is outside this repository. The topology is one reasonable testing model for the described workflow, not a claim that the original systems used these exact boundaries or APIs.

### Example flow

1. The migrator validates the legacy-export file and maps supported blocks to the destination content model.
2. The migrator sends the mapped page to the Admin API. Admin creates the CMS draft through its own service integration. A stable `source_reference` prevents duplicate draft creation when the same unchanged item is submitted again. Reusing the reference with changed content returns a conflict rather than silently overwriting the first draft.
3. Admin reloads the draft from CMS, validates the response contract, and checks an illustrative blocked-term policy.
4. If policy checks pass, Admin requests publication by the destination site and validates the site's response.
5. Admin marks the CMS draft as published. If the destination accepts a page but this final status update fails, the API reports the partial failure; a repeat is safe because destination publishing and the status update are idempotent.
6. The black-box tests verify that published content is retrievable from the new site and rejected content never appears there.

## Repository layout

```text
.
├── .github/workflows/ci.yml
├── examples/
│   ├── tilda-export.json
│   └── restricted-content.json
├── src/content_migration_gate/
│   ├── admin.py       # Draft validation and publishing orchestration
│   ├── clients.py     # HTTP clients and downstream contract checks
│   ├── cms.py         # Draft creation and retrieval API
│   ├── contracts.py   # Strict legacy and destination models
│   ├── errors.py      # Typed dependency and publication failures
│   ├── mapper.py      # Legacy-to-destination content mapping
│   ├── migration.py   # CLI and per-page migration flow
│   ├── observability.py
│   └── site.py        # Publish and public-read API
├── tests/
│   ├── unit/          # Contracts, mapping, clients, services and failure paths
│   └── e2e/           # Black-box tests against running services
├── Dockerfile
├── compose.yaml
└── pyproject.toml
```

## Run locally

Requirements: Python 3.11+; Docker Engine and the Docker Compose plugin are only required for the composed run.

### 1. Create the environment

**PowerShell:**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

**macOS/Linux:**

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

### 2. Validate and preview the legacy export

The dry-run validates and maps every page but makes no network calls and does not write content to CMS.

```bash
content-migrator --file examples/tilda-export.json --dry-run
```

The same command can be executed as a module:

```bash
python -m content_migration_gate --file examples/tilda-export.json --dry-run
```

### 3. Run unit and contract tests

```bash
ruff check .
pytest -q --cov=content_migration_gate --cov-branch --cov-report=term-missing tests/unit
```

Unit tests run without Docker or any external services. CI enforces the configured coverage floor.

### 4. Start the service stack

```bash
# Optional: copy .env.example to .env to customize the demo policy and timeout.
docker compose up --build --detach
```

All three service ports are published to loopback only for local development:

| Service | Base URL | Purpose |
|---|---|---|
| CMS | `http://127.0.0.1:8101` | Create and retrieve drafts |
| Admin | `http://127.0.0.1:8102` | Validate and publish drafts |
| Destination site | `http://127.0.0.1:8103` | Read published pages |

Wait for each `/health` endpoint to return HTTP 200 before running a migration.

### 5. Execute the migration

Start with the dry-run. Only use `--execute` when the mapped content is understood and the local stack is running.

```bash
content-migrator --file examples/tilda-export.json --execute
```

The command sends each mapped page to the Admin API, which creates a CMS draft, validates it, publishes the page, and marks the draft as published. It reports a result per source page. If one item fails, it continues with the remaining pages and exits with a non-zero status so a shell script or CI can detect partial failure.

Read a page after a successful migration:

```bash
curl --fail http://127.0.0.1:8103/v1/pages/about-the-center
```

To see the demo policy reject a page, execute:

```bash
content-migrator --file examples/restricted-content.json --execute
```

The demo policy rejects the marker terms `do-not-publish` and `internal-only` by default. These are deliberately synthetic test markers, **not** the original employer's moderation rules. Override `BLOCKED_TERMS` in the Admin service only for local experimentation.

Run black-box tests while the stack is running:

```bash
CONTENT_GATE_E2E=1 pytest -q tests/e2e
```

PowerShell equivalent:

```powershell
$env:CONTENT_GATE_E2E = "1"
pytest -q tests/e2e
```

Stop the stack and remove its ephemeral state:

```bash
docker compose down --volumes
```

## Selected API contracts

### CMS: `POST /v1/drafts`

```json
{
  "source_reference": "tilda:page-about-center",
  "slug": "about-the-center",
  "title": "About the Center",
  "blocks": [
    {
      "type": "heading",
      "text": "A place to learn and build",
      "style": {
        "font_family": "Arial",
        "font_size_pt": 32,
        "color": "#17324D"
      }
    }
  ]
}
```

Repeated submissions with the same source reference and exactly the same mapped payload return the existing draft. Reusing a source reference for different content returns HTTP 409, which prevents silent overwrite during a rerun.

### Admin: `POST /v1/migrations`

Accepts a mapped content payload, creates or reuses a CMS draft, validates it, publishes it, and confirms the CMS status. The migration CLI calls this endpoint instead of writing directly to CMS. A repeated unchanged source item is safe to retry.

### Admin: `POST /v1/drafts/{draft_id}/publish`

Used to publish a draft created through the CMS content-management flow.

- `200`: the validated draft is published or the same draft was already published; the CMS status is confirmed as `published`.
- `404`: draft does not exist.
- `409`: destination slug is owned by a different draft.
- `422`: content fails the configured illustrative policy; the site is not called.
- `502`: CMS/site is unavailable or its response violates the expected contract.

### Destination site: `GET /v1/pages/{slug}`

Returns only published content. A draft rejected by Admin should not be visible through this public read endpoint.

## Design decisions

- **Strict schemas at boundaries.** Unknown fields and invalid block shapes are rejected; an HTTP 200 alone is not treated as proof of a compatible response.
- **Idempotency without silent mutation.** Same source reference plus same payload returns the existing draft; same reference plus changed payload fails explicitly.
- **Idempotent write boundaries.** Retrying writes safely requires a clear idempotency contract. The CMS keys drafts by source reference, destination publication is idempotent for the same draft, and the CMS status transition is safe to repeat. The demo does not blindly retry failed POSTs.
- **Per-item failure reporting.** A broken page does not stop unrelated pages from being attempted, but any partial failure produces a non-zero CLI exit code.
- **Correlated requests.** One correlation ID is passed from the migrator through CMS/Admin/Site calls so request chains can be traced in logs or test assertions.
- **Bounded network calls.** Internal HTTP clients have connection/request timeouts and do not follow redirects implicitly.
- **Run locally with narrow exposure.** Compose binds service ports to `127.0.0.1`; the container runs non-root with a read-only root filesystem and dropped capabilities.

## Limits and production considerations

This is a focused demo, not a production content platform. Each service keeps state in memory, so data resets when a process restarts; CMS and site do not share a database. There is no real authentication, authorization, audit trail, rollback, asset downloading, HTML sanitization engine, or production moderation model. If the site succeeds but the CMS status update fails, the caller sees a partial failure. A repeated publish request sends the same content to the destination (which returns the existing page for the same draft) and retries the CMS status transition. A production implementation would need persistent storage, stronger identity and access controls, operational observability, and a carefully defined failure/reconciliation strategy.
