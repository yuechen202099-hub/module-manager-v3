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
    claim = read("v2-web/src/views/ClaimTasksView.vue")
    task_hall = read("v2-web/src/views/TaskHallView.vue")
    app_layout = read("v2-web/src/layouts/AppLayout.vue")
    workspace = read("v2-web/src/stores/workspace.ts")
    main_css = read("v2-web/src/styles/main.css")

    require("handleTaskMoreCommand" in claim, "claim task card should route secondary actions through a More menu")
    require("<ElDropdown" in claim and "MoreFilled" in claim, "claim task card should render a More dropdown")
    require('class="task-export-row"' not in claim, "claim task card should not keep the export row expanded")
    require('导出范围：全部' in claim and '暂存释放' in claim, "claim More menu should keep export scope and release actions")
    require(".native-claim-page .task-card-actions .el-dropdown" in main_css, "claim dropdown button should be width-aligned")

    require("handleReviewMoreCommand" in task_hall, "review workbench should route secondary actions through a More menu")
    require("review-action-cluster" in task_hall, "review action row should be grouped into compact clusters")
    require('command="reset"' in task_hall and 'command="export-exceptions"' in task_hall, "review More menu should keep risk and export actions")

    load_tasks = between(task_hall, "async function loadTasks()", "function scheduleFieldTasksWarmup()")
    require("scheduleFieldTasksWarmup()" in load_tasks, "task hall should defer field task loading from terminal review first paint")
    require("void loadFieldTasks()" not in load_tasks, "task hall loadTasks should not eagerly fetch field task lists")
    require("if (activeTaskMode.value !== 'terminal') await loadFieldTasks(true)" in task_hall, "background refresh should only reload field tasks while field mode is open")

    require("void workspace.loadProjects()" in app_layout, "layout should only load project summary on app mount")
    require("async loadProjects()" in workspace, "workspace store should expose lightweight project loading")

    print("action consolidation and first-load checks passed")


if __name__ == "__main__":
    main()
