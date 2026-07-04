from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "start-platform-local.ps1"


REQUIRED_SNIPPETS = {
    "APP_ENV": "$env:APP_ENV = \"local\"",
    "DEMO_AUTH_ENABLED": "$env:DEMO_AUTH_ENABLED = \"true\"",
    "STATE_BACKEND": "$env:STATE_BACKEND = \"json\"",
    "STORAGE_BACKEND": "$env:STORAGE_BACKEND = \"local\"",
    "PROJECT_DRAFTS_PATH": "$env:PLATFORM_PROJECT_DRAFTS_PATH =",
    "LOCAL_STATE_PATH": "$env:LOCAL_SIMULATION_STATE_PATH =",
    "HOST_ADDRESS_PARAM": '[string]$HostAddress = "127.0.0.1"',
    "HOST_ADDRESS_VALIDATE_SET": '[ValidateSet("127.0.0.1", "0.0.0.0")]',
    "UVICORN_HOST_ADDRESS": "--host $HostAddress",
    "LAN_HOST": '$HostAddress -eq "0.0.0.0"',
    "LAN_IP_DISCOVERY": "Get-NetIPAddress -AddressFamily IPv4",
    "LAN_URL_OUTPUT": 'LAN URL: http://$lanIp`:$Port/platform-projects',
    "UVICORN_COMMAND": "\"uvicorn\"",
    "UVICORN_APP": "\"app.main:app\"",
    "V2_API_WORKDIR": "$ApiDir = Join-Path $Root \"v2-api\"",
    "PYTHON_VENV": ".venv",
    "TERMINAL_DEMO_SEED": "seed-platform-terminal-demo.py",
    "TERMINAL_REVIEW_SAMPLE": "--with-review-sample",
    "DEFAULT_TEAM_SEED": "--team-id default-team",
    "DEMO_TEAM_SEED": "--team-id demo-team",
}


FORBIDDEN_SNIPPETS = (
    "OSS_ACCESS_KEY_ID",
    "OSS_ACCESS_KEY_SECRET",
    "postgresql+psycopg://",
    "production/V3",
)


def main() -> int:
    if not SCRIPT.exists():
        print(f"[FAIL] Missing local platform start script: {SCRIPT}")
        return 1
    source = SCRIPT.read_text(encoding="utf-8")
    failures: list[str] = []
    for name, snippet in REQUIRED_SNIPPETS.items():
        if snippet not in source:
            failures.append(f"missing required snippet {name}: {snippet}")
    for snippet in FORBIDDEN_SNIPPETS:
        if snippet in source:
            failures.append(f"forbidden production-sensitive snippet present: {snippet}")
    if "Stop-Process" in source and "-Restart" not in source:
        failures.append("Stop-Process must be gated behind the explicit -Restart option")
    if "--host 0.0.0.0" in source:
        failures.append("LAN binding must stay opt-in through -HostAddress, not hard-coded")
    if failures:
        for failure in failures:
            print(f"[FAIL] {failure}")
        return 1
    print("[OK] local platform start script is pinned to safe development paths.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
