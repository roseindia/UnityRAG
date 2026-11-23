import { useQuery } from '@tanstack/react-query'
import { Check, Circle, Loader2, X } from 'lucide-react'
import { documentApi } from '@/services/api/documentApi'
import { usePageVisible } from '@/hooks/useMisc'
import { StatusBadge } from '@/components/common/display'
import { cn } from '@/utils/cn'
import type { IngestionJob } from '@/types/api'

export const TERMINAL = ['succeeded', 'failed', 'quarantined', 'dead_letter', 'cancelled']
export const STAGES = ['queued', 'malware_scan', 'parse', 'chunk', 'embed', 'publish'] as const
const STAGE_LABEL: Record<string, string> = { queued: 'Queued', malware_scan: 'Security scan', parse: 'Parsing', chunk: 'Chunking', embed: 'Embedding', publish: 'Indexing' }

/** Stage timeline: the actual status returned by the backend; uploaded never means ingested. */
export function StageTimeline({ job }: { job: Pick<IngestionJob, 'status' | 'stage'> }) {
  const current = Math.max(0, STAGES.indexOf((job.stage ?? 'queued') as (typeof STAGES)[number]))
  const failed = ['failed', 'quarantined', 'dead_letter', 'cancelled'].includes(job.status)
  const done = job.status === 'succeeded'
  return (
    <ol className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs" aria-label="Ingestion stages">
      {STAGES.map((s, i) => {
        const state = done || i < current ? 'done' : i === current ? (failed ? 'failed' : 'active') : 'todo'
        return (
          <li key={s} className={cn('flex items-center gap-1', state === 'todo' && 'text-ink-muted', state === 'failed' && 'text-danger', state === 'done' && 'text-success')}>
            {state === 'done' ? <Check className="h-3 w-3" aria-hidden /> : state === 'failed' ? <X className="h-3 w-3" aria-hidden /> : state === 'active' ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden /> : <Circle className="h-3 w-3" aria-hidden />}
            <span>{STAGE_LABEL[s]}</span><span className="sr-only">{state}</span>
          </li>
        )
      })}
    </ol>
  )
}

/** Poll 2 s, then 4 s, then 8 s (capped at 15 s) until terminal; pauses while the tab is hidden (Design Document 6.6). */
const POLL_STEPS_MS = [2_000, 2_000, 4_000, 4_000, 8_000, 8_000, 15_000]

/** Delay before the next poll, derived from how many updates the query has had (not from render count). */
export function pollDelay(updates: number): number {
  return POLL_STEPS_MS[Math.min(Math.max(updates - 1, 0), POLL_STEPS_MS.length - 1)]
}

export function useJob(jobId: string | undefined) {
  const visible = usePageVisible()
  return useQuery({
    queryKey: ['ingestion', 'job', jobId],
    queryFn: ({ signal }) => documentApi.job(jobId!, signal),
    enabled: !!jobId, staleTime: 0,
    refetchInterval: (q) => {
      const st = q.state.data?.status
      if (st && TERMINAL.includes(st)) return false
      if (!visible) return false
      return pollDelay(q.state.dataUpdateCount)
    },
  })
}

export function JobTracker({ jobId }: { jobId: string }) {
  const q = useJob(jobId)
  const j = q.data
  if (q.isError) return <p className="text-xs text-danger">Status unavailable. {(q.error as Error).message}</p>
  if (!j) return <p className="text-xs text-ink-muted">Waiting for the first status…</p>
  return (
    <div className="space-y-1" aria-live="polite">
      <div className="flex items-center gap-2"><StatusBadge value={j.status} />{j.attempt > 1 && <span className="text-xs text-ink-muted">attempt {j.attempt} of {j.max_attempts}</span>}</div>
      <StageTimeline job={j} />
      {j.status === 'quarantined' && <p className="text-xs text-danger">The file was blocked by security scanning. It cannot be retried.</p>}
      {['failed', 'dead_letter'].includes(j.status) && <p className="text-xs text-danger">Processing failed{j.error_code ? ` (${j.error_code})` : ''}. Contact an administrator, who can retry. {j.correlation_id && <>Reference: <code className="font-mono">{j.correlation_id.slice(0, 8)}…</code></>}</p>}
    </div>
  )
}
