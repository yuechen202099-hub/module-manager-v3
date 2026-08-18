from __future__ import annotations

MESSAGE = (
    "This migration entry is retired. Use migrate_external_photos_to_oss.py "
    "with an explicit mode, migration id, and source-host allowlist."
)


def main() -> int:
    raise SystemExit(MESSAGE)


if __name__ == "__main__":
    main()
