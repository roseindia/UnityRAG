import { useQuery } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { useMemo, useState } from 'react'
import { adminApi } from '@/services/api/adminApi'
import { useUrlState } from '@/hooks/useUrlState'
import { Button } from '@/components/ui/button'
import { Checkbox, Field, Input, Select, Textarea } from '@/components/ui/form'
import { Modal } from '@/components/ui/dialog'
import { DataTable } from '@/components/tables/DataTable'
import { InlineAlert } from '@/components/feedback/states'
import { KeyValueList, Mono, PageHeader, StatusBadge } from '@/components/common/display'
import { formatDateTime, humanize, timeAgo } from '@/utils/format'
import { s, useTenantKey, useWrite, type Row } from './common'

const DEFAULTS = { status: '', category: '', offset: '0', limit: '25' }
const STATUSES = ['new', 'triaged', 'in_progress', 'resolved', 'rejected']
const SEV: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 }

export default function FeedbackPage() {
  const key = useTenantKey()
  const [st, set] = useUrlState(DEFAULTS)
  const limit = Number(st.limit), offset = Number(st.offset)
  const q = useQuery({ queryKey: key('admin', 'feedback', st), queryFn: () => adminApi.feedback({ status: st.status, category: st.category, limit, offset }), placeholderData: (p) => p })
  const [open, setOpen] = useState<Row | null>(null)
  const [status, setStatus] = useState('new')
  const [assigned, setAssigned] = useState('')
  const [resolution, setResolution] = useState('')
  const [golden, setGolden] = useState(false)
  const save = useWrite(() => adminApi.updateFeedback(s(open!.feedback_id), { status, assigned_to: assigned || undefined, resolution: resolution || undefined, golden_candidate: golden }),
    { invalidate: [['admin', 'feedback']], success: 'Feedback updated.', onSuccess: () => setOpen(null) })
  const items = useMemo(() => [...(q.data?.items ?? [])].sort((a, b) => (SEV[s(a.severity, 'low')] ?? 9) - (SEV[s(b.severity, 'low')] ?? 9)), [q.data])
  const columns = useMemo<ColumnDef<Row, unknown>[]>(() => [
    { header: 'Severity', cell: ({ row: { original: r } }) => <StatusBadge value={s(r.severity, '')} /> },
    { header: 'Category', cell: ({ row: { original: r } }) => humanize(s(r.category, '')) },
    { header: 'Rating', cell: ({ row: { original: r } }) => r.rating === 1 ? 'Helpful' : r.rating === -1 ? 'Not helpful' : '–' },
    { header: 'Status', cell: ({ row: { original: r } }) => <StatusBadge value={s(r.status, '')} /> },
    { header: 'Comment', cell: ({ row: { original: r } }) => <span className="block max-w-xs truncate">{s(r.comment)}</span> },
    { header: 'Age', cell: ({ row: { original: r } }) => timeAgo(r.created_at as string) },
    { header: 'Review', cell: ({ row: { original: r } }) => <Button size="sm" variant="secondary" onClick={() => { setOpen(r); setStatus(s(r.status, 'new')); setAssigned(s(r.assigned_to, '')); setResolution(s(r.resolution, '')); setGolden(Boolean(r.golden_candidate)) }}>Review</Button> },
  ], [])
  return (
    <>
      <PageHeader title="Feedback review" description="Queue ordered by severity. Answer text is not shown here; this queue holds feedback records only." />
      <div className="mb-3 grid gap-2 sm:grid-cols-3">
        <Field label="Status">{(p) => <Select {...p} value={st.status} onChange={(e) => set({ status: e.target.value })}><option value="">All</option>{STATUSES.map((x) => <option key={x} value={x}>{humanize(x)}</option>)}</Select>}</Field>
        <Field label="Category">{(p) => <Select {...p} value={st.category} onChange={(e) => set({ category: e.target.value })}><option value="">All</option>{['incorrect', 'outdated', 'unsafe', 'missing_source', 'wrong_version', 'access', 'document_error', 'other', 'rating'].map((x) => <option key={x} value={x}>{humanize(x)}</option>)}</Select>}</Field>
      </div>
      <DataTable caption="Feedback" columns={columns} rows={q.data ? items : undefined} total={q.data?.total} limit={limit} offset={offset} loading={q.isFetching} error={q.error} onRetry={() => void q.refetch()}
        rowKey={(r) => s(r.feedback_id)} onPage={(o, l) => set({ offset: String(o), limit: String(l) }, { keepOffset: true })} />
      <Modal open={!!open} onOpenChange={(o) => !o && setOpen(null)} variant="drawer" title="Feedback record" footer={<><Button variant="secondary" onClick={() => setOpen(null)}>Cancel</Button><Button loading={save.isPending} onClick={() => save.mutate(undefined)}>Save</Button></>}>
        {open && <div className="space-y-4">
          <KeyValueList items={[{ label: 'Category', value: humanize(s(open.category, '')) }, { label: 'Severity', value: humanize(s(open.severity, '')) }, { label: 'Rating', value: s(open.rating) }, { label: 'Received', value: formatDateTime(open.created_at as string) },
            { label: 'Linked message', value: <Mono>{s(open.message_id)}</Mono> }, { label: 'Linked search', value: <Mono>{s(open.search_id)}</Mono> }]} />
          <div><p className="text-xs font-medium uppercase text-ink-muted">User comment</p><p className="mt-1 whitespace-pre-wrap rounded-control bg-canvas p-2">{s(open.comment, 'No comment.')}</p></div>
          <InlineAlert>The answer itself is not shown: administrators do not have content access.</InlineAlert>
          <Field label="Status">{(p) => <Select {...p} value={status} onChange={(e) => setStatus(e.target.value)}>{STATUSES.map((x) => <option key={x} value={x}>{humanize(x)}</option>)}</Select>}</Field>
          <Field label="Assigned to (user id)">{(p) => <Input {...p} value={assigned} onChange={(e) => setAssigned(e.target.value)} />}</Field>
          <Field label="Resolution">{(p) => <Textarea {...p} value={resolution} onChange={(e) => setResolution(e.target.value)} />}</Field>
          <Checkbox label="Candidate for the evaluation set" checked={golden} onChange={(e) => setGolden(e.target.checked)} />
        </div>}
      </Modal>
    </>
  )
}
