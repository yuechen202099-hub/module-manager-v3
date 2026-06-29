const PHOTO_SLOTS = [
  { key: 'before_box', label: '改造前照片', required: true },
  { key: 'collector_barcode', label: '采集器照片', required: false },
  { key: 'module_meter', label: '模块与电表照片', required: true },
  { key: 'after_box', label: '改造后照片', required: true }
]

const GROUP_FILTERS = [
  { key: 'todo', label: '待施工' },
  { key: 'draft', label: '待上传' },
  { key: 'exception', label: '异常' },
  { key: 'uploaded', label: '已上传' },
  { key: 'all', label: '全部' }
]

const GROUP_STATUS_LABELS = {
  todo: '待施工',
  draft: '待上传',
  ready: '待上传',
  editing: '待采集',
  unconstructed: '待施工',
  constructed: '已施工',
  scanned: '已采集',
  uploaded: '已上传',
  exception: '异常',
  pending: '待审核',
  unreviewed: '待审核',
  incomplete: '待补充',
  approved: '已通过',
  unmatched: '无工单'
}

function groupStatusLabel(status) {
  const key = String(status || '').toLowerCase()
  return GROUP_STATUS_LABELS[key] || status || '待施工'
}

module.exports = {
  PHOTO_SLOTS,
  GROUP_FILTERS,
  GROUP_STATUS_LABELS,
  groupStatusLabel
}
