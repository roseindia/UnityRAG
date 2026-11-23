import { AlertTriangle, CheckCircle2, Info, OctagonAlert, Inbox } from 'lucide-react'
import type { ReactNode } from 'react'
import type { UseQueryResult } from '@tanstack/react-query'
import { ApiError, GENERIC_ERROR } from '@/services/api/errors'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/card'
import { CopyButton } from '@/components/common/CopyButton'
import { cn } from '@/utils/cn'

export function EmptyState({ title, description, action, icon }: { title: string; description?: string; action?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 px-4 py-10 text-center">
      <div className="text-ink-muted" aria-hidden>{icon ?? <Inbox className="h-8 w-8" />}</div>
      <p className="font-medium">{title}</p>
      {description && <p className="max-w-md text-sm text-ink-muted">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}

/** What happened, what to do, and the reference (NFR-094). No status codes, stack traces or SQL. */
export function ErrorState({ error, onRetry, title }: { error: unknown; onRetry?: () => void; title?: string }) {
  const api = error instanceof ApiError ? error : null
  const forbidden = api?.status === 403 || api?.status === 404
  return (
    <div role="alert" className="flex flex-col items-center gap-2 px-4 py-8 text-center">
      <OctagonAlert className="h-8 w-8 text-danger" aria-hidden />
      <p className="font-medium">{title ?? (forbidden ? 'Not available to you' : "We couldn't load this")}</p>
      <p className="max-w-md text-sm text-ink-muted">{api?.message ?? GENERIC_ERROR}</p>
      {api?.correlationId && (
        <p className="flex items-center gap-1 text-xs text-ink-muted">
          Reference: <code className="font-mono">{api.correlationId.slice(0, 8)}…{api.correlationId.slice(-4)}</code>
          <CopyButton text={api.correlationId} label="Copy reference" />
        </p>
      )}
      {onRetry && !forbidden && <Button variant="secondary" onClick={onRetry}>Try again</Button>}
    </div>
  )
}

const alertTones = {
  info: { cls: 'border-primary/30 bg-info-bg', Icon: Info },
  success: { cls: 'border-success/30 bg-success-bg', Icon: CheckCircle2 },
  warning: { cls: 'border-warning/30 bg-warning-bg', Icon: AlertTriangle },
  danger: { cls: 'border-danger/30 bg-danger-bg', Icon: OctagonAlert },
}

export function InlineAlert({ tone = 'info', title, children, className }: { tone?: keyof typeof alertTones; title?: string; children?: ReactNode; className?: string }) {
  const { cls, Icon } = alertTones[tone]
  return (
    <div role={tone === 'danger' ? 'alert' : 'status'} className={cn('flex gap-2 rounded-card border px-3 py-2 text-sm', cls, className)}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div>{title && <p className="font-medium">{title}</p>}{children && <div className={title ? 'mt-0.5' : ''}>{children}</div>}</div>
    </div>
  )
}

export function LoadingBlock({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-2 p-4" role="status" aria-live="polite" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => <Skeleton key={i} className="h-6 w-full" />)}
      <span className="sr-only">Loading</span>
    </div>
  )
}

/** Loading → error → empty → content for a query. */
export function QueryState<T>({ query, children, isEmpty, empty, rows }: {
  query: UseQueryResult<T>
  children: (data: T) => ReactNode
  isEmpty?: (d: T) => boolean
  empty?: ReactNode
  rows?: number
}) {
  if (query.isPending) return <LoadingBlock rows={rows} />
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />
  if (isEmpty?.(query.data)) return <>{empty ?? <EmptyState title="Nothing here yet" />}</>
  return <>{children(query.data)}</>
}

export function Banner({ tone = 'info', children, action }: { tone?: 'info' | 'warning' | 'danger'; children: ReactNode; action?: ReactNode }) {
  const c = tone === 'danger' ? 'bg-danger text-white' : tone === 'warning' ? 'bg-warning-bg text-warning' : 'bg-info-bg text-primary'
  return (
    <div role={tone === 'danger' ? 'alert' : 'status'} className={cn('flex flex-wrap items-center justify-between gap-2 px-4 py-2 text-sm font-medium', c)}>
      <span>{children}</span>{action}
    </div>
  )
}
