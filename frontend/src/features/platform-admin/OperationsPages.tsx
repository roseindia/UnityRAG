import { useQuery } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { Pause } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { platformApi } from '@/services/api/platformApi'
import { ApiError } from '@/services/api/errors'
import { useBreakGlass } from '@/contexts/BreakGlassContext'
import { usePageVisible, useRefreshInterval } from '@/hooks/useMisc'
import { useUrlState } from '@/hooks/useUrlState'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader, Badge } from '@/components/ui/card'
import { Checkbox, Field, Input, Select, Textarea } from '@/components/ui/form'
import { Modal } from '@/components/ui/dialog'
import { DataTable } from '@/components/tables/DataTable'
import { EmptyState, ErrorState, InlineAlert, LoadingBlock, QueryState } from '@/components/feedback/states'
import { JsonViewer, KeyValueList, KpiTile, PageHeader, StatusBadge } from '@/components/common/display'
import { formatDateTime, formatNumber, humanize, timeAgo } from '@/utils/format'
import { n, s, useWrite, type Row } from '@/features/tenant-admin/common'

const obj = (v: unknown): Row => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Row) : {})
const list = (v: unknown): Row[] => (Array.isArray(v) ? (v as Row[]) : [])

/* ---------- Monitoring (auto-refresh 30 s, paused when hidden) ---------- */
export function MonitoringPage() {
  const visible = usePageVisible()
  const refetch = useRefreshInterval(30_000)
  const q = useQuery({ queryKey: ['platform', 'monitoring'], queryFn: platformApi.monitoring, refetchInterval: refetch })
  return (
    <>
      <PageHeader title="Monitoring" description="API, PostgreSQL, Redis, workers, queues and AI providers." actions={<span className="flex items-center gap-2 text-xs text-ink-muted">{!visible && <Badge><Pause className="h-3 w-3" aria-hidden />Paused</Badge>}{q.dataUpdatedAt ? `Last checked ${new Date(q.dataUpdatedAt).toLocaleTimeString()}` : ''}</span>} />
      <QueryState query={q}>{(d) => {
        const h = obj(d.health)
        const db = obj(d.database)
        return (<div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            {['api', 'database', 'redis', 'workers', 'queue'].map((k) => <Card key={k} className="p-4"><p className="text-xs font-medium uppercase tracking-wide text-ink-muted">{humanize(k)}</p><div className="mt-1"><StatusBadge value={s(obj(h[k]).status, 'unknown')} /></div>{obj(h[k]).latency_ms !== undefined && <p className="mt-1 text-xs text-ink-muted">{s(obj(h[k]).latency_ms)} ms</p>}</Card>)}
          </div>
          <div className="grid gap-3 sm:grid-cols-3"><KpiTile label="HTTP 5xx error rate" value={`${s(d.error_rate_pct, '0')}%`} /><KpiTile label="DB cache hit ratio" value={db.cache_hit_ratio !== undefined ? `${(Number(db.cache_hit_ratio) * 100).toFixed(1)}%` : '–'} /><KpiTile label="DB deadlocks" value={formatNumber(n(db.deadlocks))} /></div>
          <Card><CardHeader title="Worker heartbeats" /><div className="table-wrap border-0"><table className="tbl"><caption className="sr-only">Workers</caption><thead><tr><th scope="col">Worker</th><th scope="col">Status</th><th scope="col">Processed</th><th scope="col">Failed</th><th scope="col">Last seen</th><th scope="col">Healthy</th></tr></thead>
            <tbody>{list(obj(h.workers).instances).length === 0 ? <tr><td colSpan={6} className="text-ink-muted">No workers have reported.</td></tr> : list(obj(h.workers).instances).map((w, i) => <tr key={i}><td>{s(w.worker_name)}</td><td>{s(w.status)}</td><td>{s(w.processed)}</td><td>{s(w.failed)}</td><td>{timeAgo(w.last_seen_at as string)}</td><td><StatusBadge value={w.healthy ? 'healthy' : 'down'} /></td></tr>)}</tbody></table></div></Card>
          <Card><CardHeader title="AI provider health" /><div className="table-wrap border-0"><table className="tbl"><caption className="sr-only">Providers</caption><thead><tr><th scope="col">Provider</th><th scope="col">Type</th><th scope="col">Health</th><th scope="col">Last checked</th><th scope="col">Enabled</th></tr></thead>
            <tbody>{list(d.provider_health).map((p, i) => <tr key={i}><td>{s(p.code)}</td><td>{humanize(s(p.provider_type, ''))}</td><td><StatusBadge value={s(p.health_status, 'unknown')} /></td><td>{formatDateTime(p.last_checked_at as string)}</td><td>{p.is_enabled ? 'Yes' : 'No'}</td></tr>)}</tbody></table></div></Card>
        </div>)
      }}</QueryState>
    </>
  )
}

