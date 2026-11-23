import { useQuery } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { ShieldCheck, ShieldX } from 'lucide-react'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import { adminApi } from '@/services/api/adminApi'
import { ApiError } from '@/services/api/errors'
import { useUrlState } from '@/hooks/useUrlState'
import { Button } from '@/components/ui/button'
import { Field, Input, Select } from '@/components/ui/form'
import { Modal } from '@/components/ui/dialog'
import { DataTable } from '@/components/tables/DataTable'
import { InlineAlert } from '@/components/feedback/states'
import { JsonViewer, KeyValueList, Mono, PageHeader, StatusBadge } from '@/components/common/display'
import { formatDateTime } from '@/utils/format'
import { n, s, useTenantKey, type Row } from './common'

const DEFAULTS = { category: '', outcome: '', actor_user_id: '', resource_id: '', correlation_id: '', start: '', end: '', offset: '0', limit: '50' }
const CATEGORIES = ['authentication', 'authorization', 'search', 'retrieval', 'chat', 'document_access', 'document', 'ingestion', 'administration', 'configuration', 'export']

export default function AuditPage() {
  const key = useTenantKey()
  const [st, set] = useUrlState(DEFAULTS)
  const limit = Number(st.limit), offset = Number(st.offset)
  const q = useQuery({ queryKey: key('admin', 'audit', st), queryFn: ({ signal }) => adminApi.audit({ category: st.category, outcome: st.outcome, actor_user_id: st.actor_user_id, resource_id: st.resource_id, correlation_id: st.correlation_id, start: st.start, end: st.end, limit, offset }, signal), placeholderData: (p) => p })
  const [open, setOpen] = useState<Row | null>(null)
  const [verify, setVerify] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const bad = !!st.start && !!st.end && st.end < st.start

  const columns = useMemo<ColumnDef<Row, unknown>[]>(() => [
    { header: 'Time', cell: ({ row: { original: r } }) => <time dateTime={s(r.occurred_at, '')} title={s(r.occurred_at)}>{formatDateTime(r.occurred_at as string)}</time> },
    { header: 'Category', cell: ({ row: { original: r } }) => s(r.category) },
    { header: 'Event', cell: ({ row: { original: r } }) => <Mono>{s(r.event_type)}</Mono> },
    { header: 'Actor', cell: ({ row: { original: r } }) => <Mono>{s(r.actor_user_id).slice(0, 8)}</Mono> },
    { header: 'Resource', cell: ({ row: { original: r } }) => <span className="text-xs">{s(r.resource_type, '')} <Mono>{s(r.resource_id, '').slice(0, 8)}</Mono></span> },
    { header: 'Outcome', cell: ({ row: { original: r } }) => <StatusBadge value={s(r.outcome, '')} /> },
    { header: 'Correlation', cell: ({ row: { original: r } }) => r.correlation_id ? <button className="font-mono text-xs text-primary underline" onClick={(e) => { e.stopPropagation(); set({ correlation_id: s(r.correlation_id) }) }}>{s(r.correlation_id).slice(0, 8)}</button> : '–' },
    { header: 'Detail', cell: ({ row: { original: r } }) => <Button size="sm" variant="ghost" onClick={() => setOpen(r)}>Details</Button> },
  ], [set])

  return (
    <>
      <PageHeader title="Audit log" description="Events are shown exactly as the backend recorded them." actions={<>
        <Button variant="secondary" loading={busy} onClick={async () => { setBusy(true); try { const f = await adminApi.auditExport({ category: st.category, start: st.start, end: st.end }); toast.success(`Downloaded ${f}. Exports are recorded in the audit log.`) } catch (e) { toast.error(e instanceof ApiError ? e.message : 'Export failed.') } finally { setBusy(false) } }}>Export CSV</Button>
        <Button onClick={async () => { setBusy(true); try { const r = await adminApi.auditVerify(); const ok = r.valid === true || r.ok === true || r.status === 'ok' || (r.broken_at === undefined && r.first_broken_seq === undefined && r.broken_at_seq === undefined)
          const broken = r.broken_at ?? r.first_broken_seq ?? r.broken_at_seq
          setVerify(ok ? { ok, text: `Chain verified: ${n(r.events ?? r.checked ?? r.count) ?? 'all'} events` } : { ok, text: `Chain broken at sequence ${s(broken)}. Escalate to your security officer.` }) } catch (e) { toast.error(e instanceof ApiError ? e.message : 'Verification failed.') } finally { setBusy(false) } }}>Verify integrity</Button>
      </>} />
      {verify && <InlineAlert className="mb-3" tone={verify.ok ? 'success' : 'danger'} title={verify.text}>{verify.ok ? <span className="flex items-center gap-1"><ShieldCheck className="h-4 w-4" aria-hidden />The hash chain is intact.</span> : <span className="flex items-center gap-1"><ShieldX className="h-4 w-4" aria-hidden />Tampering or data loss is possible.</span>}</InlineAlert>}
      <div className="mb-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Category">{(p) => <Select {...p} value={st.category} onChange={(e) => set({ category: e.target.value })}><option value="">All</option>{CATEGORIES.map((c) => <option key={c}>{c}</option>)}</Select>}</Field>
        <Field label="Outcome">{(p) => <Select {...p} value={st.outcome} onChange={(e) => set({ outcome: e.target.value })}><option value="">All</option><option value="success">Success</option><option value="denied">Denied</option><option value="failure">Failure</option></Select>}</Field>
        <Field label="From">{(p) => <Input {...p} type="date" value={st.start} onChange={(e) => set({ start: e.target.value })} />}</Field>
        <Field label="To" error={bad ? 'Must be on or after the start date.' : undefined}>{(p) => <Input {...p} type="date" value={st.end} onChange={(e) => set({ end: e.target.value })} />}</Field>
        <Field label="Actor user id">{(p) => <Input {...p} value={st.actor_user_id} onChange={(e) => set({ actor_user_id: e.target.value.trim() })} />}</Field>
        <Field label="Resource id">{(p) => <Input {...p} value={st.resource_id} onChange={(e) => set({ resource_id: e.target.value.trim() })} />}</Field>
        <Field label="Correlation id" hint="Shows every event of one request">{(p) => <Input {...p} value={st.correlation_id} onChange={(e) => set({ correlation_id: e.target.value.trim() })} />}</Field>
        <div className="flex items-end"><Button variant="ghost" onClick={() => set({ category: '', outcome: '', actor_user_id: '', resource_id: '', correlation_id: '', start: '', end: '' })}>Clear filters</Button></div>
      </div>
      <DataTable caption="Audit events" columns={columns} rows={bad ? [] : q.data?.items} total={q.data?.total} limit={limit} offset={offset} loading={q.isFetching} error={q.error} onRetry={() => void q.refetch()}
        rowKey={(r) => s(r.event_id ?? r.seq ?? `${r.occurred_at}${r.event_type}${r.resource_id}`)} onPage={(o, l) => set({ offset: String(o), limit: String(l) }, { keepOffset: true })} />
      <Modal open={!!open} onOpenChange={(o) => !o && setOpen(null)} variant="drawer" title="Audit event">
        {open && <div className="space-y-3"><KeyValueList items={[{ label: 'Time', value: formatDateTime(open.occurred_at as string) }, { label: 'Category', value: s(open.category) }, { label: 'Event', value: <Mono>{s(open.event_type)}</Mono> }, { label: 'Outcome', value: s(open.outcome) },
          { label: 'Actor', value: <Mono>{s(open.actor_user_id)}</Mono> }, { label: 'Correlation id', value: <Mono>{s(open.correlation_id)}</Mono> }]} /><JsonViewer value={open.detail ?? open} /></div>}
      </Modal>
    </>
  )
}
