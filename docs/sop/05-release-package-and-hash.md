# Release Package And Hash SOP

## Purpose

Ensure the exact artifact uploaded to the server is reproducible, verified, and recorded.

## Standard Package

Production server packages are created under:

```text
build/server-release/module-manager-v2-server-<version>.zip
```

Historical client-demo package instructions are not part of the production workflow. Production deployment uses only the server-release package.

## Build Command

Generate the report only against an isolated service listening on `localhost` or `127.0.0.1`. The report must be generated from and verified against the exact commit being packaged:

```powershell
$sourceCommit = (git rev-parse HEAD).Trim().ToLowerInvariant()
.\.venv\Scripts\python.exe .\v2-api\scripts\verify_task_review_performance.py --base-url http://127.0.0.1:<port> --output .\outputs\performance\v<version>-task-review.json --source-commit $sourceCommit
.\.venv\Scripts\python.exe .\v2-api\scripts\verify_v3_1_release.py --repo-root . --performance-report .\outputs\performance\v<version>-task-review.json --expected-source-commit $sourceCommit
powershell -ExecutionPolicy Bypass -File .\scripts\build-client-release.ps1 -Version <version> -PerformanceReport .\outputs\performance\v<version>-task-review.json
```

Missing evidence, a non-local URL, empty route data, invalid pagination or serialization evidence, less than 60 seconds of sampling, a changed cache instance, failed thresholds, or a source commit mismatch blocks both acceptance and packaging.

## Verification Commands

```powershell
.\.venv\Scripts\python.exe .\scripts\verify-client-release.py .\build\server-release\module-manager-v2-server-<version>.zip --expected-source-commit $sourceCommit
Get-FileHash .\build\server-release\module-manager-v2-server-<version>.zip -Algorithm SHA256
```

## Static Asset Gate

After `npm run build`, verify that all `/vue/...` references in `v2-api/app/static/vue/index.html` exist and are tracked by git before committing.
The build must emit `v2-api/app/static/vue/version.json` from the single `v2-web/src/version.json` source. Package verification must parse that JSON artifact and the exact version marker in the module entry bundle referenced by `index.html`, then reconcile them with the manifest Version, Vue title, AGENTS candidate markers, and release record; arbitrary strings or markers in unrelated chunks do not count.

## Dependency Gate

- Production-only newly introduced dependencies should be pinned when practical.
- Server install logs must be checked for successful installation.
- Any dependency that cannot install on the server blocks release.

## Release Record Required Fields

- package path,
- SHA256,
- commit,
- build command,
- package verification result,
- server-side SHA256 result.
