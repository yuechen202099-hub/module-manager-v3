# Release Package And Hash SOP

## Purpose

Ensure the exact artifact uploaded to the server is reproducible, verified, and recorded.

## Standard Package

Production server packages are created under:

```text
build/server-release/module-manager-v2-server-<version>.zip
```

The old `build/client-release` path is for historical demo notes only and must not be used for production deployment.

## Build Command

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build-client-release.ps1 -Version 3.0.37
```

## Verification Commands

```powershell
.\.venv\Scripts\python.exe .\scripts\verify-client-release.py .\build\server-release\module-manager-v2-server-3.0.37.zip
Get-FileHash .\build\server-release\module-manager-v2-server-3.0.37.zip -Algorithm SHA256
```

## Static Asset Gate

After `npm run build`, verify that all `/vue/...` references in `v2-api/app/static/vue/index.html` exist and are tracked by git before committing.

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
