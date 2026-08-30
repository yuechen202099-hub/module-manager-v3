# V3.2.20 Device Display Hotfix Release Plan

## Goal

Publish the reviewed hotfix that shows one effective collector column and one effective module column, and makes the review form use the same effective identifiers.

## Contract

- Prefer trimmed construction collector and module identifiers when present.
- Fall back to the original collector and module identifiers when construction values are blank.
- Keep construction and source compatibility fields in the API contract while removing duplicate construction columns from the data-center table.
- Use effective identifiers for anomaly checks and anomaly evidence fingerprints.
- Keep the existing database head at `20260824_0016`; add no migration and rewrite no production business data.
- Perform no OSS write, camera request, or client-platform request during release verification.

## Release gates

1. Run the focused backend and frontend regressions plus the V3.2.20 source contract.
2. Build a source-bound package from a clean `production/V3/3.2.20` worktree.
3. Verify required and forbidden ZIP members, `SOURCE_COMMIT`, and local/server SHA256.
4. Create and verify a full production backup before cutover.
5. Wait for Uvicorn on `127.0.0.1:8000`, then verify health, authorization, pages, and effective device display.
6. Keep V3.2.19 as the rollback release and run retention in dry-run mode only.
