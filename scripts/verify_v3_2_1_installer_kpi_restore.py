"""Executable behavior gate for the V3.2.1 installer KPI utility."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UTILITY = ROOT / "v2-web/src/utils/installerKpi.ts"
COMPONENT = ROOT / "v2-web/src/components/InstallerKpiDialog.vue"
BOARD = ROOT / "v2-web/src/views/ProjectBoardView.vue"
TYPESCRIPT = ROOT / "v2-web/node_modules/typescript/lib/typescript.js"


def run_utility_contract() -> dict[str, object]:
    assert UTILITY.exists(), "installerKpi.ts must exist"
    assert TYPESCRIPT.exists(), "local TypeScript runtime must exist"

    utility_source = UTILITY.read_text(encoding="utf-8")
    node_source = f"""
import {{ createRequire }} from 'node:module'
import {{ pathToFileURL }} from 'node:url'
import {{ writeFile }} from 'node:fs/promises'

const require = createRequire(import.meta.url)
const ts = require({json.dumps(str(TYPESCRIPT))})
const source = {json.dumps(utility_source)}
const output = ts.transpileModule(source, {{
  compilerOptions: {{ module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 }},
  fileName: 'installerKpi.ts',
}}).outputText
const modulePath = process.env.INSTALLER_KPI_MODULE
await writeFile(modulePath, output, 'utf8')
const mod = await import(pathToFileURL(modulePath).href + `?contract=${{Date.now()}}`)

