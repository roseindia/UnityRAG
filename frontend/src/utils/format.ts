import { format, formatDistanceToNowStrict, isValid, parseISO } from 'date-fns'

const LOCALE = 'en-GB'

export function formatBytes(n?: number | null): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '–'
  if (n < 1024) return `${n} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let v = n / 1024
  let i = 0
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(v >= 10 ? 0 : 1)} ${units[i]}`
}

export function formatNumber(n?: number | null): string {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return '–'
  return new Intl.NumberFormat(LOCALE).format(Number(n))
}

export function formatCompact(n?: number | null): string {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return '–'
  return new Intl.NumberFormat(LOCALE, { notation: 'compact', maximumFractionDigits: 1 }).format(Number(n))
}

export function formatCost(n?: number | null): string {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return '–'
  return new Intl.NumberFormat(LOCALE, { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(Number(n))
}

export function formatPct(n?: number | null, digits = 1): string {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return '–'
  return `${Number(n).toFixed(digits)}%`
}

function toDate(v?: string | Date | null): Date | null {
  if (!v) return null
  const d = v instanceof Date ? v : parseISO(v)
  return isValid(d) ? d : null
}

/** Timestamps (UTC ISO) shown in the viewer's local zone. */
export function formatDateTime(v?: string | Date | null): string {
  const d = toDate(v)
  return d ? format(d, 'dd MMM yyyy HH:mm') : '–'
}

/** Effective dates are date-only: shown without time-zone conversion. */
export function formatDateOnly(v?: string | null): string {
  if (!v) return '–'
  const [y, m, day] = v.slice(0, 10).split('-').map(Number)
  if (!y || !m || !day) return '–'
  return format(new Date(y, m - 1, day), 'dd MMM yyyy')
}

export function timeAgo(v?: string | Date | null): string {
  const d = toDate(v)
  return d ? `${formatDistanceToNowStrict(d)} ago` : '–'
}

export function isoDate(d: Date): string {
  return format(d, 'yyyy-MM-dd')
}

const ACRONYMS = new Set(['ai', 'rag', 'pii', 'sso', 'mfa', 'url', 'api', 'id', 'ip', 'csv', 'pdf', 'rrf', 'fts', 'hnsw', 'oidc', 'ocr'])

export function humanize(s?: string | null): string {
  if (!s) return '–'
  const words = s.replace(/_/g, ' ').split(' ').map((w) => (ACRONYMS.has(w.toLowerCase()) ? w.toUpperCase() : w))
  const t = words.join(' ')
  return t.charAt(0).toUpperCase() + t.slice(1)
}

export function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s
}
