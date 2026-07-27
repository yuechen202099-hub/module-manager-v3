import type { InstallerWorkloadRow } from '@/api/types'

export type InstallerKpiScopeMode = 'all' | 'day' | 'week' | 'month'
export type InstallerKpiScope = { mode: InstallerKpiScopeMode; anchorDate: string }
export type InstallerKpiDateRange = { dateFrom?: string; dateTo?: string }
export type InstallerKpiTotals = {
  groupCount: number
  photoCount: number
  archivedCount: number
  exceptionCount: number
  unreviewedCount: number
  workDurationMinutes: number
  workDurationMinutesV2: number
  fusedWorkDurationMinutes: number
  completionCount: number
  weightedCompletion: number
}

export const INSTALLER_KPI_PAGE_SIZE = 20

function localDate(value: string) {
  return new Date(`${value}T00:00:00`)
}

function formatLocalDate(value: Date) {
  return [
    value.getFullYear(),
    String(value.getMonth() + 1).padStart(2, '0'),
    String(value.getDate()).padStart(2, '0'),
  ].join('-')
}

function shiftDate(value: string, days: number) {
  const result = localDate(value)
  result.setDate(result.getDate() + days)
  return formatLocalDate(result)
}

export function installerKpiDateRange(scope: InstallerKpiScope): InstallerKpiDateRange {
  if (scope.mode === 'all' || !scope.anchorDate) return {}
  if (scope.mode === 'day') return { dateFrom: scope.anchorDate, dateTo: scope.anchorDate }
  if (scope.mode === 'week') return { dateFrom: scope.anchorDate, dateTo: shiftDate(scope.anchorDate, 6) }
  const start = localDate(`${scope.anchorDate.slice(0, 7)}-01`)
  const end = new Date(start)
  end.setMonth(end.getMonth() + 1)
  end.setDate(0)
  return { dateFrom: formatLocalDate(start), dateTo: formatLocalDate(end) }
}

export function filterInstallerKpiRows(rows: InstallerWorkloadRow[], scope: InstallerKpiScope) {
  const { dateFrom, dateTo } = installerKpiDateRange(scope)
  if (!dateFrom || !dateTo) return [...rows]
  return rows.filter((row) => Boolean(row.date) && row.date >= dateFrom && row.date <= dateTo)
}

export function paginateInstallerKpiRows<T>(rows: T[], requestedPage: number, pageSize = INSTALLER_KPI_PAGE_SIZE) {
  const safePageSize = Math.max(1, Math.trunc(Number(pageSize) || INSTALLER_KPI_PAGE_SIZE))
  const total = rows.length
  const totalPages = Math.max(1, Math.ceil(total / safePageSize))
  const page = Math.min(totalPages, Math.max(1, Math.trunc(Number(requestedPage) || 1)))
  const start = (page - 1) * safePageSize
  return { items: rows.slice(start, start + safePageSize), page, total, totalPages }
}

export function createInstallerKpiRequestGate() {
  let serial = 0
  return {
    begin: () => ++serial,
    invalidate: () => { serial += 1 },
    isCurrent: (candidate: number) => candidate === serial,
  }
}

export function summarizeInstallerKpiRows(rows: InstallerWorkloadRow[]): InstallerKpiTotals {
  return rows.reduce<InstallerKpiTotals>(
    (total, row) => ({
      groupCount: total.groupCount + row.groupCount,
      photoCount: total.photoCount + row.photoCount,
      archivedCount: total.archivedCount + row.archivedCount,
      exceptionCount: total.exceptionCount + row.exceptionCount,
      unreviewedCount: total.unreviewedCount + row.unreviewedCount,
      workDurationMinutes: total.workDurationMinutes + row.workDurationMinutes,
      workDurationMinutesV2: total.workDurationMinutesV2 + row.workDurationMinutesV2,
      fusedWorkDurationMinutes: total.fusedWorkDurationMinutes + row.fusedWorkDurationMinutes,
      completionCount: total.completionCount + row.completionCount,
      weightedCompletion: total.weightedCompletion + row.weightedCompletion,
    }),
    {
      groupCount: 0,
      photoCount: 0,
      archivedCount: 0,
      exceptionCount: 0,
      unreviewedCount: 0,
      workDurationMinutes: 0,
      workDurationMinutesV2: 0,
      fusedWorkDurationMinutes: 0,
      completionCount: 0,
      weightedCompletion: 0,
    },
  )
}

export function formatInstallerKpiDuration(minutes: number) {
  const safe = Math.max(0, Math.round(Number(minutes) || 0))
  const hours = Math.floor(safe / 60)
  const rest = safe % 60
  if (hours && rest) return `${hours}小时${rest}分钟`
  if (hours) return `${hours}小时`
  return `${rest}分钟`
}

export function formatInstallerKpiDecimal(value: number, digits = 2) {
  if (!Number.isFinite(Number(value))) return '0'
  return Number(value).toFixed(digits).replace(/\.?0+$/, '')
}

export function installerKpiBarHeight(minutes: number, maximum: number) {
  const value = Math.max(0, Number(minutes) || 0)
  const ceiling = Math.max(1, Number(maximum) || 1)
  if (!value) return 0
  return Math.max(8, Math.min(100, Math.round((value / ceiling) * 100)))
}

function csvCell(value: unknown) {
  const text = String(value ?? '')
  const safe = /^[=+\-@]/.test(text.trimStart()) ? `'${text}` : text
  return `"${safe.replace(/"/g, '""')}"`
}

export function buildInstallerKpiCsv(installer: string, rows: InstallerWorkloadRow[]) {
  const header = [
    '安装人员', '日期', '开工时间', '收工时间', '有效工时', '补偿分钟', '考勤跨度',
    '有效时间点', '完成量', '每小时完成量', '难度加权完成量', '难度加权效率',
    '资料组数', '照片数', '已归档', '异常', '未审核',
  ]
  const body = rows.map((row) => [
    installer, row.date, row.startTime || '-', row.endTime || '-',
    row.workDurationLabel || formatInstallerKpiDuration(row.workDurationMinutes),
    row.denseBonusMinutesV2, row.workSpanLabel || formatInstallerKpiDuration(row.workSpanMinutes),
    row.timepointCount, row.completionCount, row.completionPerEffectiveHour,
    row.weightedCompletion, row.weightedCompletionPerEffectiveHour,
    row.groupCount, row.photoCount, row.archivedCount, row.exceptionCount, row.unreviewedCount,
  ])
  const filenameBase = (installer || 'installer')
    .replace(/[<>:"/\\\\|?*\u0000-\u001f]/g, '_')
    .replace(/[. ]+$/g, '') || 'installer'
  return {
    filename: `${filenameBase}-daily-workload.csv`,
    content: `\uFEFF${[header, ...body].map((row) => row.map(csvCell).join(',')).join('\r\n')}`,
  }
}
