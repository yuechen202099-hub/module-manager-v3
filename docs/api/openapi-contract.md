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

## Tasks

- `GET /projects/{project_id}/tasks`
- `POST /projects/{project_id}/tasks/publish`
- `POST /tasks/{task_id}/claim`
- `POST /tasks/{task_id}/release`
- `GET /tasks/{task_id}`
- `GET /tasks/{task_id}/groups`

## Review

- `GET /groups/{group_id}`
- `PATCH /groups/{group_id}/review`
- `POST /groups/{group_id}/exceptions`
- `POST /groups/{group_id}/photos/sign-upload`
- `POST /groups/{group_id}/photos/complete-upload`

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