export function JobsPage() {
  const refetch = useRefreshInterval(30_000)
  const q = useQuery({ queryKey: ['platform', 'jobs'], queryFn: platformApi.jobs, refetchInterval: refetch })
  return (
    <>
      <PageHeader title="Jobs and workers" description="Queue depth and per-tenant ingestion backlog (metadata only)." />
      <QueryState query={q}>{(d) => {
        const queue = obj(d.queue)
        return (<div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-3"><KpiTile label="Ingestion queue" value={formatNumber(n(queue.ingestion))} /><KpiTile label="Maintenance queue" value={formatNumber(n(queue.maintenance))} /><Card className="p-4"><p className="text-xs font-medium uppercase tracking-wide text-ink-muted">Queue broker</p><div className="mt-1"><StatusBadge value={s(queue.status, 'unknown')} /></div></Card></div>
          <Card><CardHeader title="Per-tenant ingestion activity" /><div className="table-wrap border-0"><table className="tbl"><caption className="sr-only">Tenant ingestion backlog</caption><thead><tr><th scope="col">Tenant</th><th scope="col">Active jobs</th><th scope="col">Ingested (7 d)</th><th scope="col">Failures (7 d)</th></tr></thead>
            <tbody>{list(d.tenants).map((t) => <tr key={s(t.tenant_id)}><td><Link className="text-primary hover:underline" to={`/platform/tenants/${s(t.tenant_id)}`}>{s(t.code)}</Link></td><td>{s(t.active_ingestion_jobs)}</td><td>{s(t.ingested_7d)}</td><td className={(n(t.failures_7d) ?? 0) > 0 ? 'font-medium text-danger' : ''}>{s(t.failures_7d)}</td></tr>)}</tbody></table></div></Card>
        </div>)
      }}</QueryState>
    </>
  )
}

/* ---------- Security events and platform audit ---------- */
const DEF = { category: '', severity: '', tenant_id: '', start: '', end: '', offset: '0', limit: '50' }

function EventsTable({ rows, total, limit, offset, loading, error, onRetry, onPage, caption }: { rows?: Row[]; total?: number; limit: number; offset: number; loading: boolean; error: unknown; onRetry: () => void; onPage: (o: number, l: number) => void; caption: string }) {
  const [open, setOpen] = useState<Row | null>(null)
  const columns = useMemo<ColumnDef<Row, unknown>[]>(() => [
    { header: 'Time', cell: ({ row: { original: r } }) => <time title={s(r.occurred_at)}>{formatDateTime(r.occurred_at as string)}</time> },
    { header: 'Severity', cell: ({ row: { original: r } }) => <StatusBadge value={s(r.severity, '')} /> },
    { header: 'Category', cell: ({ row: { original: r } }) => humanize(s(r.category, '')) },
    { header: 'Action', cell: ({ row: { original: r } }) => <span className="font-mono text-xs">{s(r.action ?? r.event_type)}</span> },
    { header: 'Tenant', cell: ({ row: { original: r } }) => <span className="font-mono text-xs">{s(r.target_tenant_id ?? r.tenant_id, '').slice(0, 8) || '–'}</span> },
    { header: 'Actor', cell: ({ row: { original: r } }) => <span className="font-mono text-xs">{s(r.actor_account_id ?? r.actor_id, '').slice(0, 8) || '–'}</span> },
    { header: 'Outcome', cell: ({ row: { original: r } }) => <StatusBadge value={s(r.outcome, '')} /> },
    { header: 'Detail', cell: ({ row: { original: r } }) => <Button size="sm" variant="ghost" onClick={() => setOpen(r)}>Details</Button> },
  ], [])
  return (<>
    <DataTable caption={caption} columns={columns} rows={rows} total={total} limit={limit} offset={offset} loading={loading} error={error} onRetry={onRetry} rowKey={(r) => s(r.seq ?? r.event_id ?? `${r.occurred_at}${r.action}`)} onPage={onPage} />
    <Modal open={!!open} onOpenChange={(o) => !o && setOpen(null)} variant="drawer" title="Event detail">{open && <JsonViewer value={open} />}</Modal>
  </>)
}

