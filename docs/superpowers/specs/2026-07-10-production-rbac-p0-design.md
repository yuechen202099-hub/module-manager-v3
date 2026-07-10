# Production RBAC P0 Design

## Goal

Close the highest-risk production authorization gaps without changing business data models or frontend behavior.

## Scope

- Add one request-level role guard for FastAPI routes that reads the decoded JWT payload already stored on `request.state.auth`.
- Restrict `POST /local-test/scan/clear` to administrators in production mode.
- Restrict review actor binding to `reviewer` or `admin` roles in production mode.
- Restrict construction actor binding to `constructor` or `admin` roles in production mode.
- Preserve current local-development behavior when `APP_ENV` is not `prod` or `production`.
- Add production-mode negative tests for anonymous, reviewer, and constructor access, plus positive administrator coverage.

## Out Of Scope

- Full write-route authorization audit.
- JWT revocation after account disable, deletion, or password change.
- Static upload/photo access control.
- Upload rate limiting and streamed request-size enforcement.
- Production deployment.

## Versioning Addendum

On 2026-07-10, the user superseded the original no-version-change constraint and required every bug fix to advance the semantic patch version by `0.0.1`. This RBAC fix therefore advances the release candidate from `V3.0.78` to `V3.0.79`; deployment remains out of scope.

## Authorization Rules

| Operation | Allowed roles | Rejected roles |
| --- | --- | --- |
| Clear scan data | `admin` | `reviewer`, `constructor`, unauthenticated |
| Review mutations using `bound_review_actor` | `admin`, `reviewer` | `constructor`, unauthenticated |
| Construction mutations using `bound_construction_actor` | `admin`, `constructor` | `reviewer`, unauthenticated |

Role checks are server-side. Frontend visibility is not treated as an authorization control.

## Design

Keep the change in `v2-api/app/api/routes/local_test.py`, where request payload parsing and the existing role helpers already live. Add a small helper that accepts a request and an allowed-role set, returns the JWT payload when authorized, and raises `401` for missing authentication or `403` for an authenticated role mismatch in production mode.

`request_is_admin` remains available for non-throwing decisions. The destructive clear route calls the new guard before touching the repository. The review and construction actor binders call the same guard before accepting the signed-in subject, so every existing route that already uses those binders inherits the role boundary.

## Error Behavior

- Missing or invalid authentication in production: `401 Authentication required`.
- Valid JWT without an allowed role: `403` with an operation-specific role message.
- Local/test mode: retain existing fallback behavior so local simulation tests and tools do not require production credentials.

## Test Strategy

Add focused API tests in `v2-api/tests/test_api.py` using production-mode clients and real login tokens:

- Constructor and reviewer tokens cannot clear scan data; the repository clear method is not called.
- Administrator token can clear scan data.
- Constructor token cannot perform a review mutation through `bound_review_actor`.
- Reviewer token cannot perform a construction mutation through `bound_construction_actor`.
- Valid reviewer and constructor flows continue to work.

Run the focused tests first, then the complete backend suite. No source verifier may replace these behavioral tests.

## Safety And Rollback

The patch changes authorization checks only. It creates no migration and performs no production data write during development. Rollback is a code revert of the helper, three guard integrations, and their tests.
