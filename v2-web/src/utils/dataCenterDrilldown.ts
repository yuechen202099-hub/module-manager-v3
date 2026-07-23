export type DataCenterDrilldownKind =
  | 'groups'
  | 'scanned_groups'
  | 'archived_groups'
  | 'barcode_eligible'
  | 'barcode_passed'
  | 'barcode_manual_queue'
  | 'barcode_ineligible'
  | 'unmatched_records'
  | 'exception_missing_photo'
  | 'unconstructed_unscanned'
  | 'terminal_all'
  | 'terminal_completed'
  | 'terminal_incomplete'
  | 'terminal_pending_archive'
  | 'terminal_archived'
  | 'installer_completed'

export interface DataCenterDrilldownContext {
  installer?: string
  dateFrom?: string
  dateTo?: string
  terminal?: string
  keyword?: string
}

type DataCenterDrilldownQuery = Record<string, string>

const BASE_GROUP_QUERY = { data_type: 'group' } as const
const DEFAULT_PAGE_QUERY = { page: '1', page_size: '20' } as const

function withContext(
  query: DataCenterDrilldownQuery,
  context: DataCenterDrilldownContext,
): DataCenterDrilldownQuery {
  const next = { ...query }
  const installer = String(context.installer || '').trim()
  const dateFrom = String(context.dateFrom || '').trim()
  const dateTo = String(context.dateTo || '').trim()
  const terminal = String(context.terminal || '').trim()
  const keyword = String(context.keyword || '').trim()
  if (installer) next.installer = installer
  if (dateFrom) next.date_from = dateFrom
  if (dateTo) next.date_to = dateTo
  if (terminal) next.terminal = terminal
  if (keyword) next.keyword = keyword
  return next
}

const BUILDERS: Record<
  DataCenterDrilldownKind,
  (context: DataCenterDrilldownContext) => DataCenterDrilldownQuery
> = {
  groups: () => ({ ...BASE_GROUP_QUERY }),
  scanned_groups: () => ({ ...BASE_GROUP_QUERY, construction_status: 'in_progress' }),
  archived_groups: () => ({ ...BASE_GROUP_QUERY, archive_status: 'archived' }),
  barcode_eligible: () => ({ ...BASE_GROUP_QUERY, classification_status: 'complete' }),
  barcode_passed: () => ({
    ...BASE_GROUP_QUERY,
    classification_status: 'complete',
    barcode_status: 'passed',
  }),
  barcode_manual_queue: () => ({
    ...BASE_GROUP_QUERY,
    classification_status: 'complete',
    barcode_status: 'manual',
  }),
  barcode_ineligible: () => ({ ...BASE_GROUP_QUERY, barcode_status: 'ineligible' }),
  unmatched_records: () => ({ data_type: 'unmatched' }),
  exception_missing_photo: () => ({ ...BASE_GROUP_QUERY, exception_status: 'open' }),
  unconstructed_unscanned: () => ({ ...BASE_GROUP_QUERY, construction_status: 'unconstructed' }),
  terminal_all: () => ({ ...BASE_GROUP_QUERY }),
  terminal_completed: () => ({ ...BASE_GROUP_QUERY, construction_status: 'completed' }),
  terminal_incomplete: () => ({ ...BASE_GROUP_QUERY, construction_status: 'in_progress' }),
  terminal_pending_archive: () => ({
    ...BASE_GROUP_QUERY,
    construction_status: 'completed',
    archive_status: 'pending',
  }),
  terminal_archived: () => ({ ...BASE_GROUP_QUERY, archive_status: 'archived' }),
  installer_completed: (context) => withContext(
    { ...BASE_GROUP_QUERY, construction_status: 'completed' },
    context,
  ),
}

export function buildDataCenterDrilldown(
  kind: DataCenterDrilldownKind,
  context: DataCenterDrilldownContext = {},
) {
  const builder = BUILDERS[kind]
  if (!builder) {
    throw new Error(`Unsupported data center drilldown kind: ${kind}`)
  }
  return {
    path: '/global-search',
    query: {
      ...builder(context),
      ...DEFAULT_PAGE_QUERY,
    },
  }
}
