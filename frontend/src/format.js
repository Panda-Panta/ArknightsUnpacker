const dateTime = new Intl.DateTimeFormat('zh-CN', {
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
})

export function shortTime(value) {
  if (!Number.isFinite(value)) return '—'
  return dateTime.format(new Date(value * 1000)).replace(/\//g, '-')
}

export function fullTime(value) {
  if (!Number.isFinite(value)) return '未知'
  return new Date(value * 1000).toLocaleString('zh-CN', { hour12: false })
}

export function sizeText(value) {
  if (!Number.isFinite(value)) return '—'
  if (value < 1024) return value + ' B'
  const units = ['KB', 'MB', 'GB', 'TB']
  let amount = value / 1024
  let unit = 0
  while (amount >= 1024 && unit < units.length - 1) {
    amount /= 1024
    unit += 1
  }
  return amount.toFixed(2) + ' ' + units[unit]
}

export function sourceText(row) {
  return [row.source, row.status !== row.source ? row.status : null].filter(Boolean).join(' · ') || '—'
}

export const resourceColumns = [
  { key: 'name', label: '名称', minWidth: 190 },
  { key: 'category', label: '用途', minWidth: 102 },
  { key: 'extension', label: '类型', minWidth: 76 },
  { key: 'size', label: '大小', minWidth: 82 },
  { key: 'modified', label: '修改时间', minWidth: 112 },
  { key: 'created', label: '创建时间', minWidth: 112 },
  { key: 'observed', label: '首次观测', minWidth: 112 },
  { key: 'source', label: '状态 / 来源', minWidth: 110 },
]

export const objectColumns = [
  { key: 'name', label: '对象名称', minWidth: 214 },
  { key: 'type', label: '类型', minWidth: 110 },
  { key: 'size', label: '大小', minWidth: 88 },
  { key: 'id', label: '对象 ID', minWidth: 192 },
]

export function cellText(row, key) {
  if (key === 'size') return sizeText(row.size)
  if (['modified', 'created', 'observed'].includes(key)) return shortTime(row[key])
  if (key === 'extension' && row.kind === 'directory') return '文件夹'
  if (key === 'source') return sourceText(row)
  return row[key] || '—'
}
