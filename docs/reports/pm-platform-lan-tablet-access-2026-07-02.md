# PM Platform LAN Tablet Access Report

Date: 2026-07-02

## Scope

This package makes the local platform reachable from a tablet on the same trusted LAN for review and field-style walkthroughs. It does not create a production deployment, public tunnel, version tag, release package, database migration, OSS write, or PostgreSQL write.

## Changed Behavior

- `scripts/start-platform-local.ps1` keeps default local-only binding at `127.0.0.1`.
- The script now accepts `-HostAddress 0.0.0.0` for explicit LAN listening.
- `HostAddress` is restricted to `127.0.0.1` or `0.0.0.0`.
- When LAN mode is enabled, the script prints a `LAN URL` such as:

```text
http://192.168.50.162:52131/platform-projects
```

## How To Use

From the project root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-platform-local.ps1 -Port 52131 -HostAddress 0.0.0.0 -Restart
```

Then open the printed `LAN URL` on a tablet connected to the same Wi-Fi/LAN.

Current verified LAN URL:

```text
http://192.168.50.162:52131/platform-projects
```

## Verification

Fresh verification on 2026-07-02:

- `.\.venv\Scripts\python.exe scripts\verify_platform_local_start_script.py`
  - RED before guard update: missing required snippet `LOCAL_HOST: --host 127.0.0.1`.
  - GREEN after update: `[OK] local platform start script is pinned to safe development paths.`
- `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-platform-local.ps1 -Port 52131 -HostAddress 0.0.0.0 -Restart`
  - Result: local service restarted in LAN mode.
- `Get-NetTCPConnection -LocalPort 52131 -State Listen`
  - Result: listener on `0.0.0.0:52131`.
- `Invoke-WebRequest http://127.0.0.1:52131/platform-projects`
  - Result: `HTTP 200`.
- `Invoke-WebRequest http://192.168.50.162:52131/platform-projects`
  - Result: `HTTP 200`.

## Safety And Rollback

- Default start mode remains local-only: `127.0.0.1`.
- LAN access is opt-in with `-HostAddress 0.0.0.0`.
- Use LAN mode only on a trusted private network.
- Windows firewall may need to allow Python/private-network access for tablets to reach the service.
- Rollback: run the script again without `-HostAddress 0.0.0.0`, or stop the local process. To revert the package, revert `scripts/start-platform-local.ps1`, `scripts/verify_platform_local_start_script.py`, this report, and related documentation.
