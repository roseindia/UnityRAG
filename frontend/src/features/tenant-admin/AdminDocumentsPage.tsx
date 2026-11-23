import { useQuery } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { adminApi } from '@/services/api/adminApi'
import { useUrlState } from '@/hooks/useUrlState'
import { useDebounced } from '@/hooks/useMisc'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader, Badge } from '@/components/ui/card'
import { Field, Input, Select } from '@/components/ui/form'
import { Modal } from '@/components/ui/dialog'
import { AccessRuleEditor, type Rule } from '@/components/forms/AccessRuleEditor'
import { DataTable } from '@/components/tables/DataTable'
import { ConfirmDialog } from '@/components/dialogs/ConfirmDialog'
import { InlineAlert, QueryState } from '@/components/feedback/states'
import { KeyValueList, Mono, PageHeader, StatusBadge } from '@/components/common/display'
import { StageTimeline } from '@/features/ingestion/JobTracker'
import { DOCUMENT_TYPES, LIFECYCLE_STATES, type DocumentRow, type IngestionJob } from '@/types/api'
import { formatBytes, formatDateOnly, formatDateTime, humanize } from '@/utils/format'
import { s, useTenantKey, useWrite, type Row } from './common'

const DEFAULTS = { q: '', collection_id: '', lifecycle_state: '', document_type: '', sort: 'updated_at', offset: '0', limit: '50' }

export function AdminDocumentsPage() {
  const key = useTenantKey()
  const nav = useNavigate()
  const [st, set] = useUrlState(DEFAULTS)
  const q = useDebounced(st.q)
  const limit = Number(st.limit), offset = Number(st.offset)
  const cols = useQuery({ queryKey: key('admin', 'collections'), queryFn: adminApi.collections, staleTime: 60_000 })
  const docs = useQuery({ queryKey: key('admin', 'documents', { ...st, q }), queryFn: ({ signal }) => adminApi.documents({ q, collection_id: st.collection_id, lifecycle_state: st.lifecycle_state, document_type: st.document_type, sort: st.sort, limit, offset }, signal), placeholderData: (p) => p })
  const name = useMemo(() => new Map((cols.data ?? []).map((c) => [s(c.collection_id), s(c.name)])), [cols.data])
  const columns = useMemo<ColumnDef<DocumentRow, unknown>[]>(() => [
    { header: 'Title', cell: ({ row: { original: d } }) => <Link className="font-medium text-primary hover:underline" to={`/admin/documents/${d.document_id}`}>{d.title}</Link> },
    { header: 'Type', cell: ({ row: { original: d } }) => humanize(d.document_type) },
    { header: 'Collection', cell: ({ row: { original: d } }) => name.get(d.collection_id) ?? '–' },
    { header: 'Lifecycle', cell: ({ row: { original: d } }) => <StatusBadge value={d.lifecycle_state} /> },
    { header: 'Classification', cell: ({ row: { original: d } }) => humanize(d.classification) },
    { header: 'Hold', cell: ({ row: { original: d } }) => d.legal_hold ? <Badge tone="danger">Legal hold</Badge> : '–' },
    { header: 'Size', cell: ({ row: { original: d } }) => formatBytes(d.size_bytes) },
    { header: 'Updated', cell: ({ row: { original: d } }) => formatDateTime(d.updated_at) },
  ], [name])
  return (
    <>
      <PageHeader title="Document administration" description="Metadata, lifecycle and access only. Administrators cannot read document text here." />
      <div className="mb-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
        <Field label="Search title">{(p) => <Input {...p} type="search" value={st.q} onChange={(e) => set({ q: e.target.value })} />}</Field>
        <Field label="Collection">{(p) => <Select {...p} value={st.collection_id} onChange={(e) => set({ collection_id: e.target.value })}><option value="">All</option>{cols.data?.map((c) => <option key={s(c.collection_id)} value={s(c.collection_id)}>{s(c.name)}</option>)}</Select>}</Field>
        <Field label="Lifecycle">{(p) => <Select {...p} value={st.lifecycle_state} onChange={(e) => set({ lifecycle_state: e.target.value })}><option value="">All</option>{LIFECYCLE_STATES.map((l) => <option key={l} value={l}>{humanize(l)}</option>)}</Select>}</Field>
        <Field label="Type">{(p) => <Select {...p} value={st.document_type} onChange={(e) => set({ document_type: e.target.value })}><option value="">All</option>{DOCUMENT_TYPES.map((l) => <option key={l} value={l}>{humanize(l)}</option>)}</Select>}</Field>
        <Field label="Sort by">{(p) => <Select {...p} value={st.sort} onChange={(e) => set({ sort: e.target.value })}><option value="updated_at">Recently updated</option><option value="created_at">Recently created</option><option value="title">Title</option><option value="size">Size</option></Select>}</Field>
      </div>
      <DataTable caption="Documents" columns={columns} rows={docs.data?.items} total={docs.data?.total} limit={limit} offset={offset} loading={docs.isFetching} error={docs.error}
        onRetry={() => void docs.refetch()} rowKey={(d) => d.document_id} onRowClick={(d) => nav(`/admin/documents/${d.document_id}`)} onPage={(o, l) => set({ offset: String(o), limit: String(l) }, { keepOffset: true })} />
    </>
  )
}