export function SecurityEventsPage() {
  const [st, set] = useUrlState({ offset: '0', limit: '50' })
  const limit = Number(st.limit), offset = Number(st.offset)
  const q = useQuery({ queryKey: ['platform', 'security', st], queryFn: () => platformApi.securityEvents({ limit, offset }), placeholderData: (p) => p })
  return (<><PageHeader title="Security events" description="Authorisation denials, refresh-token reuse, cross-tenant guardrail blocks and break-glass access." />
    <EventsTable caption="Security events" rows={q.data?.items} total={q.data?.total} limit={limit} offset={offset} loading={q.isFetching} error={q.error} onRetry={() => void q.refetch()} onPage={(o, l) => set({ offset: String(o), limit: String(l) }, { keepOffset: true })} /></>)
}

export function PlatformAuditPage() {
  const [st, set] = useUrlState(DEF)
  const limit = Number(st.limit), offset = Number(st.offset)
  const bad = !!st.start && !!st.end && st.end < st.start
  const q = useQuery({ queryKey: ['platform', 'audit', st], queryFn: () => platformApi.audit({ category: st.category, severity: st.severity, tenant_id: st.tenant_id, start: st.start, end: st.end, limit, offset }), placeholderData: (p) => p, enabled: !bad })
  return (<><PageHeader title="Platform audit" description="Events are shown as recorded." />
    <div className="mb-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
      <Field label="Category">{(p) => <Input {...p} value={st.category} onChange={(e) => set({ category: e.target.value.trim() })} />}</Field>
      <Field label="Severity">{(p) => <Select {...p} value={st.severity} onChange={(e) => set({ severity: e.target.value })}><option value="">All</option>{['low', 'medium', 'high', 'critical'].map((x) => <option key={x}>{x}</option>)}</Select>}</Field>
      <Field label="Tenant id">{(p) => <Input {...p} value={st.tenant_id} onChange={(e) => set({ tenant_id: e.target.value.trim() })} />}</Field>
      <Field label="From">{(p) => <Input {...p} type="date" value={st.start} onChange={(e) => set({ start: e.target.value })} />}</Field>
      <Field label="To" error={bad ? 'Must be on or after the start date.' : undefined}>{(p) => <Input {...p} type="date" value={st.end} onChange={(e) => set({ end: e.target.value })} />}</Field>
    </div>
    <EventsTable caption="Platform audit" rows={bad ? [] : q.data?.items} total={q.data?.total} limit={limit} offset={offset} loading={q.isFetching} error={q.error} onRetry={() => void q.refetch()} onPage={(o, l) => set({ offset: String(o), limit: String(l) }, { keepOffset: true })} /></>)
}

