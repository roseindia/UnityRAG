import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { MoreVertical, Plus } from 'lucide-react'
import { useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { chatApi } from '@/services/api/chatApi'
import { ApiError } from '@/services/api/errors'
import { useAuth } from '@/contexts/AuthContext'
import { useDebounced } from '@/hooks/useMisc'
import { Button } from '@/components/ui/button'
import { Field, Input } from '@/components/ui/form'
import { Menu } from '@/components/ui/menu'
import { Modal } from '@/components/ui/dialog'
import { ConfirmDialog } from '@/components/dialogs/ConfirmDialog'
import { EmptyState, ErrorState, LoadingBlock } from '@/components/feedback/states'
import { timeAgo } from '@/utils/format'
import { cn } from '@/utils/cn'
import type { ConversationSummary } from '@/types/api'

export function ConversationList({ activeId, onNew }: { activeId?: string; onNew: () => void }) {
  const { profile } = useAuth()
  const qc = useQueryClient()
  const nav = useNavigate()
  const [search, setSearch] = useState('')
  const q = useDebounced(search)
  const list = useQuery({ queryKey: [profile?.tenant_id, 'conversations', q], queryFn: ({ signal }) => chatApi.conversations({ q: q || undefined, limit: 50 }, signal) })
  const [renaming, setRenaming] = useState<ConversationSummary | null>(null)
  const [title, setTitle] = useState('')
  const [deleting, setDeleting] = useState<ConversationSummary | null>(null)

  const rename = useMutation({
    mutationFn: () => chatApi.rename(renaming!.conversation_id, title.trim()),
    onSuccess: () => { toast.success('Conversation renamed.'); setRenaming(null); void qc.invalidateQueries({ queryKey: [profile?.tenant_id, 'conversations'] }) },
    onError: (e) => toast.error((e as ApiError).message),
  })

  return (
    <div className="flex h-full flex-col">
      <div className="space-y-2 border-b border-line p-3">
        <Button className="w-full" onClick={onNew}><Plus className="h-4 w-4" aria-hidden />New conversation</Button>
        <Input type="search" placeholder="Search conversations" aria-label="Search conversations" value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>
      <div className="flex-1 overflow-y-auto">
        {list.isPending && <LoadingBlock rows={4} />}
        {list.isError && <ErrorState error={list.error} onRetry={() => void list.refetch()} />}
        {list.data && list.data.items.length === 0 && <EmptyState title={q ? 'No matching conversations' : 'No conversations yet'} description={q ? undefined : 'Ask your first question to start one.'} />}
        <ul>
          {list.data?.items.map((c) => (
            <li key={c.conversation_id} className="group flex items-center gap-1 pr-1">
              <NavLink to={`/chat/${c.conversation_id}`} className={cn('min-w-0 flex-1 px-3 py-2 hover:bg-canvas', c.conversation_id === activeId && 'bg-info-bg')}>
                <p className="truncate text-sm font-medium">{c.title || 'Untitled conversation'}</p>
                <p className="text-xs text-ink-muted">{timeAgo(c.updated_at)} · {c.message_count} messages</p>
              </NavLink>
              <Menu label={`Actions for ${c.title}`} trigger={<Button variant="ghost" size="icon" aria-label={`Actions for ${c.title || 'conversation'}`}><MoreVertical className="h-4 w-4" aria-hidden /></Button>} items={[
                { label: 'Rename', onSelect: () => { setTitle(c.title); setRenaming(c) } },
                { label: 'Export', onSelect: () => { void chatApi.exportConversation(c.conversation_id).then(() => toast.success('Exported. The export includes the AI disclaimer.')).catch((e: ApiError) => toast.error(e.message)) } },
                { label: 'Delete', danger: true, onSelect: () => setDeleting(c) },
              ]} />
            </li>
          ))}
        </ul>
      </div>
      <Modal open={!!renaming} onOpenChange={(o) => !o && setRenaming(null)} title="Rename conversation" size="sm"
        footer={<><Button variant="secondary" onClick={() => setRenaming(null)}>Cancel</Button><Button loading={rename.isPending} disabled={!title.trim()} onClick={() => rename.mutate()}>Rename</Button></>}>
        <form onSubmit={(e) => { e.preventDefault(); if (title.trim()) rename.mutate() }}>
          <Field label="Title" required>{(p) => <Input {...p} maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} />}</Field>
        </form>
      </Modal>
      <ConfirmDialog open={!!deleting} onOpenChange={(o) => !o && setDeleting(null)} title="Delete conversation"
        description={<>Delete <strong>{deleting?.title || 'this conversation'}</strong>? This cannot be undone. Conversations under legal hold cannot be deleted.</>}
        confirmLabel="Delete conversation"
        onConfirm={async () => {
          try {
            await chatApi.remove(deleting!.conversation_id)
            toast.success('Conversation deleted.')
            void qc.invalidateQueries({ queryKey: [profile?.tenant_id, 'conversations'] })
            if (deleting!.conversation_id === activeId) nav('/chat')
          } catch (e) {
            if (e instanceof ApiError && e.code === 'legal_hold') throw new ApiError({ status: 409, code: 'legal_hold' })
            throw e
          }
        }} />
    </div>
  )
}
