# API Contract Draft

This document is the contract boundary between frontend and backend.

## Auth

- `POST /auth/login`
- `GET /auth/me`

## Projects

- `GET /projects`
- `POST /projects`
- `GET /projects/{project_id}`

## Catalog

- `POST /projects/{project_id}/catalog/total/import`
- `POST /projects/{project_id}/catalog/stage/import`
- `GET /projects/{project_id}/catalog/imports/{job_id}`

## Scan Data

- `POST /projects/{project_id}/scan/import`
- `GET /projects/{project_id}/scan/imports/{job_id}`
- `GET /projects/{project_id}/groups`

`POST /projects/{project_id}/scan/import` is the primary scan/photo ingestion path. It accepts spreadsheet uploads once the final template is confirmed. Parsed rows must support terminal, collector, meter number, module number, address, one or more photo URLs, and classification naming. Photo URLs are stored as URL references; the import endpoint must not download photo binaries.

## Tasks

- `GET /projects/{project_id}/tasks`
- `POST /projects/{project_id}/tasks/publish`
- `POST /tasks/{task_id}/claim`
- `POST /tasks/{task_id}/release`
- `GET /tasks/{task_id}`
- `GET /tasks/{task_id}/groups`

Task status values returned by production APIs must use the database enum: `draft`, `published`, `claimed`, `released`, `completed`, `cancelled`.
The V2.1 local simulation value `in_review` is a local-only alias and must be normalized to `claimed` before persistence or production API response.

Allowed task transitions:

| From | Endpoint/action | To |
| --- | --- | --- |
| `draft` | `POST /projects/{project_id}/tasks/publish` | `published` |
| `published` | `POST /tasks/{task_id}/claim` | `claimed` |
| `released` | `POST /tasks/{task_id}/claim` | `claimed` |
| `claimed` | `POST /tasks/{task_id}/release` by current claimant | `released` |
| `claimed` | complete workflow | `completed` |

## Review

- `GET /groups/{group_id}`
- `PATCH /groups/{group_id}/review`
- `POST /groups/{group_id}/exceptions`
- `POST /groups/{group_id}/photos/sign-upload`
- `POST /groups/{group_id}/photos/complete-upload`

Group status values returned by production APIs must use the database enum: `unreviewed`, `in_review`, `incomplete`, `approved`, `rejected`.
Local simulation aliases are normalized as follows: `pending` to `unreviewed`, `unmatched` to `rejected` with an exception, and `exception` to `rejected` with an exception.

Photo rules:

- A group requires at least 4 valid uploaded photos to leave `incomplete`.
- `POST /groups/{group_id}/photos/complete-upload` appends a photo to the existing group and deduplicates by `group_id + sha256`.
- After supplemental-photo completion, the backend recalculates `photo_count`. If the count is at least 4 and no other blocking exception remains, the group returns to `unreviewed`.
- Review approval must reject groups whose current `photo_count` is below 4.

Address rule:

- Group address fields returned by `GET /groups/{group_id}` and task group listings must be sourced from `material_groups.installation_address`, which is copied only from `total_catalog_rows.installation_address`.
- Stage catalog, scan data, and review payloads must not be accepted as installation-address updates.

## Exports and Jobs

- `POST /exports/task-detail`
- `POST /exports/final-delivery`
- `GET /jobs/{job_id}`

## Response Shape

```json
{
  "data": {},
  "error": null,
  "request_id": "string"
}
```

Errors use this shape:

```json
{
  "data": null,
  "error": {
    "code": "string",
    "message": "string",
    "details": {}
  },
  "request_id": "string"
}
```
