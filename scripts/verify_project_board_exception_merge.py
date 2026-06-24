from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT_BOARD = ROOT / "v2-web" / "src" / "views" / "ProjectBoardView.vue"


def main() -> int:
    source = PROJECT_BOARD.read_text(encoding="utf-8")

    checks = [
        (
            "merged exception total computed",
            "const exceptionRiskTotal = computed(() => summary.value.exceptionGroups)" in source,
        ),
        (
            "project progress uses merged exception label",
            "<span>异常与缺照</span>" in source,
        ),
        (
            "project progress uses exception list count",
            "<strong>{{ exceptionRiskTotal }}</strong>" in source,
        ),
        (
            "missing-photo standalone progress card removed",
            "<span>缺照片</span>" not in source,
        ),
        (
            "exception dialog title matches merged entry",
            'title="异常与缺照"' in source,
        ),
        (
            "dialog stat label explains merged scope",
            "<span>异常/缺照</span>" in source,
        ),
    ]

    failed = [name for name, ok in checks if not ok]
    if failed:
        print("Project board exception merge verification failed:")
        for item in failed:
            print(f"- {item}")
        return 1

    print("Project board exception merge verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
