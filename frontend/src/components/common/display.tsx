import type { ReactNode } from 'react'
import { Badge, Card, type Tone } from '@/components/ui/card'
import { humanize } from '@/utils/format'
import { cn } from '@/utils/cn'

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-xl">{title}</h1>
        {description && <p className="mt-0.5 text-sm text-ink-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

const STATUS_TONE: Record<string, Tone> = {
  active: 'success', published: 'success', succeeded: 'success', completed: 'success', up: 'success', healthy: 'success', approved: 'success', resolved: 'success', answered: 'success', passed: 'success', high: 'success', ok: 'success', enabled: 'success', success: 'success',
  trial: 'info', draft: 'neutral', new: 'info', queued: 'info', running: 'info', processing: 'info', in_review: 'info', triaged: 'info', in_progress: 'info', proposed: 'info', medium: 'warning',
  retrying: 'warning', suspended: 'warning', superseded: 'warning', deprecated: 'warning', degraded: 'warning', needs_review: 'warning', warning: 'warning', low: 'warning', archived: 'neutral', expired: 'warning',
  failed: 'danger', dead_letter: 'danger', quarantined: 'danger', withdrawn: 'danger', down: 'danger', inactive: 'neutral', deactivated: 'danger', blocked: 'danger', rejected: 'danger', critical: 'danger', error: 'danger', disabled: 'neutral', cancelled: 'neutral', abstained: 'neutral', none: 'neutral',
}

/** Status is shown as text as well as colour, so colour is never the only carrier of meaning. */
export function StatusBadge({ value, tone }: { value?: string | null; tone?: Tone }) {
  if (!value) return <span className="text-ink-muted">–</span>
  return <Badge tone={tone ?? STATUS_TONE[value.toLowerCase()] ?? 'neutral'}>{humanize(value)}</Badge>
}

export function KpiTile({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: 'danger' | 'warning' }) {
  return (
    <Card className="p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">{label}</p>
      <p className={cn('mt-1 text-2xl font-semibold', tone === 'danger' && 'text-danger', tone === 'warning' && 'text-warning')}>{value}</p>
      {sub && <p className="mt-0.5 text-xs text-ink-muted">{sub}</p>}
    </Card>
  )
}

/** Amber from 80 %, red from 100 % (NFR-106). */
export function QuotaBar({ label, used, limit, format = (n: number) => String(n) }: { label: string; used: number; limit: number; format?: (n: number) => string }) {
  const pct = limit ? Math.min(100, Math.round((used / limit) * 100)) : 100
  const tone = pct >= 100 ? 'bg-danger' : pct >= 80 ? 'bg-warning' : 'bg-primary'
  const state = pct >= 100 ? 'limit reached' : pct >= 80 ? 'near limit' : 'ok'
  return (
    <div>
      <div className="mb-1 flex justify-between text-xs">
        <span className="font-medium">{label}</span>
        <span className="text-ink-muted">{format(used)} / {format(limit)} ({pct}% – {state})</span>
      </div>
      <div className="h-2 overflow-hidden rounded-pill bg-line" role="progressbar" aria-label={label} aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <div className={cn('h-full', tone)} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

export function KeyValueList({ items }: { items: { label: string; value: ReactNode }[] }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
      {items.map((i) => (
        <div key={i.label} className="min-w-0">
          <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">{i.label}</dt>
          <dd className="break-words">{i.value ?? '–'}</dd>
        </div>
      ))}
    </dl>
  )
}

export function JsonViewer({ value }: { value: unknown }) {
  return (
    // Scrollable region: focusable so keyboard users can scroll it (WCAG 2.1.1).
    // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
    <pre className="max-h-96 overflow-auto rounded-control bg-canvas p-3 font-mono text-xs" tabIndex={0} aria-label="JSON detail">
      {JSON.stringify(value, null, 2)}
    </pre>
  )
}

export function Mono({ children }: { children: ReactNode }) {
  return <span className="font-mono text-xs">{children}</span>
}
