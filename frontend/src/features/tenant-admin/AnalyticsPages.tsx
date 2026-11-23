import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { adminApi } from '@/services/api/adminApi'
import { ApiError } from '@/services/api/errors'
import { usePermissions } from '@/hooks/usePermissions'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Tabs } from '@/components/ui/tabs'
import { DateRangePicker, defaultRange } from '@/components/forms/DateRangePicker'
import { BarsChart } from '@/components/charts/charts'
import { QueryState } from '@/components/feedback/states'
import { KpiTile, PageHeader, QuotaBar } from '@/components/common/display'
import { formatBytes, formatCompact, formatCost, formatNumber, formatPct, humanize } from '@/utils/format'
import type { DateRange, QuotaSnapshot } from '@/types/api'
import { n, s, useTenantKey, type Row } from './common'

const rows = (v: unknown): Row[] => (Array.isArray(v) ? (v as Row[]) : [])
const QF: Record<string, (v: number) => string> = { storage: formatBytes, storage_bytes: formatBytes, ai_tokens: formatCompact }

function SearchTab({ range }: { range: DateRange }) {
  const key = useTenantKey()
  const q = useQuery({ queryKey: key('admin', 'analytics', 'search', range), queryFn: () => adminApi.searchAnalytics(range) })
  return <QueryState query={q}>{(d) => {
    const sm = (d.summary ?? {}) as Row
    const searches = n(sm.searches) ?? 0
    return (<div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <KpiTile label="Searches" value={formatNumber(searches)} /><KpiTile label="Zero-result rate" value={searches ? formatPct(100 * (n(sm.zero_result) ?? 0) / searches) : '–'} />
        <KpiTile label="Average latency" value={`${formatNumber(n(sm.avg_latency_ms))} ms`} /><KpiTile label="p95 latency" value={`${formatNumber(n(sm.p95_latency_ms))} ms`} />
        <KpiTile label="Cache hit rate" value={searches ? formatPct(100 * (n(sm.cache_hits) ?? 0) / searches) : '–'} />
      </div>
      <BarsChart title="Searches by mode" data={rows(d.by_mode).map((r) => ({ mode: humanize(s(r.mode)), searches: n(r.n), latency: n(r.avg_latency_ms) }))} xKey="mode" series={[{ key: 'searches', label: 'Searches' }, { key: 'latency', label: 'Average latency (ms)' }]} />
    </div>)
  }}</QueryState>
}

function ChatTab({ range }: { range: DateRange }) {
  const key = useTenantKey()
  const q = useQuery({ queryKey: key('admin', 'analytics', 'chat', range), queryFn: () => adminApi.chatAnalytics(range) })
  return <QueryState query={q}>{(d) => {
    const status = rows(d.by_status)
    const total = status.reduce((a, r) => a + (n(r.n) ?? 0), 0)
    const abst = status.find((r) => r.answer_status === 'abstained')
    const fb = rows(d.feedback)
    return (<div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <KpiTile label="Answers" value={formatNumber(total)} /><KpiTile label="Abstention rate" value={total ? formatPct(100 * (n(abst?.n) ?? 0) / total) : '–'} />
        <KpiTile label="Citation coverage" value={formatPct(n(d.citation_coverage_pct))} /><KpiTile label="Answers with unverified citations" value={formatNumber(n(d.unverified_citation_answers))} />
      </div>
      <BarsChart title="Answers by status" data={status.map((r) => ({ status: humanize(s(r.answer_status)), answers: n(r.n) }))} xKey="status" series={[{ key: 'answers', label: 'Answers' }]} />
      <BarsChart title="Evidence strength mix" data={rows(d.by_evidence).map((r) => ({ evidence: humanize(s(r.evidence_strength)), answers: n(r.n) }))} xKey="evidence" series={[{ key: 'answers', label: 'Answers' }]} />
      <Card><CardHeader title="Feedback by category and status" /><div className="table-wrap border-0"><table className="tbl"><caption className="sr-only">Feedback</caption><thead><tr><th scope="col">Category</th><th scope="col">Status</th><th scope="col">Count</th></tr></thead>
        <tbody>{fb.length === 0 ? <tr><td colSpan={3} className="text-ink-muted">No feedback in this period.</td></tr> : fb.map((r, i) => <tr key={i}><td>{humanize(s(r.category))}</td><td>{humanize(s(r.status))}</td><td>{s(r.n)}</td></tr>)}</tbody></table></div></Card>
    </div>)
  }}</QueryState>
}

