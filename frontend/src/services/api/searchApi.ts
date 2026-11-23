import { get, post, clean } from './apiClient'
import type { Facets, Filters, Page, SearchHistoryItem, SearchResponse } from '@/types/api'

export type SearchMode = 'hybrid' | 'vector' | 'fulltext'

// The backend owns embedding, FTS, pgvector, RRF, reranking, ACL and tenant isolation.
export const searchApi = {
  search: (query: string, mode: SearchMode, filters: Filters | undefined, top_k = 10, rerank = true, signal?: AbortSignal) =>
    post<SearchResponse>('/search', { query, mode, filters, top_k, rerank }, { signal }),
  facets: (signal?: AbortSignal) => get<Facets>('/search/facets', undefined, { signal }),
  history: (p: { limit?: number; offset?: number }) => get<Page<SearchHistoryItem>>('/search/history', clean(p)),
}
