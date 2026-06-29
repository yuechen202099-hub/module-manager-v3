function compactDateTime(value) {
  if (!value) return '-'
  return String(value).replace('T', ' ').replace(/\.\d+.*$/, '').slice(0, 16)
}

function safeText(value, fallback = '-') {
  const clean = String(value || '').trim()
  return clean || fallback
}

module.exports = {
  compactDateTime,
  safeText
}
