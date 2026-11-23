import { useCallback, useEffect, useReducer, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { env } from '@/config/env'
import { chatApi } from '@/services/api/chatApi'
import { ApiError } from '@/services/api/errors'
import type { ChatAnswer, Citation, ConversationDetail, Filters } from '@/types/api'

export interface Turn {
  key: string
  role: 'user' | 'assistant'
  text: string
  state: 'streaming' | 'done' | 'stopped' | 'error'
  messageId?: string
  status?: string
  evidence?: string
  warnings?: string[]
  citations?: Citation[]
  disclaimer?: string
  rewritten?: string | null
  error?: { message: string; ref?: string }
  /** Text shown before the authoritative final event arrived. */
  incomplete?: boolean
}

type Action =
  | { t: 'reset'; turns: Turn[] }
  | { t: 'push'; turns: Turn[] }
  | { t: 'token'; key: string; text: string }
  | { t: 'final'; key: string; a: ChatAnswer }
  | { t: 'fail'; key: string; error: { message: string; ref?: string } }
  | { t: 'stop'; key: string }
  | { t: 'cites'; key: string; citations: Citation[] }

function reducer(s: Turn[], a: Action): Turn[] {
  switch (a.t) {
    case 'cites': return s.map((x) => (x.key === a.key ? { ...x, citations: a.citations } : x))
    case 'reset': return a.turns
    case 'push': return [...s, ...a.turns]
    case 'token': return s.map((x) => (x.key === a.key ? { ...x, text: x.text + a.text } : x))
    case 'final': return s.map((x) => (x.key === a.key ? {
      ...x, state: 'done', incomplete: false,
      // The final answer replaces streamed text: it is the authoritative, guard-railed version.
      text: a.a.answer, messageId: a.a.message_id, status: a.a.status, evidence: a.a.evidence_strength,
      warnings: a.a.warnings ?? [], citations: a.a.citations ?? [], disclaimer: a.a.disclaimer, rewritten: a.a.rewritten_query,
    } : x))
    case 'fail': return s.map((x) => (x.key === a.key ? { ...x, state: 'error', error: a.error, incomplete: x.text.length > 0 } : x))
    case 'stop': return s.map((x) => (x.key === a.key ? { ...x, state: 'stopped', incomplete: true } : x))
  }
}

export function turnsFromConversation(c: ConversationDetail): Turn[] {
  return c.messages.map((m) => ({
    key: m.message_id, role: m.role === 'user' ? 'user' : 'assistant', text: m.content, state: 'done', messageId: m.message_id,
    status: m.answer_status ?? undefined, evidence: m.evidence_strength ?? undefined, warnings: m.warnings ?? [],
    citations: m.citations ?? [], rewritten: m.rewritten_query,
  }))
}

let seq = 0
const nextKey = () => `t${++seq}`

/** Chat state machine (Design Document 10.4): idle → streaming → done | stopped | error. */
export function useChatStream(onConversation: (id: string) => void) {
  const [turns, dispatch] = useReducer(reducer, [])
  const abort = useRef<AbortController | null>(null)
  const conv = useRef<string | undefined>(undefined)
  const lastUser = useRef<{ text: string; filters?: Filters } | null>(null)
  const qc = useQueryClient()
  const streaming = turns.some((t) => t.state === 'streaming')

  useEffect(() => () => abort.current?.abort(), [])

  const setConversation = useCallback((id: string | undefined) => { conv.current = id }, [])

  const send = useCallback(async (text: string, filters?: Filters) => {
    const message = text.trim()
    if (!message) return
    lastUser.current = { text: message, filters }
    const aKey = nextKey()
    dispatch({ t: 'push', turns: [
      { key: nextKey(), role: 'user', text: message, state: 'done' },
      { key: aKey, role: 'assistant', text: '', state: 'streaming' },
    ] })
    const ctl = new AbortController()
    abort.current = ctl
    const fail = (e: unknown) => {
      if (e instanceof ApiError && e.code === 'aborted') return
      const api = e instanceof ApiError ? e : null
      dispatch({ t: 'fail', key: aKey, error: { message: api?.message ?? 'Something went wrong. Please try again.', ref: api?.correlationId } })
    }
    try {
      if (!env.chatStreaming) {
        const a = await chatApi.ask(message, conv.current, filters)
        conv.current = a.conversation_id; onConversation(a.conversation_id)
        dispatch({ t: 'final', key: aKey, a })
      } else {
        let finished = false
        await chatApi.stream(message, conv.current, filters, ctl.signal, {
          onMeta: (m) => { conv.current = m.conversation_id; onConversation(m.conversation_id) },
          onToken: (tx) => dispatch({ t: 'token', key: aKey, text: tx }),
          onFinal: (a) => { finished = true; dispatch({ t: 'final', key: aKey, a }) },
          onError: (e) => { finished = true; dispatch({ t: 'fail', key: aKey, error: { message: e.code === 'rate_limited' ? 'Too many requests. Please wait a moment.' : 'Something went wrong on our side. Please try again.', ref: e.correlation_id } }) },
        })
        if (!finished && !ctl.signal.aborted) fail(new ApiError({ status: 0, code: 'network_error' }))
      }
      void qc.invalidateQueries({ queryKey: ['conversations'] })
    } catch (e) { fail(e) }
  }, [onConversation, qc])

  const stop = useCallback(() => {
    abort.current?.abort()
    const last = [...turns].reverse().find((t) => t.state === 'streaming')
    if (last) dispatch({ t: 'stop', key: last.key })
    void qc.invalidateQueries({ queryKey: ['conversations'] })
  }, [turns, qc])

  /** There is no regenerate endpoint: resend the last user message in the same conversation. */
  const regenerate = useCallback(() => { if (lastUser.current) void send(lastUser.current.text, lastUser.current.filters) }, [send])

  // Stable identity: ChatPage uses it in effect dependencies; a new function per render caused an endless reset loop.
  const load = useCallback((t: Turn[]) => dispatch({ t: 'reset', turns: t }), [])

  const setCitations = useCallback((key: string, citations: Citation[]) => dispatch({ t: 'cites', key, citations }), [])

  return { turns, streaming, send, stop, regenerate, setConversation, load, setCitations }
}