/* ---------- Break-glass ---------- */
export function BreakGlassPage() {
  const nav = useNavigate()
  const { grant, start } = useBreakGlass()
  const tenants = useQuery({ queryKey: ['platform', 'tenants', 'picker'], queryFn: () => platformApi.tenants({ limit: 200 }) })
  const [v, setV] = useState({ tenant_id: '', reason: '', minutes: '15', documents: true, conversations: false, consent: false })
  const [err, setErr] = useState<{ message: string; grantId?: string } | null>(null)
  const mins = Number(v.minutes)
  const bad = !v.tenant_id || v.reason.trim().length < 15 || !(mins >= 5 && mins <= 480) || !v.consent || (!v.documents && !v.conversations)
  const open = useWrite(() => platformApi.openBreakGlass({ tenant_id: v.tenant_id, reason: v.reason.trim(), minutes: mins, scope: [v.documents && 'documents:read', v.conversations && 'conversations:read'].filter(Boolean), confirm: true }), { silentError: true })
  const submit = () => open.mutate(undefined, {
    onSuccess: (r) => {
      const g = s(r.grant_id)
      const t = tenants.data?.items.find((x) => x.tenant_id === v.tenant_id)
      start({ grantId: g, tenantId: v.tenant_id, tenantName: s(t?.name, 'tenant'), expiresAt: r.expires_at ? Date.parse(r.expires_at as string) : Date.now() + mins * 60_000 })
      nav(`/platform/break-glass/${g}`)
    },
    onError: (e) => {
      const api = e instanceof ApiError ? e : null
      setErr({ message: api?.status === 409 ? 'An active grant already exists for this tenant.' : api?.status === 403 ? "This tenant's subscription does not permit support access." : (api?.message ?? 'Could not open the grant.'), grantId: api?.status === 409 ? s(api.details?.[0]?.grant_id, '') || undefined : undefined })
    },
  })
  return (
    <>
      <PageHeader title="Break-glass access" description="Time-boxed, reason-captured, audited read access to tenant content. Read-only, no export or download." />
      {grant && <InlineAlert tone="danger" className="mb-3" title="A grant is active">Tenant {grant.tenantName}. <Link className="underline" to={`/platform/break-glass/${grant.grantId}`}>Open it</Link>.</InlineAlert>}
      <Card className="max-w-2xl"><CardHeader title="Request access" /><CardBody>
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (!bad) submit() }}>
          {err && <InlineAlert tone="danger">{err.message} {err.grantId && <Link className="underline" to={`/platform/break-glass/${err.grantId}`}>Open it</Link>}</InlineAlert>}
          <Field label="Tenant" required>{(p) => <Select {...p} value={v.tenant_id} onChange={(e) => setV({ ...v, tenant_id: e.target.value })}><option value="">Select…</option>{tenants.data?.items.map((t) => <option key={s(t.tenant_id)} value={s(t.tenant_id)}>{s(t.name)} ({s(t.code)})</option>)}</Select>}</Field>
          <Field label="Business reason" required error={v.reason && v.reason.trim().length < 15 ? 'At least 15 characters.' : undefined} hint="Recorded in the platform and tenant audit logs.">{(p) => <Textarea {...p} value={v.reason} onChange={(e) => setV({ ...v, reason: e.target.value })} />}</Field>
          <Field label="Duration (minutes)" required error={v.minutes && !(mins >= 5 && mins <= 480) ? 'Between 5 and 480 minutes.' : undefined}>{(p) => <Input {...p} type="number" min={5} max={480} value={v.minutes} onChange={(e) => setV({ ...v, minutes: e.target.value })} />}</Field>
          <fieldset><legend className="mb-1 text-sm font-medium">Scope</legend><div className="flex gap-4"><Checkbox label="documents:read" checked={v.documents} onChange={(e) => setV({ ...v, documents: e.target.checked })} /><Checkbox label="conversations:read" checked={v.conversations} onChange={(e) => setV({ ...v, conversations: e.target.checked })} /></div></fieldset>
          <Checkbox label="All access is recorded in the platform and tenant audit logs. I accept this." checked={v.consent} onChange={(e) => setV({ ...v, consent: e.target.checked })} />
          <Button type="submit" variant="danger" loading={open.isPending} disabled={bad}>Open grant</Button>
        </form></CardBody></Card>
    </>
  )
}

