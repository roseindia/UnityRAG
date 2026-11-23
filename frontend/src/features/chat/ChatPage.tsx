import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Copy, Filter, Loader2, RefreshCw, Send, Square, ShieldAlert } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { useAuth } from '@/contexts/AuthContext'
import { chatApi } from '@/services/api/chatApi'
import { useMediaQuery } from '@/hooks/useMediaQuery'
import { useOnline } from '@/hooks/useMisc'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/card'
import { Modal } from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/form'
import { ErrorState, InlineAlert, LoadingBlock } from '@/components/feedback/states'
import { AiLabel, AnswerText, DisclaimerNote, EvidenceBadge, SourceCard } from '@/components/rag/evidence'
import { DocumentPreviewDrawer, type PreviewTarget } from '@/components/rag/DocumentPreviewDrawer'
import { RatingButtons, ReportDialog } from '@/components/rag/FeedbackControls'
import { ScopeFilterDialog, filterSummary } from '@/components/rag/ScopeFilterDialog'
import { ConversationList } from './ConversationList'
import { turnsFromConversation, useChatStream, type Turn } from './useChatStream'
import { copyWithFootnotes } from './copyAnswer'
import { env } from '@/config/env'
import { cn } from '@/utils/cn'
import { Can } from '@/app/guards'
import type { Citation, Filters } from '@/types/api'

const MAX = 4000
const EXAMPLES = ['Is flood damage covered under the motor policy?', 'What documents are needed to submit a property claim?', 'Which endorsements change the excess on a renewal?']

function AnswerCard({ turn, selectedCite, onSelect, onOpen, onRegenerate, last, inlineSources, onRephrase }: {
  turn: Turn; selectedCite: number | null; onSelect: (i: number) => void; onOpen: (c: Citation) => void
  onRegenerate: () => void; last: boolean; inlineSources: boolean; onRephrase: (text: string) => void
}) {
  const [report, setReport] = useState(false)
  const streaming = turn.state === 'streaming'
  const cites = turn.citations ?? []
  const status = turn.status ?? 'answered'
  return (
    <article className="max-w-3xl rounded-card border border-line bg-surface p-4" aria-busy={streaming} aria-label="Assistant answer">
      <header className="mb-2 flex flex-wrap items-center gap-2">
        <AiLabel />
        {!streaming && turn.state !== 'error' && <EvidenceBadge strength={turn.evidence} />}
        {turn.state === 'stopped' && <Badge tone="neutral">Stopped</Badge>}
        {turn.incomplete && turn.state !== 'stopped' && <Badge tone="warning">Incomplete</Badge>}
      </header>

      {status === 'needs_review' && <InlineAlert tone="warning" className="mb-2" title="Requires expert review before use">This answer should be checked by a subject-matter expert before it is relied on in a decision.</InlineAlert>}
      {status === 'blocked' ? (
        <InlineAlert tone="warning" title="This request can't be answered">{turn.text}</InlineAlert>
      ) : status === 'abstained' ? (
        <div className="rounded-card border border-line bg-canvas p-3">
          <p className="font-medium">No sufficient approved evidence</p>
          <p className="mt-1 text-sm">{turn.text}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button size="sm" variant="secondary" onClick={() => onRephrase('')}>Rephrase</Button>
            <Can permission="feedback.submit"><Button size="sm" variant="secondary" onClick={() => setReport(true)}>Report missing source</Button></Can>
          </div>
          <ReportDialog open={report} onOpenChange={setReport} target={{ message_id: turn.messageId }} initial="missing_source" />
        </div>
      ) : (
        <div aria-live={streaming ? 'polite' : 'off'}>
          <div className={cn(streaming && turn.text && 'caret')}>
            {turn.text ? <AnswerText text={turn.text} citations={cites} onCite={onSelect} />
              : streaming && <p className="flex items-center gap-2 text-ink-muted"><Loader2 className="h-4 w-4 animate-spin" aria-hidden />Searching approved sources…</p>}
          </div>
        </div>
      )}

      {turn.state === 'error' && (
        <InlineAlert tone="danger" className="mt-2" title={turn.text ? 'Connection lost. The answer above is incomplete.' : "We couldn't produce an answer."}>
          {turn.error?.message}{turn.error?.ref && <span className="ml-1 text-xs">Reference: <code className="font-mono">{turn.error.ref.slice(0, 8)}…</code></span>}
          <div className="mt-1"><Button size="sm" variant="secondary" onClick={onRegenerate}>Retry</Button></div>
        </InlineAlert>
      )}

      {(turn.warnings ?? []).length > 0 && (
        <ul className="mt-2 space-y-1">{turn.warnings!.map((w, i) => <li key={i} className="flex gap-2 rounded-control bg-warning-bg px-2 py-1 text-xs text-warning"><AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />{w}</li>)}</ul>
      )}

      {turn.rewritten && <details className="mt-2 text-xs text-ink-muted"><summary className="cursor-pointer">How I searched</summary><p className="mt-1">{turn.rewritten}</p></details>}

      {inlineSources && cites.length > 0 && (
        <details className="mt-3"><summary className="cursor-pointer text-sm font-medium">Sources ({cites.length})</summary>
          <ul className="mt-2 space-y-2">{cites.map((c, i) => <SourceCard key={i} c={c} index={i} onOpen={onOpen} />)}</ul></details>
      )}

      {!streaming && <DisclaimerNote text={turn.disclaimer} />}

      {!streaming && turn.state !== 'error' && (
        <footer className="mt-2 flex flex-wrap items-center gap-1">
          {turn.messageId && <RatingButtons target={{ message_id: turn.messageId }} />}
          <Button variant="ghost" size="sm" onClick={() => { void navigator.clipboard.writeText(copyWithFootnotes(turn.text, cites, turn.disclaimer)).then(() => toast.success('Answer copied with its sources and disclaimer.')) }}><Copy className="h-3.5 w-3.5" aria-hidden />Copy</Button>
          {last && <Button variant="ghost" size="sm" onClick={onRegenerate}><RefreshCw className="h-3.5 w-3.5" aria-hidden />Regenerate</Button>}
          {selectedCite !== null && <span className="sr-only">Source {selectedCite + 1} selected</span>}
        </footer>
      )}
    </article>
  )
}

