import { del, downloadBlob, get, post, put, clean } from './apiClient'
import { postStream } from './sse'
import type { ChatAnswer, Citation, ConversationDetail, ConversationSummary, Filters, Message, Page, Row } from '@/types/api'

export interface FeedbackBody {
  message_id?: string; search_id?: string; rating?: -1 | 1
  category?: 'rating' | 'incorrect' | 'outdated' | 'unsafe' | 'missing_source' | 'wrong_version' | 'access' | 'document_error' | 'other'
  comment?: string
}
export interface StreamHandlers {
  onMeta: (m: { conversation_id: string; correlation_id: string; disclaimer: string }) => void
  onToken: (text: string) => void
  onFinal: (a: ChatAnswer) => void
  onError: (e: { code: string; message: string; correlation_id?: string }) => void
}

export const chatApi = {
  ask: (message: string, conversation_id?: string, filters?: Filters) =>
    post<ChatAnswer>('/chat', { message, conversation_id, filters, stream: false }, { timeout: 120_000 }),
  /** Streaming chat over SSE: meta, token*, final, done, or error (Design Document 6.5). */
  stream: (message: string, conversation_id: string | undefined, filters: Filters | undefined, signal: AbortSignal, h: StreamHandlers) =>
    postStream({
      path: '/chat/stream', body: { message, conversation_id, filters, stream: true }, signal,
      onEvent: ({ event, data }) => {
        let payload: unknown = {}
        try { payload = data ? JSON.parse(data) : {} } catch { return }
        if (event === 'meta') h.onMeta(payload as Parameters<StreamHandlers['onMeta']>[0])
        else if (event === 'token') h.onToken((payload as { text?: string }).text ?? '')
        else if (event === 'final') h.onFinal(payload as ChatAnswer)
        else if (event === 'error') h.onError(payload as Parameters<StreamHandlers['onError']>[0])
      },
    }),
  feedback: (b: FeedbackBody) => post<Row>('/feedback', b),
  conversations: (p: { q?: string; limit?: number; offset?: number }, signal?: AbortSignal) =>
    get<Page<ConversationSummary>>('/conversations', clean(p), { signal }),
  conversation: (id: string) => get<ConversationDetail>(`/conversations/${id}`),
  createConversation: (title?: string) => post<ConversationSummary>('/conversations', { title }),
  rename: (id: string, title: string) => put<ConversationSummary>(`/conversations/${id}`, { title }),
  remove: (id: string) => del<Message>(`/conversations/${id}`),
  exportConversation: (id: string) => downloadBlob(`/conversations/${id}/export`, undefined, `conversation-${id}.json`),
  sources: (cid: string, mid: string) => get<Citation[]>(`/conversations/${cid}/messages/${mid}/sources`),
}
