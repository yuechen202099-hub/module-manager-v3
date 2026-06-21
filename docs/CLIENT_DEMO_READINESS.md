# Client Demo Readiness

This file tracks what must be true before showing the first web build to the client.

## Demo Entrypoints

- Login: `http://127.0.0.1:8000/login`
- Admin board: `http://127.0.0.1:8000/project-board`
- Reviewer workbench: `http://127.0.0.1:8000/task-hall`
- Task claim page: `http://127.0.0.1:8000/claim-tasks`
- Unmatched data handling: `http://127.0.0.1:8000/unmatched`
- Sync status guidance: `http://127.0.0.1:8000/sync-config`

Use `docs/CLIENT_DEMO_SCRIPT.md` as the spoken walkthrough order.
Use `docs/CLIENT_ACCEPTANCE_REPORT.md` as the acceptance summary after the walkthrough.
Use `docs/CLIENT_FINAL_AUDIT.md` as the final evidence checklist before sending the release package.

## Demo Accounts

- Admin: `admin / admin123`
- Reviewer: `reviewer / review123`

The project board is visible to reviewers as a read-only progress view. Import, export, account management, and other administrator operations require the `admin` role and stay hidden for reviewer accounts.

## First-Version Acceptance Points

- Login redirects users to the correct workspace.
- Admin can see project progress, scanned-photo progress, review progress, task status, installer group share, and risk distribution.
- Reviewers only classify tasks they have claimed.
- Reviewer task ownership and archive history use the logged-in `reviewer` account, not a local debug reviewer id.
- Classification remains keyboard-first: number keys select category, Enter archives the current photo, arrow keys switch photos/groups.
- Spreadsheet import is the main workflow. Spreadsheet photo files are not downloaded to local storage; imported photo URLs and metadata are stored.
- The discontinued sync page must explain that supplier API sync is not part of the first delivery and must not expose a token/request JSON input.
- Admin can create an empty group without forcing a terminal, then handle terminal association and missing-photo uploads from `/unmatched`.
- Unmatched scan rows can be manually converted into terminal-linked groups.
- The UI uses one calm workstation visual language across login, board, claim, review, and unmatched pages.
- The demo startup script seeds four local static review image URLs if the current runtime has no visible photo, preventing the review workbench from opening on an empty image state during a client walkthrough.

## Local Run

Run the full client acceptance gate before the client walkthrough:

```powershell
.\scripts\run-client-acceptance-gate.ps1
```

This runs the backend tests, static page checks, demo smoke check, release build, release zip verification, and temporary upload cleanup.
It also validates that deployment sample files and `.env.example` contain the required production handoff fields.

```powershell
.\scripts\run-client-demo.ps1
```

The script starts the local server if needed, waits for `/health`, runs `scripts/seed-client-demo-data.py`, runs `scripts/smoke-client-demo.py`, prints the demo entry URLs, and opens `/login` unless `-NoOpen` is passed.

Run manual server commands from:

```text
C:\Users\Administrator\Desktop\2025模块改造\模块更换项目管理器V2.0\v2-api
```

## Verification Commands

```powershell
.\scripts\run-client-acceptance-gate.ps1
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe .\scripts\smoke-client-demo.py
.\.venv\Scripts\python.exe .\scripts\verify-static-pages.py
.\.venv\Scripts\python.exe .\scripts\verify-production-readiness.py --example
```

## Server Preparation Notes

- Replace demo users with real account storage before public deployment.
- Move secrets and server configuration into environment variables.
- Add Nginx reverse proxy and HTTPS.
- Configure PostgreSQL backups before importing production data.
- Keep uploaded spreadsheet templates and import logs for traceability.
- Use `docs/SERVER_DEPLOYMENT_PREP.md` for the first 2C2G server rollout checklist.