export default function ChatPage() {
  const { conversationId } = useParams()
  const nav = useNavigate()
  const loc = useLocation()
  const { profile } = useAuth()
  const online = useOnline()
  const wide = useMediaQuery('(min-width: 1024px)')
  const [draft, setDraft] = useState(() => { try { return sessionStorage.getItem(`erag.draft.${conversationId ?? 'new'}`) ?? '' } catch { return '' } })
  const [filters, setFilters] = useState<Filters>({})
  const [filterOpen, setFilterOpen] = useState(false)
  const [preview, setPreview] = useState<PreviewTarget | null>(null)
  const [selected, setSelected] = useState<{ turn: string; idx: number } | null>(null)
  const [listOpen, setListOpen] = useState(false)
  const endRef = useRef<HTMLDivElement>(null)
  const composer = useRef<HTMLTextAreaElement>(null)
  const owned = useRef<string | undefined>(undefined) // conversation created by the current stream

  const onConversation = useCallback((id: string) => {
    owned.current = id
    nav(`/chat/${id}`, { replace: true })
  }, [nav])
  const chat = useChatStream(onConversation)
  const { load, setConversation } = chat

  // Load a stored conversation when navigating to it (not when this page just created it).
  const detail = useQuery({
    queryKey: [profile?.tenant_id, 'conversation', conversationId],
    queryFn: () => chatApi.conversation(conversationId!),
    enabled: !!conversationId && owned.current !== conversationId, staleTime: 0, gcTime: 0, retry: false,
  })
  const { setCitations } = chat
  useEffect(() => {
    const d = detail.data
    if (!d) return
    load(turnsFromConversation(d)); setConversation(d.conversation_id)
    // Re-verify the latest answer's sources against the caller's current access (dates, lifecycle, verified flag).
    const last = [...d.messages].reverse().find((m) => m.role !== 'user' && (m.citations?.length ?? 0) > 0)
    if (last) {
      chatApi.sources(d.conversation_id, last.message_id).then((c) => { if (Array.isArray(c) && c.length) setCitations(last.message_id, c) }).catch(() => undefined)
    }
  }, [detail.data, load, setConversation, setCitations])
  useEffect(() => {
    if (!conversationId) { owned.current = undefined; setConversation(undefined); load([]) }
  }, [conversationId, load, setConversation])

  // Prefilled question from Home / Search ("Ask about this").
  const prefill = (loc.state as { ask?: string; filters?: Filters } | null)
  useEffect(() => {
    if (prefill?.ask) { setDraft(prefill.ask); if (prefill.filters) setFilters(prefill.filters); nav(loc.pathname, { replace: true, state: null }) }
  }, [prefill, nav, loc.pathname])

  useEffect(() => { try { sessionStorage.setItem(`erag.draft.${conversationId ?? 'new'}`, draft) } catch { /* optional */ } }, [draft, conversationId])
  const turnCount = chat.turns.length
  const lastLen = chat.turns[turnCount - 1]?.text.length
  useEffect(() => { endRef.current?.scrollIntoView({ block: 'end' }) }, [turnCount, lastLen])

  const lastAssistant = useMemo(() => [...chat.turns].reverse().find((t) => t.role === 'assistant' && t.state !== 'streaming'), [chat.turns])
  const activeTurn = (selected ? chat.turns.find((t) => t.key === selected.turn) : undefined) ?? lastAssistant
  const sources = activeTurn?.citations ?? []

  const submit = useCallback(() => {
    if (!draft.trim() || chat.streaming || !online) return
    const text = draft
    setDraft(''); try { sessionStorage.removeItem(`erag.draft.${conversationId ?? 'new'}`) } catch { /* optional */ }
    void chat.send(text, Object.keys(filters).length ? filters : undefined)
    composer.current?.focus()
  }, [draft, chat, filters, online, conversationId])

  // Esc stops streaming; Alt+1..9 jumps to a citation of the latest answer.
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && chat.streaming) chat.stop()
      if (e.altKey && /^[1-9]$/.test(e.key) && lastAssistant) {
        const i = Number(e.key) - 1
        if (lastAssistant.citations?.[i]) { e.preventDefault(); setSelected({ turn: lastAssistant.key, idx: i }) }
      }
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [chat, lastAssistant])

  const openSource = (c: Citation) => setPreview({ documentId: c.document_id, chunkId: c.chunk_id, page: undefined, title: c.title })
  const selectCite = (turnKey: string, i: number) => {
    setSelected({ turn: turnKey, idx: i })
    if (wide) setTimeout(() => document.getElementById(`source-${i}`)?.focus(), 0)
  }
  const fs = filterSummary(filters)

  return (
    <div className="-m-3 flex h-[calc(100vh-3.5rem)] sm:-m-5">
      {wide && <aside className="w-72 shrink-0 border-r border-line bg-surface" aria-label="Conversations"><ConversationList activeId={conversationId} onNew={() => nav('/chat')} /></aside>}
      <section className="flex min-w-0 flex-1 flex-col" aria-label="Conversation">
        {!wide && (
          <div className="flex items-center justify-between border-b border-line bg-surface px-3 py-2">
            <Button variant="secondary" size="sm" onClick={() => setListOpen(true)}>Conversations</Button>
            <Button size="sm" onClick={() => nav('/chat')}>New</Button>
          </div>
        )}
        <div className="flex-1 overflow-y-auto px-3 py-4 sm:px-6" role="log" aria-label="Messages">
          {conversationId && detail.isFetching && chat.turns.length === 0 && <LoadingBlock rows={5} />}
          {detail.isError && <ErrorState error={detail.error} onRetry={() => void detail.refetch()} />}
          {chat.turns.length === 0 && !detail.isFetching && !detail.isError && (
            <div className="mx-auto mt-10 max-w-xl text-center">
              <h1 className="text-2xl">Ask about approved documents</h1>
              <p className="mt-1 text-ink-muted">Answers are AI-generated from your organisation's approved documents and always show their sources.</p>
              <div className="mt-4 grid gap-2">{EXAMPLES.map((e) => <Button key={e} variant="secondary" className="whitespace-normal text-left" onClick={() => { setDraft(e); composer.current?.focus() }}>{e}</Button>)}</div>
            </div>
          )}
          <div className="space-y-4">
            {chat.turns.map((t, i) => t.role === 'user' ? (
              <div key={t.key} className="flex justify-end"><p className="max-w-[85%] whitespace-pre-wrap rounded-card bg-primary px-3 py-2 text-white">{t.text}</p></div>
            ) : (
              <AnswerCard key={t.key} turn={t} last={i === chat.turns.length - 1} inlineSources={!wide}
                selectedCite={selected?.turn === t.key ? selected.idx : null}
                onSelect={(idx) => selectCite(t.key, idx)} onOpen={openSource} onRegenerate={chat.regenerate}
                onRephrase={() => composer.current?.focus()} />
            ))}
          </div>
          <div ref={endRef} />
        </div>

        <form className="border-t border-line bg-surface p-3" onSubmit={(e) => { e.preventDefault(); submit() }}>
          <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
            <Button type="button" variant="secondary" size="sm" onClick={() => setFilterOpen(true)}><Filter className="h-3.5 w-3.5" aria-hidden />Scope</Button>
            {fs.length ? fs.map((s) => <Badge key={s} tone="info">{s}</Badge>) : <span className="text-ink-muted">All approved documents you can access</span>}
            <span className="ml-auto flex items-center gap-1 text-ink-muted"><ShieldAlert className="h-3 w-3" aria-hidden />Do not enter customer personal data</span>
          </div>
          <div className="flex items-end gap-2">
            <Textarea ref={composer} data-focus-target aria-label="Your question" placeholder="Ask a question…" rows={2} maxLength={MAX} value={draft} className="min-h-[56px] resize-y"
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() } }} />
            {chat.streaming
              ? <Button type="button" variant="secondary" onClick={chat.stop} aria-label="Stop generating"><Square className="h-4 w-4" aria-hidden />Stop</Button>
              : <Button type="submit" disabled={!draft.trim() || !online} aria-label="Send"><Send className="h-4 w-4" aria-hidden />Send</Button>}
          </div>
          <p className="mt-1 text-right text-xs text-ink-muted" aria-live="off">{draft.length}/{MAX}</p>
        </form>
      </section>

      {wide && (
        <aside className="w-[380px] shrink-0 overflow-y-auto border-l border-line bg-canvas p-3" aria-label="Sources">
          <h2 className="mb-2">Sources</h2>
          {sources.length === 0 ? <p className="text-sm text-ink-muted">Sources for the latest answer appear here. Each shows its version and date.</p> : (
            <ul className="space-y-2">{sources.map((c, i) => <SourceCard key={i} id={`source-${i}`} c={c} index={i} selected={selected?.idx === i && selected.turn === activeTurn?.key} onOpen={openSource} />)}</ul>
          )}
          {sources.length > 0 && <p className="mt-2 text-xs text-ink-muted">Generated answer and retrieved evidence are shown separately: verify claims against the sources.</p>}
        </aside>
      )}

      <ScopeFilterDialog open={filterOpen} onOpenChange={setFilterOpen} value={filters} onChange={setFilters} />
      <DocumentPreviewDrawer target={preview} onClose={() => setPreview(null)} />
      {!wide && <Modal open={listOpen} onOpenChange={setListOpen} variant="drawer" title="Conversations"><div className="-m-4 h-[75vh]"><ConversationList activeId={conversationId} onNew={() => { setListOpen(false); nav('/chat') }} /></div></Modal>}
      {env.chatStreaming ? null : <span className="sr-only">Streaming is disabled; answers appear when complete.</span>}
    </div>
  )
}
