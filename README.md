# Module Replacement Project Manager V2.01

V2.0 upgrades the V1.3 desktop workflow into a low-cost multi-user web system.

## Scope

- 4 reviewers working at the same time.
- About 23,000 meter groups.
- About 100,000 photos.
- Reviewers claim published tasks themselves.
- Review progress is saved per meter group, so partial work can be uploaded.
- Admin users can see all tasks. Reviewers only see available tasks and their own claimed tasks.

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
- Photos are deduplicated by SHA-256.
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

## Local Development Target

The first milestone is a runnable skeleton:

- Backend health check and OpenAPI.
- Frontend login, dashboard, task hall, and review page shells.
- PostgreSQL schema migration.
- Docker Compose boot path.
- Basic tests for barcode matching and task status flow.

## V2.01 Local Simulation

V2.01 includes a local no-npm test entry for the three provided workbooks:

- `C:\Users\Administrator\Desktop\总体数据.xlsx`
- `C:\Users\Administrator\Desktop\第一批数据.xlsx`
- `C:\Users\Administrator\Desktop\批量扫码_20260608125555.xlsx`

Run:

```powershell
.\scripts\run-v201-local.ps1
```

Then open:

```text
http://127.0.0.1:8000/v201
```

The page imports the three workbooks, applies the V1.3 barcode matching rule, and shows matched groups, missing photos, and unmatched rows.
