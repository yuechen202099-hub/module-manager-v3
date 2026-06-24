from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAIL: {message}")


def between(text: str, start: str, end: str) -> str:
    start_index = text.index(start)
    end_index = text.index(end, start_index)
    return text[start_index:end_index]


def main() -> None:
    project_board = read("v2-web/src/views/ProjectBoardView.vue")
    claim_tasks = read("v2-web/src/views/ClaimTasksView.vue")
    services = read("v2-web/src/api/services.ts")
    routes = read("v2-api/app/api/routes/local_test.py")
    repository = read("v2-api/app/services/state_repository.py")

    board_load = between(project_board, "async function loadBoard()", "async function exportExceptionRows()")
    claim_load = between(claim_tasks, "async function loadTasks", "function refreshTasks()")
    claim_mounted = between(claim_tasks, "onMounted(() =>", "onUnmounted")
    postgres_repository = repository[repository.index("class PostgresStateRepository") :]
    postgres_status = between(
        postgres_repository,
        "    def task_status(self) -> dict[str, Any]:",
        "    def installer_daily_workload",
    )

    checks = [
        (
            "project board uses lightweight task status instead of full task list",
            "fetchTaskStatus()" in board_load and "fetchTasks()" not in board_load,
        ),
        (
            "project board subscribes to authenticated server-pushed refresh stream",
            "fetch(boardEventsUrl('project-board')" in project_board and "boardEventHeaders()" in project_board,
        ),
        (
            "project board fallback interval is 15 minutes",
            "BOARD_REFRESH_INTERVAL_MS = 15 * 60 * 1000" in project_board,
        ),
        (
            "claim page checks task status before fetching full tasks",
            "fetchTaskStatus()" in claim_load and claim_load.index("fetchTaskStatus()") < claim_load.index("fetchTasks()"),
        ),
        (
            "claim page caches tasks for fast first paint",
            "sessionStorage.getItem(claimTasksCacheKey())" in claim_tasks
            and "sessionStorage.setItem(" in claim_tasks,
        ),
        (
            "claim page no longer performs ten second full refresh",
            "10000" not in claim_tasks and "TASK_STATUS_REFRESH_INTERVAL_MS" in claim_mounted,
        ),
        (
            "backend exposes lightweight task status route",
            '@router.get("/tasks/status")' in routes and "state_repository().task_status()" in routes,
        ),
        (
            "backend exposes SSE board event stream",
            '@router.get("/events")' in routes
            and "StreamingResponse" in routes
            and 'media_type="text/event-stream"' in routes
            and "BOARD_EVENT_INTERVAL_SECONDS = 15 * 60" in routes,
        ),
        (
            "postgres task status avoids address string aggregation",
            "address_search_text" not in postgres_status and "string_agg" not in postgres_status,
        ),
        (
            "frontend service exposes task status and authenticated event helpers",
            "export async function fetchTaskStatus()" in services
            and "export function boardEventHeaders()" in services,
        ),
    ]
    failed = [name for name, ok in checks if not ok]
    if failed:
        print("Board refresh performance verification failed:")
        for item in failed:
            print(f"- {item}")
        raise SystemExit(1)
    print("Board refresh performance verification passed.")


if __name__ == "__main__":
    main()
