# Client Demo Script

Use this script for the first client walkthrough. The goal is to show that V2.0 is already a real operating workflow, not just a static dashboard.

## 1. Login And Role Split

Open:

```text
http://127.0.0.1:8000/login
```

Show:

- Admin enters the project board.
- Reviewer enters the review workbench.
- Reviewers can open the project board in read-only mode. Import, export, account management, and other administrator operations stay hidden unless the logged-in user has the `admin` role.
- The review workbench shows the reviewer identity from the logged-in account.

Demo accounts:

- Admin: `admin / admin123`
- Reviewer: `reviewer / review123`

## 2. Admin Project Board

Open:

```text
http://127.0.0.1:8000/project-board
```

Talk track:

- The top five-step flow explains the whole delivery path: import, claim, review, exception handling, final delivery.
- The progress carousel prioritizes scanned-photo progress and reviewed-group progress.
- Installer group share shows how many data groups each installer contributed.
- Terminal task progress shows uploaded, unreviewed, upload rate, review rate, and current holder.

## 3. Spreadsheet Import Workflow

Open the review workbench:

```text
http://127.0.0.1:8000/task-hall
```

Click `导入表格数据`.

Talk track:

- The current main workflow is spreadsheet import because the supplier does not provide a stable official API.
- Imported photo rows keep URL references only. The system does not download spreadsheet photos locally.
- Important fields: terminal, collector, meter number, module number, address, photo URL, installer.

Then open:

```text
http://127.0.0.1:8000/sync-config
```

Talk track:

- The `/sync-config` page is now an explanation page only: no token input, no hidden backend sync dependency.
- This protects the first delivery from relying on an unofficial supplier API that cannot be guaranteed in production.

## 4. Task Claiming

Open:

```text
http://127.0.0.1:8000/claim-tasks
```

Talk track:

- Reviewers claim tasks by terminal.
- Only terminals with scan/photo data can become review tasks.
- Claimed tasks prevent multiple reviewers from classifying the same terminal at the same time.

## 5. Keyboard-First Review

Return to:

```text
http://127.0.0.1:8000/task-hall
```

Talk track:

- The reviewer only sees owned tasks.
- Claimed tasks and archive records are attributed to `reviewer`.
- Number keys select category.
- Enter archives the current photo.
- Arrow keys switch photos and groups.
- Each photo archive filename follows its category label.

## 6. Exception And Recovery

Open:

```text
http://127.0.0.1:8000/unmatched
```

Talk track:

- Unmatched scan rows can be converted into terminal-linked groups.
- Admin can create an empty group for a terminal.
- Missing photos are supplemented from `/unmatched` after selecting an exception data group; the project board only owns spreadsheet import and progress review.
- Importing new valid photos can return incomplete reviewed groups to unreviewed status for re-checking.

## 7. Server Readiness

Show:

- `docs/SERVER_DEPLOYMENT_PREP.md`
- `infra/nginx/module-manager-v2.conf`
- `infra/module-manager-v2.service`

Talk track:

- First server version can run on a low-cost 2C2G host.
- Nginx proxies to FastAPI on `127.0.0.1:8000`.
- PostgreSQL can be deployed on the same server for the first version.
- Before production import, replace demo accounts, configure secrets, HTTPS, and database backup.
