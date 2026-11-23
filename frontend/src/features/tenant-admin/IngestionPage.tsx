import { useQuery } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { adminApi } from '@/services/api/adminApi'
import { useRefreshInterval } from '@/hooks/useMisc'
import { useUrlState } from '@/hooks/useUrlState'
import { Button } from '@/components/ui/button'
import { Field, Select } from '@/components/ui/form'
import { DataTable } from '@/components/tables/DataTable'
import { QueryState } from '@/components/feedback/states'
import { KpiTile, PageHeader, StatusBadge } from '@/components/common/display'
import { StageTimeline } from '@/features/ingestion/JobTracker'
import type { IngestionJob } from '@/types/api'
import { formatDateTime, formatNumber, humanize } from '@/utils/format'
import { n, useTenantKey, useWrite } from './common'

const DEFAULTS = { status: '', job_type: '', offset: '0', limit: '25' }
const STATUSES = ['queued', 'running', 'retrying', 'failed', 'dead_letter', 'quarantined', 'succeeded', 'cancelled']

export default function IngestionPage() {
  const key = useTenantKey()
  const [st, set] = useUrlState(DEFAULTS)
  const refetch = useRefreshInterval(15_000) // auto-refresh every 15 s while visible
  const limit = Number(st.limit), offset = Number(st.offset)
  const sum = useQuery({ queryKey: key('admin', 'ingestion', 'summary'), queryFn: adminApi.ingestionSummary, refetchInterval: refetch })
  const jobs = useQuery({ queryKey: key('admin', 'ingestion', 'jobs', st), queryFn: ({ signal }) => adminApi.ingestionJobs({ status: st.status, job_type: st.job_type, limit, offset }, signal), refetchInterval: refetch, placeholderData: (p) => p })
  const retry = useWrite((id: string) => adminApi.retryJob(id), { invalidate: [['admin', 'ingestion']], success: 'Retry requested.' })
  const cancel = useWrite((id: string) => adminApi.cancelJob(id), { invalidate: [['admin', 'ingestion']], success: 'Job cancelled.' })
  const columns = useMemo<ColumnDef<IngestionJob, unknown>[]>(() => [
    { header: 'Status', cell: ({ row: { original: j } }) => <StatusBadge value={j.status} /> },
    { header: 'Type', cell: ({ row: { original: j } }) => humanize(j.job_type) },
    { header: 'Stages', cell: ({ row: { original: j } }) => <StageTimeline job={j} /> },
    { header: 'Attempts', cell: ({ row: { original: j } }) => `${j.attempt}/${j.max_attempts}` },
    { header: 'Error', cell: ({ row: { original: j } }) => j.error_code ? <span title={j.error_message ?? undefined}><code className="font-mono text-xs">{j.error_code}</code><span className="block max-w-xs truncate text-xs text-ink-muted">{j.error_message}</span></span> : '–' },
    { header: 'Queued', cell: ({ row: { original: j } }) => formatDateTime(j.queued_at) },
    { header: 'Document', cell: ({ row: { original: j } }) => <Link className="text-primary hover:underline" to={`/admin/documents/${j.document_id}`}>Open</Link> },
    { header: 'Actions', cell: ({ row: { original: j } }) => (
      <span className="flex gap-1">
        {['failed', 'dead_letter'].includes(j.status) && <Button size="sm" variant="secondary" loading={retry.isPending && retry.variables === j.job_id} onClick={() => retry.mutate(j.job_id)}>Retry</Button>}
        {['queued', 'retrying'].includes(j.status) && <Button size="sm" variant="ghost" onClick={() => cancel.mutate(j.job_id)}>Cancel</Button>}
        {j.status === 'quarantined' && <span className="text-xs text-ink-muted">Blocked by scan</span>}
      </span>) },
  ], [retry, cancel])
  return (
    <>
      <PageHeader title="Ingestion monitor" description="Refreshes every 15 seconds while this tab is visible." />
      <QueryState query={sum}>{(d) => (
        <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-6">
          {(['queued', 'running', 'retrying', 'failed', 'dead_letter', 'quarantined'] as const).map((k) => {
            const by = (d.by_status ?? d.counts ?? d) as Record<string, unknown>
            const v = n(by[k]) ?? n(d[k])
            return <KpiTile key={k} label={humanize(k)} value={formatNumber(v)} tone={['failed', 'dead_letter', 'quarantined'].includes(k) && (v ?? 0) > 0 ? 'danger' : undefined} />
          })}
        </div>)}</QueryState>
      <div className="mb-3 grid gap-2 sm:grid-cols-3">
        <Field label="Status">{(p) => <Select {...p} value={st.status} onChange={(e) => set({ status: e.target.value })}><option value="">All</option>{STATUSES.map((x) => <option key={x} value={x}>{humanize(x)}</option>)}</Select>}</Field>
        <Field label="Job type">{(p) => <Select {...p} value={st.job_type} onChange={(e) => set({ job_type: e.target.value })}><option value="">All</option><option value="ingest">Ingest</option><option value="reprocess">Reprocess</option><option value="reindex">Reindex</option><option value="purge">Purge</option></Select>}</Field>
      </div>
      <DataTable caption="Ingestion jobs" columns={columns} rows={jobs.data?.items} total={jobs.data?.total} limit={limit} offset={offset} loading={jobs.isFetching} error={jobs.error} onRetry={() => void jobs.refetch()}
        rowKey={(j) => j.job_id} onPage={(o, l) => set({ offset: String(o), limit: String(l) }, { keepOffset: true })} />
    </>
  )
}
