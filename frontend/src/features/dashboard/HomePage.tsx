import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { useState } from 'react'
import { Send } from 'lucide-react'
import { useAuth } from '@/contexts/AuthContext'
import { chatApi } from '@/services/api/chatApi'
import { searchApi } from '@/services/api/searchApi'
import { documentApi } from '@/services/api/documentApi'
import { Can } from '@/app/guards'
import { usePermissions } from '@/hooks/usePermissions'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader, Badge } from '@/components/ui/card'
import { Textarea } from '@/components/ui/form'
import { EmptyState, QueryState } from '@/components/feedback/states'
import { PageHeader } from '@/components/common/display'
import { humanize, timeAgo } from '@/utils/format'

function examplesFor(lines: string[]): string[] {
  const l = humanize(lines[0] ?? 'motor').toLowerCase()
  return [`What does the ${l} policy wording say about exclusions?`, `Which documents are needed to support a ${l} claim?`, `What are the referral rules for ${l} renewals?`]
}

export default function HomePage() {
  const { profile } = useAuth()
  const p = usePermissions()
  const nav = useNavigate()
  const [q, setQ] = useState('')
  const t = profile?.tenant_id
  const convs = useQuery({ queryKey: [t, 'home', 'conversations'], queryFn: ({ signal }) => chatApi.conversations({ limit: 5 }, signal), enabled: p.can('chat.use') })
  const searches = useQuery({ queryKey: [t, 'home', 'searches'], queryFn: () => searchApi.history({ limit: 5 }), enabled: p.can('search.use') })
  const cols = useQuery({ queryKey: [t, 'home', 'collections'], queryFn: documentApi.collections, enabled: p.can('collections.read'), staleTime: 5 * 60_000 })
  const firstUse = convs.data && convs.data.items.length === 0 && searches.data && searches.data.items.length === 0

  return (
    <>
      <PageHeader title={`Welcome${profile?.display_name ? `, ${profile.display_name.split(' ')[0]}` : ''}`} description="Continue recent work or ask a new question. Answers are AI-generated guidance based on approved documents." />
      <Can permission="chat.use">
        <Card className="mb-4"><CardBody>
          <form onSubmit={(e) => { e.preventDefault(); if (q.trim()) nav('/chat', { state: { ask: q.trim() } }) }} className="flex items-end gap-2">
            <Textarea aria-label="Ask a question" data-focus-target rows={2} maxLength={4000} placeholder="Ask a question…" value={q} onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (q.trim()) nav('/chat', { state: { ask: q.trim() } }) } }} />
            <Button type="submit" disabled={!q.trim()}><Send className="h-4 w-4" aria-hidden />Ask</Button>
          </form>
          {firstUse && <div className="mt-3"><p className="mb-1 text-xs text-ink-muted">Try one of these:</p>
            <div className="flex flex-wrap gap-2">{examplesFor(profile?.lines_of_business ?? []).map((e) => <Button key={e} variant="secondary" size="sm" className="whitespace-normal text-left" onClick={() => setQ(e)}>{e}</Button>)}</div></div>}
        </CardBody></Card>
      </Can>
      <div className="grid gap-4 lg:grid-cols-2">
        <Can permission="chat.use">
          <Card><CardHeader title="Recent conversations" actions={<Button asChild variant="link"><Link to="/history">View all</Link></Button>} />
            <QueryState query={convs} isEmpty={(d) => d.items.length === 0} empty={<EmptyState title="No conversations yet" description="Your recent chats appear here." />}>
              {(d) => <ul>{d.items.map((c) => <li key={c.conversation_id} className="border-b border-line last:border-0"><Link className="block px-4 py-2 hover:bg-canvas" to={`/chat/${c.conversation_id}`}><span className="font-medium">{c.title || 'Untitled conversation'}</span><span className="block text-xs text-ink-muted">{timeAgo(c.updated_at)}</span></Link></li>)}</ul>}
            </QueryState></Card>
        </Can>
        <Can permission="search.use">
          <Card><CardHeader title="Recent searches" actions={<Button asChild variant="link"><Link to="/history?tab=searches">View all</Link></Button>} />
            <QueryState query={searches} isEmpty={(d) => d.items.length === 0} empty={<EmptyState title="No searches yet" />}>
              {(d) => <ul>{d.items.map((s) => <li key={s.search_id} className="border-b border-line px-4 py-2 last:border-0">
                <Link className="font-medium hover:underline" to={s.query_text ? `/search?q=${encodeURIComponent(s.query_text)}` : '/search'}>{s.query_text ?? '(query text not stored)'}</Link>
                <span className="block text-xs text-ink-muted">{s.result_count} results · {timeAgo(s.created_at)}</span></li>)}</ul>}
            </QueryState></Card>
        </Can>
        <Can permission="collections.read">
          <Card className="lg:col-span-2"><CardHeader title="Collections you can access" description="Select one to search within it." />
            <QueryState query={cols} isEmpty={(d) => d.length === 0} empty={<EmptyState title="No collections available" description="Ask your administrator for access." />}>
              {(d) => <div className="flex flex-wrap gap-2 p-4">{d.map((c) => <Link key={c.collection_id} to={`/search?collection_ids=${c.collection_id}`}><Badge tone="info" className="px-3 py-1 text-sm">{c.name}</Badge></Link>)}</div>}
            </QueryState></Card>
        </Can>
        <Can anyOf={['department.analytics.view', 'admin.analytics.view']}>
          <Card><CardHeader title="Department usage" /><CardBody><p className="mb-2 text-sm text-ink-muted">Searches, chats and tokens for your department.</p><Button asChild variant="secondary"><Link to="/analytics/department">Open department analytics</Link></Button></CardBody></Card>
        </Can>
      </div>
    </>
  )
}