export function AdminDocumentDetailPage() {
  const { id = '' } = useParams()
  const key = useTenantKey()
  const q = useQuery({ queryKey: key('admin', 'document', id), queryFn: () => adminApi.document(id), retry: false })
  const jobs = useQuery({ queryKey: key('admin', 'document', id, 'jobs'), queryFn: () => adminApi.ingestionJobs({ document_id: id, limit: 20 }), retry: false })
  const [lc, setLc] = useState<{ state: string } | null>(null)
  const [hold, setHold] = useState<boolean | null>(null)
  const inv = [['admin', 'document', id], ['admin', 'documents']]
  const lifecycleState = useState('published')
  const access = useWrite((rules: Rule[]) => adminApi.setDocumentAccess(id, rules as unknown as Record<string, unknown>[]), { invalidate: [['admin', 'document', id], ['search']], success: 'Access rules saved.', silentError: true })
  const reprocess = useWrite(() => adminApi.reprocess(id), { invalidate: [['admin', 'document', id, 'jobs']], success: 'Re-processing started. Track it under Ingestion.' })
  const reindex = useWrite(() => adminApi.reindex(id), { invalidate: [['admin', 'document', id, 'jobs']], success: 'Re-indexing started. Track it under Ingestion.' })
  return (
    <QueryState query={q}>
      {(d) => {
        const rules = (d.access ?? d.entries) as Rule[] | undefined
        const held = Boolean(d.legal_hold)
        const blocked = (st: string) => held && st === 'withdrawn'
        return (
          <>
            <PageHeader title={s(d.title)} description="Administrative view: no text preview." actions={<>
              <Button variant="secondary" onClick={() => setLc({ state: s(d.lifecycle_state) })}>Change lifecycle</Button>
              <Button variant="secondary" onClick={() => setHold(!held)}>{held ? 'Release legal hold' : 'Place legal hold'}</Button>
              <Button variant="secondary" loading={reprocess.isPending} onClick={() => reprocess.mutate(undefined)} title="Re-parse the original file">Reprocess</Button>
              <Button variant="secondary" loading={reindex.isPending} onClick={() => reindex.mutate(undefined)} title="Re-embed with the active model">Reindex</Button>
            </>} />
            {held && <InlineAlert tone="warning" className="mb-3" title="Legal hold in place">Delete and withdraw are disabled while the hold is on.</InlineAlert>}
            <div className="grid gap-4 lg:grid-cols-2">
              <Card><CardHeader title="Metadata" /><CardBody><KeyValueList items={[
                { label: 'Lifecycle', value: <StatusBadge value={s(d.lifecycle_state, '')} /> }, { label: 'Type', value: humanize(s(d.document_type, '')) },
                { label: 'Line', value: humanize(s(d.insurance_line, '')) }, { label: 'Classification', value: humanize(s(d.classification, '')) },
                { label: 'Effective', value: `${formatDateOnly(d.effective_from as string)} – ${formatDateOnly(d.effective_to as string)}` }, { label: 'Size', value: formatBytes(d.size_bytes as number) },
                { label: 'Checksum', value: <Mono>{s(d.checksum_sha256 ?? (d.versions as Row[] | undefined)?.[0]?.checksum_sha256, '–').slice(0, 16)}…</Mono> }, { label: 'Updated', value: formatDateTime(d.updated_at as string) },
              ]} /></CardBody></Card>
              <Card><CardHeader title="Versions" /><div className="table-wrap border-0"><table className="tbl"><caption className="sr-only">Versions</caption><thead><tr><th scope="col">#</th><th scope="col">State</th><th scope="col">File</th><th scope="col">Pages</th></tr></thead>
                <tbody>{((d.versions ?? []) as Row[]).map((v) => <tr key={s(v.version_id)}><td>{s(v.version_seq)}</td><td><StatusBadge value={s(v.state, '')} /></td><td>{s(v.original_filename)}</td><td>{s(v.page_count)}</td></tr>)}</tbody></table></div></Card>
              {Array.isArray(d.lifecycle_history) && <Card className="lg:col-span-2"><CardHeader title="Lifecycle history" /><ul className="p-4 text-sm">{(d.lifecycle_history as Row[]).map((h, i) => <li key={i}>{formatDateTime(h.created_at as string)} · {humanize(s(h.to_state ?? h.state, ''))} · {s(h.reason, '')}</li>)}</ul></Card>}
              <Card className="lg:col-span-2"><CardHeader title="Document access rules" description="Collection access also applies." /><CardBody>
                {rules ? <AccessRuleEditor initial={rules} onSave={(r) => access.mutateAsync(r)} /> : <InlineAlert tone="warning">Access rules are not included in this response, so they cannot be edited safely from here.</InlineAlert>}
              </CardBody></Card>
              <Card className="lg:col-span-2"><CardHeader title="Ingestion jobs" /><QueryState query={jobs} isEmpty={(j) => j.items.length === 0} empty={<p className="p-4 text-sm text-ink-muted">No jobs recorded.</p>}>
                {(j) => <ul>{j.items.map((x: IngestionJob) => <li key={x.job_id} className="border-b border-line px-4 py-2 last:border-0"><div className="mb-1 flex items-center gap-2"><StatusBadge value={x.status} /><span className="text-xs text-ink-muted">{humanize(x.job_type)} · {formatDateTime(x.queued_at)}</span></div><StageTimeline job={x} /></li>)}</ul>}</QueryState></Card>
            </div>
            <Modal open={!!lc} onOpenChange={(o) => !o && setLc(null)} title="Change lifecycle state" size="sm" footer={null}>
              {lc && <LifecycleForm current={lc.state} held={held} blocked={blocked} onDone={() => { setLc(null); inv.forEach(() => undefined); void q.refetch() }} id={id} />}
            </Modal>
            <ConfirmDialog open={hold !== null} onOpenChange={(o) => !o && setHold(null)} level="reason" destructive={hold === true} title={hold ? 'Place legal hold' : 'Release legal hold'} confirmLabel={hold ? 'Place hold' : 'Release hold'}
              description={hold ? 'While the hold is on, the document cannot be deleted or withdrawn.' : 'The document can be deleted or withdrawn again.'}
              onConfirm={async (reason) => { await adminApi.legalHold(id, hold === true, reason); toast.success(hold ? 'Legal hold placed.' : 'Legal hold released.'); void q.refetch() }} />
            <span hidden>{lifecycleState[0]}</span>
          </>
        )
      }}
    </QueryState>
  )
}

