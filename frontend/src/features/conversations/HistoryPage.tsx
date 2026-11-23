import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { useAuth } from '@/contexts/AuthContext'
import { chatApi } from '@/services/api/chatApi'
import { searchApi } from '@/services/api/searchApi'
import { ApiError } from '@/services/api/errors'
import { usePermissions } from '@/hooks/usePermissions'
import { useUrlState } from '@/hooks/useUrlState'
import { useDebounced } from '@/hooks/useMisc'
import { Button } from '@/components/ui/button'
import { Field, Input } from '@/components/ui/form'
import { Modal } from '@/components/ui/dialog'
import { Tabs } from '@/components/ui/tabs'
import { DataTable } from '@/components/tables/DataTable'
import { ConfirmDialog } from '@/components/dialogs/ConfirmDialog'
import { PageHeader } from '@/components/common/display'
import { Badge } from '@/components/ui/card'
import { formatDateTime, humanize } from '@/utils/format'
import type { ConversationSummary, SearchHistoryItem } from '@/types/api'

const DEFAULTS = { tab: 'conversations', q: '', offset: '0', limit: '25' }

function Conversations({ s, set }: { s: typeof DEFAULTS; set: ReturnType<typeof useUrlState<typeof DEFAULTS>>[1] }) {
  const { profile } = useAuth()
  const qc = useQueryClient()
  const q = useDebounced(s.q)
  const limit = Number(s.limit), offset = Number(s.offset)
  const query = useQuery({ queryKey: [profile?.tenant_id, 'conversations', 'history', q, limit, offset], queryFn: ({ signal }) => chatApi.conversations({ q, limit, offset }, signal) })
  const [renaming, setRenaming] = useState<ConversationSummary | null>(null)
  const [title, setTitle] = useState('')
  const [deleting, setDeleting] = useState<ConversationSummary | null>(null)
  const rename = useMutation({
    mutationFn: () => chatApi.rename(renaming!.conversation_id, title.trim()),
    onSuccess: () => { toast.success('Conversation renamed.'); setRenaming(null); void qc.invalidateQueries({ queryKey: [profile?.tenant_id, 'conversations'] }) },
    onError: (e) => toast.error((e as ApiError).message),
  })
  const columns = useMemo<ColumnDef<ConversationSummary, unknown>[]>(() => [
    { header: 'Title', cell: ({ row: { original: c } }) => <Link className="font-medium text-primary hover:underline" to={`/chat/${c.conversation_id}`}>{c.title || 'Untitled conversation'}</Link> },
    { header: 'Turns', cell: ({ row: { original: c } }) => Math.ceil(c.message_count / 2) },
    { header: 'Updated', cell: ({ row: { original: c } }) => formatDateTime(c.updated_at) },
    { header: 'Actions', cell: ({ row: { original: c } }) => (
      <span className="flex gap-1">
        <Button size="sm" variant="ghost" onClick={() => { setTitle(c.title); setRenaming(c) }}>Rename</Button>
        <Button size="sm" variant="ghost" onClick={() => { void chatApi.exportConversation(c.conversation_id).then(() => toast.success('Exported. The export includes the AI disclaimer.')).catch((e: ApiError) => toast.error(e.message)) }}>Export</Button>
        <Button size="sm" variant="ghost" className="text-danger" onClick={() => setDeleting(c)}>Delete</Button>
      </span>) },
  ], [])
  return (
    <div className="space-y-3">
      <Field label="Search conversations" className="max-w-sm">{(p) => <Input {...p} type="search" value={s.q} onChange={(e) => set({ q: e.target.value })} />}</Field>
      <DataTable caption="Conversations" columns={columns} rows={query.data?.items} total={query.data?.total} limit={limit} offset={offset} loading={query.isFetching}
        error={query.error} onRetry={() => void query.refetch()} rowKey={(c) => c.conversation_id} onPage={(o, l) => set({ offset: String(o), limit: String(l) }, { keepOffset: true })} />
      <Modal open={!!renaming} onOpenChange={(o) => !o && setRenaming(null)} title="Rename conversation" size="sm"
        footer={<><Button variant="secondary" onClick={() => setRenaming(null)}>Cancel</Button><Button loading={rename.isPending} disabled={!title.trim()} onClick={() => rename.mutate()}>Rename</Button></>}>
        <Field label="Title" required>{(p) => <Input {...p} maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} />}</Field>
      </Modal>
      <ConfirmDialog open={!!deleting} onOpenChange={(o) => !o && setDeleting(null)} title="Delete conversation" confirmLabel="Delete conversation"
        description={<>Delete <strong>{deleting?.title || 'this conversation'}</strong>? Conversations under legal hold cannot be deleted.</>}
        onConfirm={async () => { await chatApi.remove(deleting!.conversation_id); toast.success('Conversation deleted.'); void qc.invalidateQueries({ queryKey: [profile?.tenant_id, 'conversations'] }) }} />
    </div>
  )
}

function Searches({ s, set }: { s: typeof DEFAULTS; set: ReturnType<typeof useUrlState<typeof DEFAULTS>>[1] }) {
  const { profile } = useAuth()
  const limit = Number(s.limit), offset = Number(s.offset)
  const query = useQuery({ queryKey: [profile?.tenant_id, 'search', 'history', limit, offset], queryFn: () => searchApi.history({ limit, offset }) })
  const columns = useMemo<ColumnDef<SearchHistoryItem, unknown>[]>(() => [
    { header: 'Query', cell: ({ row: { original: r } }) => r.query_text ? <Link className="font-medium text-primary hover:underline" to={`/search?q=${encodeURIComponent(r.query_text)}&mode=${r.mode}`}>{r.query_text}</Link> : <span className="text-ink-muted">(query text not stored)</span> },
    { header: 'Mode', cell: ({ row: { original: r } }) => humanize(r.mode) },
    { header: 'Results', cell: ({ row: { original: r } }) => r.result_count },
    { header: 'Latency', cell: ({ row: { original: r } }) => <>{r.latency_ms} ms {r.cache_hit && <Badge>cached</Badge>}</> },
    { header: 'Date', cell: ({ row: { original: r } }) => formatDateTime(r.created_at) },
  ], [])
  return <DataTable caption="Search history" columns={columns} rows={query.data?.items} total={query.data?.total} limit={limit} offset={offset} loading={query.isFetching}
    error={query.error} onRetry={() => void query.refetch()} rowKey={(r) => r.search_id} onPage={(o, l) => set({ offset: String(o), limit: String(l) }, { keepOffset: true })} />
}

export default function HistoryPage() {
  const p = usePermissions()
  const [s, set] = useUrlState(DEFAULTS)
  return (
    <>
      <PageHeader title="History" description="Your conversations and searches." />
      <Tabs value={s.tab} onValueChange={(v) => set({ tab: v, offset: undefined, q: undefined })} tabs={[
        { value: 'conversations', label: 'Conversations', hidden: !p.can('chat.use'), content: <Conversations s={s} set={set} /> },
        { value: 'searches', label: 'Searches', hidden: !p.can('search.use'), content: <Searches s={s} set={set} /> },
      ]} />
    </>
  )
}