const rows = [
  {{
    date: '2026-07-01', groupCount: 2, photoCount: 4, archivedCount: 1, exceptionCount: 1, unreviewedCount: 1,
    startAt: '2026-07-01T08:00:00', endAt: '2026-07-01T17:00:00', startTime: '08:00', endTime: '17:00',
    workDurationMinutes: 480, workDurationHours: 8, workDurationLabel: '8小时', efficiencyDurationMinutes: 450,
    efficiencyDurationHours: 7.5, efficiencyDurationLabel: '7小时30分钟', workDurationMinutesV2: 490,
    workDurationHoursV2: 8.17, workDurationLabelV2: '8小时10分钟', workDurationBaseMinutesV2: 480,
    workDurationDeltaMinutesV2: 10, denseBonusMinutesV2: 10,
    denseBonusWindowsV2: [{{ startAt: '2026-07-01T09:00:00', endAt: '2026-07-01T10:00:00', startTime: '09:00', endTime: '10:00', gapCount: 2, underThreeCount: 1, underFiveCount: 2, bonusMinutes: 10, rule: 'dense' }}],
    completionPerEffectiveHourV2: 0.25, weightedCompletionPerEffectiveHourV2: 0.3, workSpanMinutes: 540,
    workSpanLabel: '9小时', breakThresholdMinutes: 30, timepointCount: 3, completionCount: 2,
    completionPerEffectiveHour: 0.25, weightedCompletion: 2.4, weightedCompletionPerEffectiveHour: 0.3,
    attendanceWindowMinutes: 540, onlineMinutes: 500, countableOnlineMinutes: 480, onlineRatio: 0.89,
    baseOnlineCoefficient: 1, idlePenaltyCoefficient: 0.9, finalOnlineCoefficient: 0.9,
    fusedWorkDurationMinutes: 441, fusedWorkDurationHours: 7.35, fusedWorkDurationLabel: '7小时21分钟',
    fusedEfficiencyDurationMinutes: 420, fusedEfficiencyDurationHours: 7, fusedEfficiencyDurationLabel: '7小时',
    fusedWeightedCompletionPerEffectiveHour: 0.34,
    idleSegments: [{{ startAt: '2026-07-01T12:00:00', endAt: '2026-07-01T12:30:00', startTime: '12:00', endTime: '12:30', minutes: 30, hours: 0.5, free: true, penaltyCoefficient: 1 }}],
    freeIdleSegmentUsed: true, pendingNonIdleCount: 1, confirmedNonIdleCount: 2, onlineConfidence: 'high',
    hourlySegments: [{{ hour: 8, label: '08:00', minutes: 60, durationLabel: '1小时', efficiencyMinutes: 55, efficiencyDurationLabel: '55分钟', completionCount: 1, weightedCompletion: 1.2, completionPerEffectiveHour: 1, weightedCompletionPerEffectiveHour: 1.2, addressCount: 1, addresses: [{{ groupId: 'g1', meterNo: 'm1', terminal: 't1', address: '地址1', status: 'done', photoCount: 2, completedAt: '2026-07-01T08:30:00', completedTime: '08:30', addressClusterKey: 'a1', difficultyWeight: 1.2, difficultyLabel: '普通', difficultyReasons: ['距离'], clusterSize: 1 }}] }}],
    twoHourSegments: [{{ hour: 8, startHour: 8, endHour: 10, label: '08:00-10:00', minutes: 120, durationLabel: '2小时', efficiencyMinutes: 110, efficiencyDurationLabel: '1小时50分钟', completionCount: 1, weightedCompletion: 1.2, completionPerEffectiveHour: 0.5, weightedCompletionPerEffectiveHour: 0.6, addressCount: 1, addresses: [{{ groupId: 'g1', meterNo: 'm1', terminal: 't1', address: '地址1', status: 'done', photoCount: 2, completedAt: '2026-07-01T08:30:00', completedTime: '08:30', addressClusterKey: 'a1', difficultyWeight: 1.2, difficultyLabel: '普通', difficultyReasons: ['距离'], clusterSize: 1 }}] }}],
    exceptionGroups: [{{ groupId: 'e1', meterNo: 'em1', terminal: 'et1', address: '异常地址', status: 'exception', exceptionNote: '缺图', exceptionReasons: ['缺图'], photoCount: 0 }}],
  }},
  {{
    date: '2026-07-06', groupCount: 3, photoCount: 6, archivedCount: 2, exceptionCount: 0, unreviewedCount: 1,
    startAt: '2026-07-06T08:00:00', endAt: '2026-07-06T17:00:00', startTime: '08:00', endTime: '17:00', workDurationMinutes: 480, workDurationHours: 8, workDurationLabel: '8小时', efficiencyDurationMinutes: 460, efficiencyDurationHours: 7.67, efficiencyDurationLabel: '7小时40分钟', workDurationMinutesV2: 500, workDurationHoursV2: 8.33, workDurationLabelV2: '8小时20分钟', workDurationBaseMinutesV2: 480, workDurationDeltaMinutesV2: 20, denseBonusMinutesV2: 20, denseBonusWindowsV2: [{{ startAt: '2026-07-06T09:00:00', endAt: '2026-07-06T10:00:00', startTime: '09:00', endTime: '10:00', gapCount: 3, underThreeCount: 2, underFiveCount: 3, bonusMinutes: 20, rule: 'dense' }}], completionPerEffectiveHourV2: 0.36, weightedCompletionPerEffectiveHourV2: 0.42, workSpanMinutes: 540, workSpanLabel: '9小时', breakThresholdMinutes: 30, timepointCount: 4, completionCount: 3, completionPerEffectiveHour: 0.38, weightedCompletion: 3.5, weightedCompletionPerEffectiveHour: 0.44, attendanceWindowMinutes: 540, onlineMinutes: 510, countableOnlineMinutes: 490, onlineRatio: 0.91, baseOnlineCoefficient: 1, idlePenaltyCoefficient: 0.95, finalOnlineCoefficient: 0.95, fusedWorkDurationMinutes: 475, fusedWorkDurationHours: 7.92, fusedWorkDurationLabel: '7小时55分钟', fusedEfficiencyDurationMinutes: 450, fusedEfficiencyDurationHours: 7.5, fusedEfficiencyDurationLabel: '7小时30分钟', fusedWeightedCompletionPerEffectiveHour: 0.47, idleSegments: [{{ startAt: '2026-07-06T12:00:00', endAt: '2026-07-06T12:20:00', startTime: '12:00', endTime: '12:20', minutes: 20, hours: 0.33, free: true, penaltyCoefficient: 1 }}], freeIdleSegmentUsed: true, pendingNonIdleCount: 0, confirmedNonIdleCount: 3, onlineConfidence: 'high', hourlySegments: [{{ hour: 8, label: '08:00', minutes: 60, durationLabel: '1小时', efficiencyMinutes: 60, efficiencyDurationLabel: '1小时', completionCount: 1, weightedCompletion: 1.1, completionPerEffectiveHour: 1, weightedCompletionPerEffectiveHour: 1.1, addressCount: 1, addresses: [{{ groupId: 'g2', meterNo: 'm2', terminal: 't2', address: '地址2', status: 'done', photoCount: 2, completedAt: '2026-07-06T08:30:00', completedTime: '08:30', addressClusterKey: 'a2', difficultyWeight: 1.1, difficultyLabel: '普通', difficultyReasons: ['距离'], clusterSize: 1 }}] }}], twoHourSegments: [{{ hour: 8, startHour: 8, endHour: 10, label: '08:00-10:00', minutes: 120, durationLabel: '2小时', efficiencyMinutes: 115, efficiencyDurationLabel: '1小时55分钟', completionCount: 1, weightedCompletion: 1.1, completionPerEffectiveHour: 0.5, weightedCompletionPerEffectiveHour: 0.55, addressCount: 1, addresses: [{{ groupId: 'g2', meterNo: 'm2', terminal: 't2', address: '地址2', status: 'done', photoCount: 2, completedAt: '2026-07-06T08:30:00', completedTime: '08:30', addressClusterKey: 'a2', difficultyWeight: 1.1, difficultyLabel: '普通', difficultyReasons: ['距离'], clusterSize: 1 }}] }}], exceptionGroups: [{{ groupId: 'e2', meterNo: 'em2', terminal: 'et2', address: '异常地址2', status: 'exception', exceptionNote: '', exceptionReasons: [], photoCount: 0 }}],
  }},
  {{
    date: '2026-07-31', groupCount: 4, photoCount: 8, archivedCount: 3, exceptionCount: 2, unreviewedCount: 0,
    startAt: '2026-07-31T08:00:00', endAt: '2026-07-31T17:00:00', startTime: '08:00', endTime: '17:00', workDurationMinutes: 480, workDurationHours: 8, workDurationLabel: '8小时', efficiencyDurationMinutes: 440, efficiencyDurationHours: 7.33, efficiencyDurationLabel: '7小时20分钟', workDurationMinutesV2: 470, workDurationHoursV2: 7.83, workDurationLabelV2: '7小时50分钟', workDurationBaseMinutesV2: 480, workDurationDeltaMinutesV2: -10, denseBonusMinutesV2: 0, denseBonusWindowsV2: [{{ startAt: '2026-07-31T09:00:00', endAt: '2026-07-31T10:00:00', startTime: '09:00', endTime: '10:00', gapCount: 1, underThreeCount: 0, underFiveCount: 1, bonusMinutes: 0, rule: 'dense' }}], completionPerEffectiveHourV2: 0.51, weightedCompletionPerEffectiveHourV2: 0.6, workSpanMinutes: 540, workSpanLabel: '9小时', breakThresholdMinutes: 30, timepointCount: 5, completionCount: 4, completionPerEffectiveHour: 0.5, weightedCompletion: 4.6, weightedCompletionPerEffectiveHour: 0.58, attendanceWindowMinutes: 540, onlineMinutes: 480, countableOnlineMinutes: 450, onlineRatio: 0.83, baseOnlineCoefficient: 1, idlePenaltyCoefficient: 0.8, finalOnlineCoefficient: 0.8, fusedWorkDurationMinutes: 376, fusedWorkDurationHours: 6.27, fusedWorkDurationLabel: '6小时16分钟', fusedEfficiencyDurationMinutes: 350, fusedEfficiencyDurationHours: 5.83, fusedEfficiencyDurationLabel: '5小时50分钟', fusedWeightedCompletionPerEffectiveHour: 0.74, idleSegments: [{{ startAt: '2026-07-31T12:00:00', endAt: '2026-07-31T13:00:00', startTime: '12:00', endTime: '13:00', minutes: 60, hours: 1, free: false, penaltyCoefficient: 0.8 }}], freeIdleSegmentUsed: false, pendingNonIdleCount: 2, confirmedNonIdleCount: 2, onlineConfidence: 'medium', hourlySegments: [{{ hour: 8, label: '08:00', minutes: 60, durationLabel: '1小时', efficiencyMinutes: 50, efficiencyDurationLabel: '50分钟', completionCount: 1, weightedCompletion: 1.3, completionPerEffectiveHour: 1, weightedCompletionPerEffectiveHour: 1.3, addressCount: 1, addresses: [{{ groupId: 'g3', meterNo: 'm3', terminal: 't3', address: '地址3', status: 'done', photoCount: 2, completedAt: '2026-07-31T08:30:00', completedTime: '08:30', addressClusterKey: 'a3', difficultyWeight: 1.3, difficultyLabel: '困难', difficultyReasons: ['距离'], clusterSize: 1 }}] }}], twoHourSegments: [{{ hour: 8, startHour: 8, endHour: 10, label: '08:00-10:00', minutes: 120, durationLabel: '2小时', efficiencyMinutes: 100, efficiencyDurationLabel: '1小时40分钟', completionCount: 1, weightedCompletion: 1.3, completionPerEffectiveHour: 0.5, weightedCompletionPerEffectiveHour: 0.65, addressCount: 1, addresses: [{{ groupId: 'g3', meterNo: 'm3', terminal: 't3', address: '地址3', status: 'done', photoCount: 2, completedAt: '2026-07-31T08:30:00', completedTime: '08:30', addressClusterKey: 'a3', difficultyWeight: 1.3, difficultyLabel: '困难', difficultyReasons: ['距离'], clusterSize: 1 }}] }}], exceptionGroups: [{{ groupId: 'e3', meterNo: 'em3', terminal: 'et3', address: '异常地址3', status: 'exception', exceptionNote: '重复', exceptionReasons: ['重复'], photoCount: 0 }}],
  }},
]
const day = mod.filterInstallerKpiRows(rows, {{ mode: 'day', anchorDate: '2026-07-06' }}).map((row) => row.date)
const week = mod.filterInstallerKpiRows(rows, {{ mode: 'week', anchorDate: '2026-07-06' }}).map((row) => row.date)
const month = mod.filterInstallerKpiRows(rows, {{ mode: 'month', anchorDate: '2026-07-31' }}).map((row) => row.date)
const page = mod.paginateInstallerKpiRows(Array.from({{ length: 41 }}, (_, index) => index + 1), 99)
const gate = mod.createInstallerKpiRequestGate()
const first = gate.begin()
const second = gate.begin()
const csv = mod.buildInstallerKpiCsv('张三', [{{ ...rows[0], date: '=2+2', startTime: '08:00,"早班"', endTime: '17:00\\n次日' }}])
process.stdout.write(JSON.stringify({{
  day, week, month,
  ranges: {{ day: mod.installerKpiDateRange({{ mode: 'day', anchorDate: '2026-07-06' }}), week: mod.installerKpiDateRange({{ mode: 'week', anchorDate: '2026-07-06' }}), month: mod.installerKpiDateRange({{ mode: 'month', anchorDate: '2026-07-31' }}) }},
  page, stale: [gate.isCurrent(first), gate.isCurrent(second)],
  totals: mod.summarizeInstallerKpiRows(rows), duration: [mod.formatInstallerKpiDuration(61), mod.formatInstallerKpiDuration(-1)], decimal: [mod.formatInstallerKpiDecimal(1.2), mod.formatInstallerKpiDecimal(Number.NaN)],
  bar: [mod.installerKpiBarHeight(0, 120), mod.installerKpiBarHeight(1, 120), mod.installerKpiBarHeight(120, 120)], csv,
}}))
"""
    with tempfile.TemporaryDirectory() as directory:
        module_path = Path(directory) / f"installerKpi-{uuid.uuid4().hex}.mjs"
        completed = subprocess.run(
            ["node", "--input-type=module", "--eval", node_source],
            cwd=ROOT,
            check=True,
            capture_output=True,
            env={**os.environ, "INSTALLER_KPI_MODULE": str(module_path)},
        )
        return json.loads(completed.stdout)


def run_component_contract() -> None:
    component = COMPONENT.read_text(encoding="utf-8") if COMPONENT.exists() else ""
    assert component, "InstallerKpiDialog.vue must exist"
    for marker in [
        "fetchInstallerWorkload",
        "createInstallerKpiRequestGate",
        "filterInstallerKpiRows",
        "buildInstallerKpiCsv",
        "update:modelValue",
        "open-data-center",
        "每日工作量",
        "导出 KPI CSV",
        "查看原始资料",
        "2 小时效率分布",
        "地址清单",
        "异常明细",
    ]:
        assert marker in component, f"InstallerKpiDialog missing {marker}"
    for forbidden in ["useRouter", "useAuthStore", "createExportJob", "downloadExportJob"]:
        assert forbidden not in component, f"InstallerKpiDialog must not use {forbidden}"
    for marker in [
        'v-if="loadError"',
        '@click="loadWorkload"',
        "requestGate.invalidate()",
        "resetDrilldowns()",
        "function clearWorkload()",
        "clearWorkload()",
        ':disabled="!row.timepointCount"',
        ':disabled="!row.exceptionCount"',
    ]:
        assert marker in component, f"InstallerKpiDialog missing lifecycle behavior {marker}"
    assert component.count("append-to-body") >= 3, "InstallerKpiDialog nested dialogs must append-to-body"


def run_component_request_lifecycle_contract() -> None:
    component = COMPONENT.read_text(encoding="utf-8") if COMPONENT.exists() else ""
    assert component, "InstallerKpiDialog.vue must exist"
    assert "function invalidateWorkloadRequest()" in component, (
        "InstallerKpiDialog must invalidate a pending request before an installer changes, including A -> empty"
    )
    assert re.search(
        r"if \(!previous \|\| props\.installer !== previous\[1\] \|\| loadedInstaller\.value !== props\.installer\.trim\(\)\) \{\s*"
        r"invalidateWorkloadRequest\(\)\s*clearWorkload\(\)\s*void loadWorkload\(\)",
        component,
    ), "InstallerKpiDialog must invalidate before clearing/loading an A -> empty installer transition"
    assert "function isCurrentRequest(request: number, installer: string)" in component, (
        "InstallerKpiDialog must guard stale responses by request, installer, and visibility"
    )
    assert component.count("isCurrentRequest(request, installer)") >= 3, (
        "InstallerKpiDialog must guard success, stale failure, and loading cleanup with the same current-request predicate"
    )
    assert "if (!isCurrentRequest(request, installer)) return" in component, (
        "InstallerKpiDialog stale failure must not update loadError"
    )
    assert "if (isCurrentRequest(request, installer)) loading.value = false" in component, (
        "InstallerKpiDialog stale failure must not update loading"
    )


def run_parent_integration_contract() -> None:
    board = BOARD.read_text(encoding="utf-8") if BOARD.exists() else ""
    assert board, "ProjectBoardView.vue must exist"
    installer_row_match = re.search(
        r'<button\s+v-if="isAdmin"\s+class="installer-row installer-row-button"[\s\S]*?</button>',
        board,
    )
    assert installer_row_match, "ProjectBoardView must retain an admin installer row"
    installer_row_block = installer_row_match.group(0)

    assert "import InstallerKpiDialog" in board
    assert '@click="openInstallerKpi(item.installer)"' in board
    assert "<InstallerKpiDialog" in board
    assert ':installer="installerKpiInstaller"' in board
    assert ':scope="installerKpiScope"' in board
    assert '@open-data-center="openInstallerDataCenter"' in board
    assert "openDashboardDrilldown('installer_completed'" not in installer_row_block


def main() -> None:
    actual = run_utility_contract()
    run_component_contract()
    run_component_request_lifecycle_contract()
    run_parent_integration_contract()
    assert actual["day"] == ["2026-07-06"]
    assert actual["week"] == ["2026-07-06"]
    assert actual["month"] == ["2026-07-01", "2026-07-06", "2026-07-31"]
    assert actual["ranges"]["week"] == {"dateFrom": "2026-07-06", "dateTo": "2026-07-12"}
    assert actual["ranges"]["month"] == {"dateFrom": "2026-07-01", "dateTo": "2026-07-31"}
    assert actual["page"] == {"items": [41], "page": 3, "total": 41, "totalPages": 3}
    assert actual["stale"] == [False, True]
    assert actual["totals"] == {"groupCount": 9, "photoCount": 18, "archivedCount": 6, "exceptionCount": 3, "unreviewedCount": 2, "workDurationMinutes": 1440, "workDurationMinutesV2": 1460, "fusedWorkDurationMinutes": 1292, "completionCount": 9, "weightedCompletion": 10.5}
    assert actual["duration"] == ["1小时1分钟", "0分钟"]
    assert actual["decimal"] == ["1.2", "0"]
    assert actual["bar"] == [0, 8, 100]
    assert actual["csv"]["filename"] == "张三-daily-workload.csv"
    assert actual["csv"]["content"].startswith("\ufeff\"安装人员\",\"日期\"")
    assert "\"'=2+2\"" in actual["csv"]["content"]
    assert "\"08:00,\"\"早班\"\"\"" in actual["csv"]["content"]
    print("[OK] V3.2.1 installer KPI restore checks passed")


if __name__ == "__main__":
    main()