function LifecycleForm({ current, held, blocked, onDone, id }: { current: string; held: boolean; blocked: (s: string) => boolean; onDone: () => void; id: string }) {
  const [state, setState] = useState(current)
  const [reason, setReason] = useState('')
  const needsReason = ['withdrawn', 'archived', 'expired'].includes(state)
  const m = useWrite(() => adminApi.lifecycle(id, state, reason || undefined), { success: 'Lifecycle updated.', onSuccess: onDone })
  const bad = blocked(state) || (needsReason && reason.trim().length < 5) || state === current
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (!bad) m.mutate(undefined) }}>
      <Field label="New state">{(p) => <Select {...p} value={state} onChange={(e) => setState(e.target.value)}>{['published', 'in_review', 'approved', 'archived', 'withdrawn', 'expired'].map((l) => <option key={l} value={l}>{humanize(l)}</option>)}</Select>}</Field>
      <Field label="Reason" required={needsReason} hint={needsReason ? 'At least 5 characters. Recorded in the audit log.' : 'Optional'}>{(p) => <Input {...p} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
      {held && state === 'withdrawn' && <InlineAlert tone="warning">Withdrawal is disabled while a legal hold is on.</InlineAlert>}
      <div className="flex justify-end"><Button type="submit" loading={m.isPending} disabled={bad}>Apply</Button></div>
    </form>
  )
}
