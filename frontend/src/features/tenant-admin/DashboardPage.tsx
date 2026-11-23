import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { adminApi } from '@/services/api/adminApi'
import { ApiError } from '@/services/api/errors'
import { usePermissions } from '@/hooks/usePermissions'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { DateRangePicker, defaultRange } from '@/components/forms/DateRangePicker'
import { TrendChart } from '@/components/charts/charts'
import { InlineAlert, QueryState } from '@/components/feedback/states'
import { KpiTile, PageHeader, QuotaBar, StatusBadge } from '@/components/common/display'
import { formatBytes, formatCompact, formatCost, formatNumber, formatPct, humanize, formatDateTime } from '@/utils/format'
import { n, s, useTenantKey, useWrite, type Row } from './common'
import type { IngestionJob, QuotaSnapshot } from '@/types/api'

const QUOTA_FMT: Record<string, (v: number) => string> = { storage: formatBytes, storage_bytes: formatBytes, ai_tokens: formatCompact }

export default function AdminDashboardPage() {
  const key = useTenantKey()
  const p = usePermissions()
  const [range, setRange] = useState(defaultRange)
  const dash = useQuery({ queryKey: key('admin', 'dashboard', range), queryFn: () => adminApi.dashboard(range) })
  const failed = useQuery({ queryKey: key('admin', 'dashboard', 'failed-jobs'), enabled: p.can('admin.ingestion.manage'), queryFn: async () => {
    const [a, b] = await Promise.all([adminApi.ingestionJobs({ status: 'failed', limit: 5 }), adminApi.ingestionJobs({ status: 'dead_letter', limit: 5 })])
    return [...a.items, ...b.items].slice(0, 8) as IngestionJob[]
  } })
  const zero = useQuery({ queryKey: key('admin', 'dashboard', 'search'), enabled: p.can('admin.analytics.view'), queryFn: () => adminApi.searchAnalytics(range) })
  const retry = useWrite((id: string) => adminApi.retryJob(id), { invalidate: [['admin', 'dashboard']], success: 'Retry requested.' })

  return (
    <>
      <PageHeader title="Dashboard" description="Real totals and trends for your organisation." actions={<DateRangePicker value={range} onChange={setRange} />} />
      <QueryState query={dash}>
        {(d) => {
          const t = (d.totals ?? {}) as Row
          const quotas = (d.quotas ?? []) as QuotaSnapshot[]
          const series = ((d.series ?? []) as Row[]).map((r) => ({ ...r, usage_date: String(r.usage_date) })) as Record<string, string | number | null>[]
          const fb = (n(t.feedback_positive) ?? 0) + (n(t.feedback_negative) ?? 0)
          const full = quotas.filter((q) => q.pct >= 100)
          return (
            <div className="space-y-4">
              {full.length > 0 && <InlineAlert tone="danger" title="Quota reached">{full.map((q) => humanize(q.metric)).join(', ')}. New activity of this kind may be rejected until the plan is raised.</InlineAlert>}
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
                <KpiTile label="Active users" value={formatNumber(n(t.active_users))} sub={`of ${formatNumber(n(t.total_users))} users`} />
                <KpiTile label="Documents" value={formatNumber(n(t.total_documents))} sub={`${formatNumber(n(t.indexed_documents))} published`} />
                <KpiTile label="Failed ingestions" value={formatNumber(n(t.failed_ingestion_jobs))} tone={(n(t.failed_ingestion_jobs) ?? 0) > 0 ? 'danger' : undefined} />
                <KpiTile label="Searches" value={formatNumber(n(t.searches))} sub={`avg ${formatNumber(n(t.avg_search_latency_ms))} ms`} />
                <KpiTile label="Chats" value={formatNumber(n(t.chats))} sub={`${formatNumber(n(t.abstentions))} abstained`} />
                <KpiTile label="AI tokens" value={formatCompact(n(t.tokens))} sub={`${formatCost(n(t.estimated_cost))} estimated`} />
              </div>
              <p className="text-xs text-ink-muted">{s(d.cost_note, 'Costs are estimates.')} Feedback satisfaction: {fb ? formatPct(n(t.feedback_satisfaction_pct)) : 'no feedback yet'}.</p>
              <TrendChart title="Daily usage" data={series} xKey="usage_date" series={[{ key: 'searches', label: 'Searches' }, { key: 'chats', label: 'Chats' }, { key: 'active_users', label: 'Active users' }]} />
              <Card><CardHeader title="Quotas" description="Amber from 80%, red at 100%." /><CardBody className="grid gap-4 md:grid-cols-2">
                {quotas.length === 0 && <p className="text-sm text-ink-muted">No quota information.</p>}
                {quotas.map((q) => <QuotaBar key={q.metric} label={humanize(q.metric)} used={q.used} limit={q.limit} format={QUOTA_FMT[q.metric] ?? formatNumber} />)}
              </CardBody></Card>
            </div>
          )
        }}
      </QueryState>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        {p.can('admin.ingestion.manage') && (
          <Card><CardHeader title="Needs attention: ingestion" actions={<Button asChild variant="link"><Link to="/admin/ingestion">Open monitor</Link></Button>} />
            <QueryState query={failed} isEmpty={(d) => d.length === 0} empty={<p className="p-4 text-sm text-ink-muted">No failed ingestion jobs.</p>}>
              {(jobs) => <ul>{jobs.map((j) => <li key={j.job_id} className="flex items-center justify-between gap-2 border-b border-line px-4 py-2 last:border-0">
                <span><StatusBadge value={j.status} /> <span className="ml-1 text-xs text-ink-muted">{humanize(j.job_type)} · {formatDateTime(j.finished_at ?? j.queued_at)}</span><span className="block text-xs">{s(j.error_code, '')}</span></span>
                <Button size="sm" variant="secondary" loading={retry.isPending && retry.variables === j.job_id} onClick={() => retry.mutate(j.job_id, { onError: (e) => toast.error((e as ApiError).message) })}>Retry</Button>
              </li>)}</ul>}
            </QueryState></Card>
        )}
        {p.can('admin.analytics.view') && (
          <Card><CardHeader title="Search quality" description="Zero-result queries are counted, query text is shown only when the organisation stores it." />
            <QueryState query={zero}>{(d) => {
              const sm = (d.summary ?? {}) as Row
              return <CardBody><dl className="grid grid-cols-2 gap-3 text-sm">
                <div><dt className="text-xs text-ink-muted">Searches</dt><dd className="text-lg font-semibold">{formatNumber(n(sm.searches))}</dd></div>
                <div><dt className="text-xs text-ink-muted">Zero results</dt><dd className="text-lg font-semibold">{formatNumber(n(sm.zero_result))}</dd></div>
                <div><dt className="text-xs text-ink-muted">p95 latency</dt><dd className="text-lg font-semibold">{formatNumber(n(sm.p95_latency_ms))} ms</dd></div>
                <div><dt className="text-xs text-ink-muted">Cache hits</dt><dd className="text-lg font-semibold">{formatNumber(n(sm.cache_hits))}</dd></div></dl></CardBody>
            }}</QueryState></Card>
        )}
      </div>
    </>
  )
}
