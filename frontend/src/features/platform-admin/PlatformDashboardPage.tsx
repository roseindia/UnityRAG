import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { platformApi } from '@/services/api/platformApi'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader, Badge } from '@/components/ui/card'
import { DateRangePicker, defaultRange } from '@/components/forms/DateRangePicker'
import { BarsChart, TrendChart } from '@/components/charts/charts'
import { EmptyState, InlineAlert, QueryState } from '@/components/feedback/states'
import { KpiTile, PageHeader, StatusBadge } from '@/components/common/display'
import { formatBytes, formatCompact, formatCost, formatDateTime, formatNumber, formatPct, humanize } from '@/utils/format'
import { n, s, type Row } from '@/features/tenant-admin/common'

const obj = (v: unknown): Row => (v && typeof v === 'object' ? (v as Row) : {})
const list = (v: unknown): Row[] => (Array.isArray(v) ? (v as Row[]) : [])

function TenantComparison({ range }: { range: { start: string; end: string } }) {
  const q = useQuery({ queryKey: ['platform', 'analytics', range], queryFn: () => platformApi.analytics(range) })
  return (
    <Card><CardHeader title="Tenant comparison" description="Usage per tenant for the selected period (aggregates only)." />
      <QueryState query={q} isEmpty={(d) => list(d.tenants).length === 0} empty={<EmptyState title="No tenants" />}>{(d) => (
        <div className="table-wrap border-0"><table className="tbl"><caption className="sr-only">Usage by tenant</caption>
          <thead><tr><th scope="col">Tenant</th><th scope="col">Status</th><th scope="col">Searches</th><th scope="col">Chats</th><th scope="col">Tokens</th><th scope="col">Peak active users</th><th scope="col">Avg search latency</th><th scope="col">Estimated cost</th></tr></thead>
          <tbody>{list(d.tenants).map((t) => <tr key={s(t.tenant_id)}><td><Link className="text-primary hover:underline" to={`/platform/tenants/${s(t.tenant_id)}`}>{s(t.name)}</Link><span className="block font-mono text-xs text-ink-muted">{s(t.code)}</span></td><td><StatusBadge value={s(t.status, '')} /></td>
            <td>{formatNumber(n(t.searches))}</td><td>{formatNumber(n(t.chats))}</td><td>{formatCompact(n(t.tokens))}</td><td>{formatNumber(n(t.peak_active_users))}</td><td>{formatNumber(n(t.avg_search_latency_ms))} ms</td><td>{formatCost(n(t.estimated_cost))}</td></tr>)}</tbody></table></div>)}</QueryState></Card>
  )
}

export default function PlatformDashboardPage() {
  const [range, setRange] = useState(defaultRange)
  const q = useQuery({ queryKey: ['platform', 'dashboard', range], queryFn: () => platformApi.dashboard(range) })
  return (
    <>
      <PageHeader title="Platform dashboard" description="Cross-tenant aggregates. Tenant content is never shown here." actions={<DateRangePicker value={range} onChange={setRange} />} />
      <QueryState query={q}>{(d) => {
        const t = obj(d.tenants), u = obj(d.users), c = obj(d.content), us = obj(d.usage)
        const series = list(d.series).map((r) => ({ ...r, usage_date: String(r.usage_date) })) as Record<string, string | number | null>[]
        const alerts = list(d.alerts)
        return (
          <div className="space-y-4">
            {alerts.length > 0 && <Card><CardHeader title="Alerts" description="Quota breaches, ingestion failures and security events." /><ul>{alerts.map((a, i) => <li key={i} className="flex items-center gap-2 border-b border-line px-4 py-2 last:border-0"><Badge tone={a.severity === 'critical' ? 'danger' : 'warning'}>{humanize(s(a.severity))}</Badge><span>{s(a.message)}</span></li>)}</ul></Card>}
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4 xl:grid-cols-6">
              <KpiTile label="Tenants" value={formatNumber(n(t.total))} sub={`${formatNumber(n(t.active))} active · ${formatNumber(n(t.suspended))} suspended · ${formatNumber(n(t.trial))} trial`} />
              <KpiTile label="Active accounts (30 d)" value={formatNumber(n(u.active_last_30_days))} sub={`${formatNumber(n(u.total_accounts))} accounts`} />
              <KpiTile label="Requests" value={formatNumber((n(us.searches) ?? 0) + (n(us.chats) ?? 0))} sub={`${formatNumber(n(us.searches))} searches · ${formatNumber(n(us.chats))} chats`} />
              <KpiTile label="AI tokens" value={formatCompact(n(us.tokens))} sub={`${formatCost(n(us.estimated_cost))} estimated`} />
              <KpiTile label="Storage" value={formatBytes(n(c.storage_bytes))} sub={`${formatNumber(n(c.documents))} documents`} />
              <KpiTile label="Ingestion failure rate" value={formatPct(n(us.ingestion_failure_rate))} tone={(n(us.ingestion_failures) ?? 0) > 0 ? 'warning' : undefined} sub={`${formatNumber(n(c.active_ingestion_jobs))} active jobs`} />
            </div>
            <p className="text-xs text-ink-muted">{s(d.cost_note, 'Costs are estimates.')}</p>
            <div className="grid gap-4 xl:grid-cols-2">
              <TrendChart title="Platform activity" data={series} xKey="usage_date" series={[{ key: 'searches', label: 'Searches' }, { key: 'chats', label: 'Chats' }, { key: 'active_users', label: 'Active users' }]} />
              <BarsChart title="Top tenants by tokens" unit="tokens" data={list(d.top_tenants).map((r) => ({ tenant: s(r.code), tokens: n(r.tokens) }))} xKey="tenant" series={[{ key: 'tokens', label: 'Tokens' }]} />
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <Card><CardHeader title="Recent platform events" actions={<Button asChild variant="link"><Link to="/platform/audit">Platform audit</Link></Button>} />
                {list(d.recent_events).length === 0 ? <EmptyState title="No events" /> : <ul>{list(d.recent_events).map((e, i) => <li key={i} className="flex items-center justify-between gap-2 border-b border-line px-4 py-2 text-sm last:border-0"><span>{humanize(s(e.action, ''))} <span className="text-xs text-ink-muted">{humanize(s(e.category, ''))}</span></span><span className="flex items-center gap-2"><StatusBadge value={s(e.outcome, '')} /><span className="text-xs text-ink-muted">{formatDateTime(e.occurred_at as string)}</span></span></li>)}</ul>}</Card>
              <Card><CardHeader title="System health" actions={<Button asChild variant="link"><Link to="/platform/monitoring">Monitoring</Link></Button>} /><CardBody>
                <ul className="grid grid-cols-2 gap-2">{['api', 'database', 'redis', 'workers'].map((k) => <li key={k} className="flex items-center justify-between rounded-control border border-line px-3 py-2"><span>{humanize(k)}</span><StatusBadge value={s(obj(obj(d.health)[k]).status, 'unknown')} /></li>)}</ul>
              </CardBody></Card>
            </div>
            <TenantComparison range={range} />
            {list(d.top_tenants).length === 0 && <InlineAlert>No tenants have recorded activity in this period.</InlineAlert>}
          </div>
        )
      }}</QueryState>
    </>
  )
}
