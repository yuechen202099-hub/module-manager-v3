# Module Replacement Project Manager V2.01

V2.0 upgrades the V1.3 desktop workflow into a low-cost multi-user web system for client demonstration, review collaboration, and first-server deployment preparation.

## Scope

- Before any change, read `AGENTS.md` first. It is the project required reading and collaboration contract.
- New agents must also read `docs/AGENT_REQUIRED_READING.md` before touching production maintenance work.
- 4 reviewers working at the same time.
- About 23,000 meter groups.
- About 100,000 photos.
- Reviewers claim published terminal tasks themselves.
- Review progress is saved per meter group, so partial work can be uploaded.
- Admin users can see all tasks. Reviewers only see available tasks and their own claimed tasks.

## Required V2 Direction

- V2 main workflow is spreadsheet import. It must not depend on the Ezcodes backend API.
- Spreadsheet photo records save and load URL references only.
- Manual补图 accepts local image upload and stores the resulting served path or future OSS key as a normal photo reference.
- Review classification must be keyboard-first. Shortcut operations are a primary acceptance criterion.
- UI must feel like an advanced review workstation: dense, calm, precise, fast, and suitable for repeated review work.
- Future development must use multi-agent collaboration. Frontend, backend, database, product, test, and visual/CSS responsibilities are separated in `AGENTS.md`; overlapping edits are forbidden unless explicitly coordinated.

## Stack

- Frontend: Vue 3, TypeScript, Vite, Pinia, Vue Router, Element Plus.
- Backend: FastAPI, SQLAlchemy, Alembic, Pydantic.
- Database: PostgreSQL.
- File storage: S3/OSS-compatible object storage.
- Deployment: one low-cost 2C2G server first, Nginx + FastAPI + PostgreSQL on the same host.

## Business Rules

- Total catalog is the only source of installation address.
- Stage catalog is used only for stage, terminal, and task slicing.
- Long scanned barcode match key: remove the first 11 chars and the last 1 char.
- Total catalog short meter match key: remove the first 2 chars.
- Display meter number must use the original meter number from the total catalog.
- Installation address must not be deduplicated because it is one-to-one with meter rows.
- Imported spreadsheet photos are stored as URL references with metadata only.
- Manual补图 uploads are stored as served photo references for review and export.
- If a reviewed group is incomplete and new valid photos are imported, the group returns to unreviewed state.

## Directory Layout

```text
v2-api/       FastAPI backend
v2-web/       Vue frontend
docs/         API, database, design, and project management docs
infra/        Nginx and deployment support files
docker-compose.yml
.env.example
```

## Client Demo And Deployment Readiness

Before showing the first web build to the client, use `docs/CLIENT_DEMO_READINESS.md` as the demo checklist. Use `docs/CLIENT_DEMO_SCRIPT.md` as the talk track for login, project board, spreadsheet import, task claiming, keyboard review, exception handling, and deployment readiness. Use `docs/CLIENT_ACCEPTANCE_REPORT.md` as the client-facing acceptance summary, `docs/CLIENT_SIGNOFF_CHECKLIST.md` as the payment/signoff checklist, and `docs/CLIENT_FINAL_AUDIT.md` as the final evidence checklist before sending the release package.

## Production SOP

The production maintenance SOP entrypoint is `docs/sop/README.md`. Every production-impacting change should follow the relevant SOP and create a release record under `ops/releases/`.

Required production references:

- Demand intake and priority: `docs/sop/01-demand-intake-and-priority.md`
- Production branch and versioning: `docs/sop/02-production-branch-versioning.md`
- Release package and hash: `docs/sop/05-release-package-and-hash.md`
- Production deploy runbook: `docs/sop/06-production-deploy-runbook.md`
- Rollback and incident review: `docs/sop/07-rollback-and-incident-review.md`
- Business acceptance templates: `docs/sop/08-business-acceptance-templates.md`

Verify SOP references after changing release process files:

```powershell
.\.venv\Scripts\python.exe .\scripts\verify_release_sop.py
```

## Vue Migration Gate

Vue is the target production frontend. The old static HTML pages are now treated as compatibility pages and must be registered in `v2-web/src/router/staticPages.ts`.

```powershell
python scripts/verify_vue_migration_gate.py
```

Build the Vue shell into the FastAPI static directory:

```powershell
cd v2-web
npm run build
```

Before removing the frontend-structure risk from product scoring:

```powershell
python scripts/verify_vue_migration_gate.py --strict-native
```

For the first low-cost server rollout, use `docs/SERVER_DEPLOYMENT_PREP.md`. It links the Nginx and systemd samples under `infra/` and lists the environment values that must be changed before production data is imported.

Run the full client acceptance gate before a client walkthrough:

```powershell
.\scripts\run-client-acceptance-gate.ps1
```

This installs dependencies, runs tests, verifies static pages, verifies deployment sample files, runs the demo smoke check, builds the release package, verifies the zip, and cleans temporary smoke-upload files.

Run the local demo:

```powershell
.\scripts\run-client-demo.ps1
```

The demo script starts the local server if needed, waits for `/health`, runs `scripts\seed-client-demo-data.py`, runs the client smoke check, prints the demo entries, and opens the login page. If the current in-memory demo state has no visible review image URL, the seed script adds one claimed terminal task with four local static demo image URLs so the review workbench is never blank during a client walkthrough.

Run a light smoke check only:

```powershell
.\.venv\Scripts\python.exe .\scripts\smoke-client-demo.py
```

This verifies login, page entries, fixed navigation active states, manual补图 local image upload without URL input, role guards, summary data, production demo-account safety, demo image assets, and deployment checklist files.

Run production readiness verification on the server before exposing real project data:

```powershell
.\.venv\Scripts\python.exe .\scripts\verify-production-readiness.py --env .\.env
```

It blocks default secrets, demo auth, weak admin credentials, and incomplete deployment samples.

Build a clean production server release package:

```powershell
.\scripts\build-client-release.ps1 -Version 3.0.39
```

The release package is created under `build/server-release/` and includes `RELEASE_MANIFEST.md` with version, generated time, included files, excluded local artifacts, verification commands, and production notes. The historical `build/client-release/` path is for old demo documents only and must not be used for production deployment.

## Legacy Local Simulation

The early `/v201` local simulation page has been retired from the client-facing flow. Direct visits to `/v201` now redirect to the formal review workbench at `/task-hall` so old bookmarks do not expose local test controls during a client walkthrough.
