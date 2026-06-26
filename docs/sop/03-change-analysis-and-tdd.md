# Change Analysis And Test-First SOP

## Purpose

Prevent production fixes from becoming guesses. Every code change must start from the observed issue and end with repeatable verification evidence.

## Required Flow

1. Confirm current production baseline.
2. Reproduce or inspect the failure path.
3. Identify the root cause before editing.
4. Add or update a focused test or verification script.
5. Run the new test and confirm it fails when it should catch the issue.
6. Implement the smallest safe change.
7. Run targeted tests.
8. Run wider regression based on impact.
9. Record commands and results in the release record.

## Impact Analysis Checklist

- [ ] Backend API impact.
- [ ] Vue/page impact.
- [ ] Admin workflow impact.
- [ ] Construction workflow impact.
- [ ] Review/archive workflow impact.
- [ ] KPI/dashboard impact.
- [ ] PostgreSQL/JSON state parity impact.
- [ ] File/OSS/upload impact.
- [ ] Auth/session impact.

## Minimum Verification By Change Type

| Change | Required Verification |
| --- | --- |
| Backend service/API | Targeted pytest plus relevant API tests |
| Vue UI | `npm run build` and targeted JS/verifier script |
| Release notes/version | release-note verifier and system status test |
| Static assets | Vue build plus asset-reference check |
| Deployment scripts | dry-run or syntax/read-only validation |
| Data repair | backup, dry-run, row counts, rollback plan |