export function BreakGlassGrantPage() {
  const { grantId = '' } = useParams()
  const nav = useNavigate()
  const { grant, end } = useBreakGlass()
  const [tab, setTab] = useState<'documents' | 'conversation'>('documents')
  const [rid, setRid] = useState('')
  const [sel, setSel] = useState<string | null>(null)
  const [now, setNow] = useState(Date.now())
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t) }, [])
  const active = grant?.grantId === grantId
  const docs = useQuery({ queryKey: ['platform', 'break-glass', grantId, 'documents'], queryFn: () => platformApi.breakGlassRead(grantId, 'documents'), enabled: active && tab === 'documents', retry: false, gcTime: 0 })
  const one = useQuery({ queryKey: ['platform', 'break-glass', grantId, 'document', sel], queryFn: () => platformApi.breakGlassRead(grantId, 'document', sel!), enabled: active && !!sel, retry: false, gcTime: 0 })
  const conv = useQuery({ queryKey: ['platform', 'break-glass', grantId, 'conversation', rid], queryFn: () => platformApi.breakGlassRead(grantId, 'conversation', rid), enabled: active && tab === 'conversation' && rid.length > 8, retry: false, gcTime: 0 })
  const close = useWrite(() => platformApi.closeBreakGlass(grantId), { success: 'Access closed. Loaded data was discarded.', onSuccess: () => { end(); nav('/platform/break-glass') } })
  if (!active) return <EmptyState title="This grant is not active in this session" description="It has expired, was closed, or belongs to another browser session. Loaded data has been discarded." action={<Button asChild><Link to="/platform/break-glass">Back to break-glass</Link></Button>} />
  const left = Math.max(0, Math.round((grant.expiresAt - now) / 1000))
  const err = (docs.error ?? one.error ?? conv.error) as ApiError | null
  return (
    <>
      <PageHeader title={`Break-glass: ${grant.tenantName}`} description="Read-only view. Every view is a server call and is audited." actions={<><Badge tone="danger">{Math.floor(left / 60)}:{String(left % 60).padStart(2, '0')} left</Badge><Button variant="danger" loading={close.isPending} onClick={() => close.mutate(undefined)}>Close access</Button></>} />
      {err?.code === 'break_glass_inactive' && <InlineAlert tone="danger" className="mb-3" title="Access expired">Support access has expired or was closed.</InlineAlert>}
      <div className="relative">
        <div className="pointer-events-none absolute inset-0 z-10 overflow-hidden opacity-[0.07]" aria-hidden><p className="rotate-[-20deg] whitespace-nowrap text-6xl font-bold">BREAK-GLASS · BREAK-GLASS · BREAK-GLASS · BREAK-GLASS</p></div>
        <div className="mb-3 flex gap-2"><Button variant={tab === 'documents' ? 'primary' : 'secondary'} onClick={() => setTab('documents')}>Documents</Button><Button variant={tab === 'conversation' ? 'primary' : 'secondary'} onClick={() => setTab('conversation')}>Conversation by id</Button></div>
        {tab === 'documents' && (docs.isPending ? <LoadingBlock /> : docs.isError ? <ErrorState error={docs.error} /> : (
          <div className="grid gap-4 lg:grid-cols-2">
            <Card><CardHeader title="Documents (metadata)" /><ul>{list(obj(docs.data).data ?? (docs.data as unknown)).map((d, i) => <li key={i}><button className="w-full border-b border-line px-4 py-2 text-left hover:bg-canvas" onClick={() => setSel(s(d.document_id))}>{s(d.title)}<span className="block text-xs text-ink-muted">{humanize(s(d.lifecycle_state, ''))}</span></button></li>)}</ul></Card>
            {sel && <Card><CardHeader title="Document" />{one.isPending ? <LoadingBlock /> : one.isError ? <ErrorState error={one.error} /> : <CardBody><JsonViewer value={obj(one.data).data ?? one.data} /></CardBody>}</Card>}
          </div>))}
        {tab === 'conversation' && <div className="space-y-3"><Field label="Conversation id" className="max-w-md">{(p) => <Input {...p} value={rid} onChange={(e) => setRid(e.target.value.trim())} />}</Field>{conv.isFetching ? <LoadingBlock /> : conv.isError ? <ErrorState error={conv.error} /> : conv.data ? <Card><CardBody><JsonViewer value={obj(conv.data).data ?? conv.data} /></CardBody></Card> : null}</div>}
      </div>
      <KeyValueList items={[{ label: 'Grant', value: <code className="font-mono text-xs">{grantId}</code> }]} />
      <p className="mt-2 text-xs text-ink-muted">There is no export or download in break-glass mode.</p>
    </>
  )
}
