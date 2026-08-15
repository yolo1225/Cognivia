const BEIJING_TIME_ZONE = 'Asia/Shanghai'

function parseApiDateTime(value?: string | null): Date | null {
  if (!value) return null
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value}Z`
  const date = new Date(normalized)
  return Number.isNaN(date.getTime()) ? null : date
}

function beijingParts(value?: string | null) {
  const date = parseApiDateTime(value)
  if (!date) return null
  const parts = new Intl.DateTimeFormat('zh-CN', {
    timeZone: BEIJING_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(date)
  return Object.fromEntries(parts.map((part) => [part.type, part.value]))
}

export function formatBeijingDateTime(value?: string | null) {
  const parts = beijingParts(value)
  if (!parts) return '-'
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}`
}

export function formatBeijingDate(value?: string | null) {
  const parts = beijingParts(value)
  if (!parts) return '-'
  return `${parts.year}-${parts.month}-${parts.day}`
}