function UsageTab({ range }: { range: DateRange }) {
  const key = useTenantKey()
  const q = useQuery({ queryKey: key('admin', 'usage', range), queryFn: () => adminApi.usage(range) })
  return <QueryState query={q}>{(d) => (
    <div className="space-y-4">
      <p className="text-xs text-ink-muted">{s(d.cost_note, 'Costs are estimates based on catalogue prices.')}</p>
      <Card><CardHeader title="Quota consumption" /><CardBody className="grid gap-4 md:grid-cols-2">{((d.quotas ?? []) as QuotaSnapshot[]).map((qq) => <QuotaBar key={qq.metric} label={humanize(qq.metric)} used={qq.used} limit={qq.limit} format={QF[qq.metric] ?? formatNumber} />)}</CardBody></Card>
      <BarsChart title="Estimated cost by model" unit="USD" data={rows(d.by_model).map((r) => ({ model: s(r.model), cost: n(r.estimated_cost) }))} xKey="model" series={[{ key: 'cost', label: 'Estimated cost' }]} />
      <Card><CardHeader title="By model" /><div className="table-wrap border-0"><table className="tbl"><caption className="sr-only">Usage by model</caption><thead><tr><th scope="col">Provider</th><th scope="col">Model</th><th scope="col">Purpose</th><th scope="col">Requests</th><th scope="col">Tokens in</th><th scope="col">Tokens out</th><th scope="col">Errors</th><th scope="col">Estimated cost</th></tr></thead>
        <tbody>{rows(d.by_model).map((r, i) => <tr key={i}><td>{s(r.provider)}</td><td>{s(r.model)}</td><td>{humanize(s(r.purpose))}</td><td>{formatNumber(n(r.requests))}</td><td>{formatCompact(n(r.input_tokens))}</td><td>{formatCompact(n(r.output_tokens))}</td><td>{formatNumber(n(r.errors))}</td><td>{formatCost(n(r.estimated_cost))}</td></tr>)}</tbody></table></div></Card>
    </div>)}</QueryState>
}

function DepartmentsTab() {
  const key = useTenantKey()
  const [range] = useState(defaultRange)
  const q = useQuery({ queryKey: key('admin', 'usage', 'departments', range), queryFn: () => adminApi.usage(range) })
  return <QueryState query={q}>{(d) => (
    <Card><CardHeader title="Department comparison" description="Selected period." /><div className="table-wrap border-0"><table className="tbl"><caption className="sr-only">Usage by department</caption><thead><tr><th scope="col">Department</th><th scope="col">Searches</th><th scope="col">Chats</th><th scope="col">Tokens</th><th scope="col">Estimated cost</th></tr></thead>
      <tbody>{rows(d.by_department).map((r, i) => <tr key={i}><td>{s(r.name)}</td><td>{formatNumber(n(r.searches))}</td><td>{formatNumber(n(r.chats))}</td><td>{formatCompact(n(r.tokens))}</td><td>{formatCost(n(r.estimated_cost))}</td></tr>)}</tbody></table></div></Card>)}</QueryState>
}

export function AnalyticsPage() {
  const p = usePermissions()
  const [sp, setSp] = useSearchParams()
  const [range, setRange] = useState(defaultRange)
  const first = p.can('admin.analytics.view') ? 'search' : 'usage'
  return (
    <>
      <PageHeader title="Analytics and usage" description="Aggregates computed by the backend. Charts have a table view." actions={<DateRangePicker value={range} onChange={setRange} />} />
      <Tabs value={sp.get('tab') ?? first} onValueChange={(v) => setSp({ tab: v }, { replace: true })} tabs={[
        { value: 'search', label: 'Search', hidden: !p.can('admin.analytics.view'), content: <SearchTab range={range} /> },
        { value: 'chat', label: 'Chat', hidden: !p.can('admin.analytics.view'), content: <ChatTab range={range} /> },
        { value: 'usage', label: 'Usage and cost', hidden: !p.can('admin.usage.view'), content: <UsageTab range={range} /> },
        { value: 'departments', label: 'Departments', hidden: !p.can('admin.usage.view'), content: <DepartmentsTab /> },
      ]} />
    </>
  )
}

const REPORTS = ['user_activity', 'document_inventory', 'ingestion_performance', 'search_usage', 'chat_usage', 'feedback', 'token_consumption', 'estimated_expenditure', 'department_usage', 'retrieval_quality', 'citation_coverage']

function ReportCard({ name }: { name: string }) {
  const [range, setRange] = useState(defaultRange)
  const [busy, setBusy] = useState(false)
  return (
    <Card><CardHeader title={humanize(name)} /><CardBody className="space-y-3">
      <DateRangePicker value={range} onChange={setRange} />
      <Button variant="secondary" loading={busy} onClick={async () => { setBusy(true); try { const f = await adminApi.report(name, range); toast.success(`Downloaded ${f}. The export is recorded in the audit log.`) } catch (e) { toast.error(e instanceof ApiError ? e.message : 'Export failed.') } finally { setBusy(false) } }}>Download CSV</Button>
    </CardBody></Card>
  )
}

export function ReportsPage() {
  return (
    <>
      <PageHeader title="Reports" description="Exports are recorded in the audit log." />
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{REPORTS.map((r) => <ReportCard key={r} name={r} />)}</div>
    </>
  )
}
