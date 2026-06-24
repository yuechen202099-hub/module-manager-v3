from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT_BOARD = ROOT / "v2-web" / "src" / "views" / "ProjectBoardView.vue"
SERVICES = ROOT / "v2-web" / "src" / "api" / "services.ts"
ROUTES = ROOT / "v2-api" / "app" / "api" / "routes" / "local_test.py"
STATE_REPOSITORY = ROOT / "v2-api" / "app" / "services" / "state_repository.py"


def main() -> int:
    project_board = PROJECT_BOARD.read_text(encoding="utf-8")
    services = SERVICES.read_text(encoding="utf-8")
    routes = ROUTES.read_text(encoding="utf-8")
    repository = STATE_REPOSITORY.read_text(encoding="utf-8")

    checks = [
        (
            "project board imports delete unmatched API",
            "deleteUnmatchedRecord," in project_board,
        ),
        (
            "project board exposes row delete handler",
            "async function deleteUnmatchedRow(row: UnmatchedRecord)" in project_board,
        ),
        (
            "unmatched table has manual delete button",
            "删除" in project_board and "@click=\"deleteUnmatchedRow(row)\"" in project_board,
        ),
        (
            "frontend service calls unmatched delete route",
            "export async function deleteUnmatchedRecord" in services
            and "/delete" in services,
        ),
        (
            "backend exposes unmatched delete route",
            '@router.post("/unmatched/{unmatched_id}/delete")' in routes,
        ),
        (
            "postgres unmatched payload keeps image URLs",
            'payload.get("image_urls")' in repository
            and '"photo_count": len(photo_urls)' in repository,
        ),
        (
            "postgres import tracks handled unmatched duplicate keys",
            "existing_unmatched_keys" in routes
            and "make_unmatched_duplicate_key" in routes,
        ),
    ]

    failed = [name for name, ok in checks if not ok]
    if failed:
        print("Unmatched replacement workflow verification failed:")
        for item in failed:
            print(f"- {item}")
        return 1

    print("Unmatched replacement workflow verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
