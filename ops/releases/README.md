# Production Release Records

Every production deployment must have one file in this directory.

Use `V<version>.md`, for example `V3.0.37.md`.

Each record must include:

- user request,
- priority,
- branch and commit,
- package path,
- SHA256,
- tests and verification,
- subagent review result,
- production backup directory,
- production release directory,
- health/API/page checks,
- rollback target,
- remaining risks.
