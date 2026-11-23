import { useQuery } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { Upload } from 'lucide-react'
import { useMemo } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '@/contexts/AuthContext'
import { documentApi } from '@/services/api/documentApi'
import { adminApi } from '@/services/api/adminApi'
import { usePermissions } from '@/hooks/usePermissions'
import { useUrlState } from '@/hooks/useUrlState'
import { useDebounced } from '@/hooks/useMisc'
import { Can } from '@/app/guards'
import { Button } from '@/components/ui/button'
import { Field, Input, Select } from '@/components/ui/form'
import { DataTable } from '@/components/tables/DataTable'
import { EmptyState } from '@/components/feedback/states'
import { PageHeader, StatusBadge } from '@/components/common/display'
import { DOCUMENT_TYPES, LINES_OF_BUSINESS, type Collection, type DocumentRow } from '@/types/api'
import { formatDateTime, formatBytes, humanize } from '@/utils/format'

const DEFAULTS = { q: '', collection_id: '', document_type: '', insurance_line: '', sort: 'updated_at', offset: '0', limit: '50' }

export default function DocumentsPage() {
  const { profile } = useAuth()
  const nav = useNavigate()
  const [s, set] = useUrlState(DEFAULTS)
  const q = useDebounced(s.q)
  const limit = Number(s.limit), offset = Number(s.offset)
  // Administrators see every collection of the tenant; other users only those their access rules allow.
  const perms = usePermissions()
  const seesAll = perms.canAny(['admin.collections.manage', 'admin.documents.manage'])
  const cols = useQuery({ queryKey: ['collections', 'usable', seesAll ? 'admin' : 'user'], queryFn: () => (seesAll ? adminApi.collections() : documentApi.collections()) as Promise<Collection[]>, staleTime: 60_000 })
  const docs = useQuery({
    queryKey: [profile?.tenant_id, 'documents', { ...s, q }],
    queryFn: ({ signal }) => documentApi.list({ q, collection_id: s.collection_id, document_type: s.document_type, insurance_line: s.insurance_line, sort: s.sort, limit, offset }, signal),
    placeholderData: (prev) => prev,
  })
  const colName = useMemo(() => new Map((cols.data ?? []).map((c) => [c.collection_id, c.name])), [cols.data])
  const columns = useMemo<ColumnDef<DocumentRow, unknown>[]>(() => [
    { header: 'Title', cell: ({ row: { original: d } }) => <Link className="font-medium text-primary hover:underline" to={`/documents/${d.document_id}`}>{d.title}</Link> },
    { header: 'Type', cell: ({ row: { original: d } }) => humanize(d.document_type) },
    { header: 'Line', cell: ({ row: { original: d } }) => humanize(d.insurance_line) },
    { header: 'Collection', cell: ({ row: { original: d } }) => colName.get(d.collection_id) ?? '–' },
    { header: 'Lifecycle', cell: ({ row: { original: d } }) => <StatusBadge value={d.lifecycle_state} /> },
    { header: 'Size', cell: ({ row: { original: d } }) => formatBytes(d.size_bytes) },
    { header: 'Updated', cell: ({ row: { original: d } }) => formatDateTime(d.updated_at) },
  ], [colName])

  return (
    <>
      <PageHeader title="Documents" description="Approved documents you are allowed to see." actions={<Can permission="documents.upload"><Button asChild><Link to="/documents/upload"><Upload className="h-4 w-4" aria-hidden />Upload</Link></Button></Can>} />
      <div className="mb-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
        <Field label="Search title">{(p) => <Input {...p} type="search" data-focus-target value={s.q} onChange={(e) => set({ q: e.target.value })} />}</Field>
        <Field label="Collection">{(p) => <Select {...p} value={s.collection_id} onChange={(e) => set({ collection_id: e.target.value })}><option value="">All</option>{cols.data?.map((c) => <option key={c.collection_id} value={c.collection_id}>{c.name}</option>)}</Select>}</Field>
        <Field label="Document type">{(p) => <Select {...p} value={s.document_type} onChange={(e) => set({ document_type: e.target.value })}><option value="">All</option>{DOCUMENT_TYPES.map((t) => <option key={t} value={t}>{humanize(t)}</option>)}</Select>}</Field>
        <Field label="Line of business">{(p) => <Select {...p} value={s.insurance_line} onChange={(e) => set({ insurance_line: e.target.value })}><option value="">All</option>{LINES_OF_BUSINESS.map((t) => <option key={t} value={t}>{humanize(t)}</option>)}</Select>}</Field>
        <Field label="Sort by">{(p) => <Select {...p} value={s.sort} onChange={(e) => set({ sort: e.target.value })}><option value="updated_at">Recently updated</option><option value="created_at">Recently created</option><option value="title">Title</option><option value="size">Size</option></Select>}</Field>
      </div>
      <DataTable caption="Documents" columns={columns} rows={docs.data?.items} total={docs.data?.total} limit={limit} offset={offset} loading={docs.isFetching}
        error={docs.error} onRetry={() => void docs.refetch()} rowKey={(d) => d.document_id} onRowClick={(d) => nav(`/documents/${d.document_id}`)}
        onPage={(o, l) => set({ offset: String(o), limit: String(l) }, { keepOffset: true })}
        empty={<EmptyState title="No documents found" description="Try different filters, or upload a document if you have permission." />} />
    </>
  )
}
