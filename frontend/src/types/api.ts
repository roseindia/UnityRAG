// Typed contracts for the backend /api/v1, transcribed from docs/api/openapi.json.
// Response bodies the OpenAPI document leaves as `object` are typed from the backend services.

export interface Page<T> { items: T[]; total: number; limit: number; offset: number }
export interface Message { message: string }

export interface Membership {
  tenant_id: string; tenant_code: string; tenant_name: string
  tenant_status: string; membership_status: string; is_default: boolean
}
export interface TokenResponse {
  access_token: string; refresh_token: string; token_type?: string; expires_at: string
  session_id: string; tenant_id: string; platform_role: string; memberships: Membership[]
}
export type ConsoleKind = 'user' | 'department_admin' | 'tenant_admin' | 'platform_admin'
export interface Profile {
  account_id: string; email: string; display_name: string; tenant_id: string; user_id: string
  user_type: string; department_id: string; platform_role: string; roles: string[]
  permissions: string[]; platform_permissions: string[]; lines_of_business: string[]
  jurisdictions: string[]; clearance_rank: number; mfa_verified: boolean; console: ConsoleKind | string
}
export interface LoginRequest { email: string; password: string; tenant_id?: string; mfa_code?: string }

export interface Filters {
  collection_ids?: string[]; document_types?: string[]; lines_of_business?: string[]
  jurisdictions?: string[]; products?: string[]; document_ids?: string[]
  as_of?: string; include_superseded?: boolean
}

export interface Citation {
  marker?: string; ordinal?: number; chunk_id?: string; document_id: string; version_id?: string
  title: string; version_label?: string | null; section_path?: string | null; clause_ref?: string | null
  page_from?: number | null; page_to?: number | null; effective_from?: string | null; effective_to?: string | null
  lifecycle_state?: string; score?: number; verified?: boolean; quote_hash?: string
}
export type AnswerStatus = 'answered' | 'abstained' | 'blocked' | 'needs_review' | string
export type EvidenceStrength = 'high' | 'medium' | 'low' | 'none' | string
export interface ChatAnswer {
  conversation_id: string; message_id: string; answer: string; status: AnswerStatus
  evidence_strength: EvidenceStrength; warnings: string[]; ai_generated: boolean
  citations: Citation[]; usage?: { model?: string; input_tokens?: number; output_tokens?: number }
  latency_ms?: number; disclaimer: string; rewritten_query?: string | null
}
export interface ConversationSummary { conversation_id: string; title: string; message_count: number; created_at: string; updated_at: string }
export interface ConversationMessage {
  message_id: string; seq: number; role: 'user' | 'assistant' | string; content: string
  answer_status?: AnswerStatus | null; evidence_strength?: EvidenceStrength | null
  rewritten_query?: string | null; warnings?: string[] | null; created_at: string; citations?: Citation[]
}
export interface ConversationDetail extends ConversationSummary {
  context?: Record<string, unknown>; status?: string; legal_hold?: boolean; messages: ConversationMessage[]
}

export interface SearchResult {
  chunk_id: string; document_id: string; version_id: string; title: string
  section_path?: string | null; clause_ref?: string | null; page_from?: number | null; page_to?: number | null
  content: string; highlight?: string | null; document_type: string; line_of_business?: string | null
  jurisdictions: string[]; effective_from?: string | null; effective_to?: string | null
  lifecycle_state: string; version_label?: string | null; low_confidence?: boolean
  score: number; rrf_score?: number; rerank_score?: number | null
  explanation?: { matched_branches: string[]; branch_ranks: Record<string, number>; branch_scores: Record<string, number>; rrf_score: number; rerank_score: number | null }
}
export interface SearchResponse {
  search_id: string; mode: string; query: string; results: SearchResult[]; latency_ms: number
  cache_hit: boolean; diagnostics?: Record<string, unknown>; filters_applied?: Filters
}
export interface FacetValue { value: string; label: string; count: number }
export type Facets = Record<string, FacetValue[]>
export interface SearchHistoryItem {
  search_id: string; mode: string; query_text?: string | null; result_count: number
  latency_ms: number; cache_hit?: boolean; created_at: string
}

export interface DocumentRow {
  document_id: string; collection_id: string; title: string; document_type: string
  insurance_line?: string | null; product?: string | null; jurisdictions?: string[]; language?: string
  classification: string; lifecycle_state: string; owner_user_id?: string | null
  current_version_id?: string | null; legal_hold?: boolean; size_bytes?: number; mime_type?: string
  effective_from?: string | null; effective_to?: string | null; review_due_at?: string | null
  created_at: string; updated_at: string
  versions?: DocumentVersion[]
}
export interface DocumentVersion {
  version_id: string; version_seq: number; version_label?: string | null; original_filename?: string
  state: string; size_bytes?: number; mime_type?: string; page_count?: number | null; created_at?: string
  checksum_sha256?: string
}
export interface UploadResult { document_id: string; version_id: string; job_id: string; version_seq?: number; checksum_sha256?: string }
export interface IngestionLog { stage: string; level: string; message: string; detail?: unknown; created_at: string }
export interface IngestionJob {
  job_id: string; document_id: string; version_id: string; job_type: string; status: string; stage?: string | null
  attempt: number; max_attempts: number; priority?: number; error_code?: string | null; error_message?: string | null
  stats?: Record<string, unknown> | null; queued_at?: string; started_at?: string | null; finished_at?: string | null
  next_retry_at?: string | null; correlation_id?: string; logs?: IngestionLog[]
}
export interface DocumentPreview {
  document_id: string; title: string; version_id: string; page_number: number; page_label?: string | null
  text: string; extraction?: string | null; ocr_confidence?: number | null; low_confidence?: boolean; pages_total: number
  /** Offsets of the cited passage inside `text` (server-located on the masked page); null when not on this page. */
  highlight?: { start: number; end: number } | null
}

export interface Collection {
  collection_id: string; code: string; name: string; description?: string | null
  line_of_business?: string | null; jurisdictions?: string[]; classification?: string
  status?: string; document_count?: number; retention_days?: number | null; auto_publish?: boolean
  owner_user_id?: string | null; department_id?: string | null; can_write?: boolean
}

export interface QuotaSnapshot { metric: string; used: number; limit: number; pct: number }
export interface SeriesPoint { usage_date: string; [k: string]: number | string | null }
export interface DateRange { start: string; end: string }
export type Dict = Record<string, unknown>
export type Row = Record<string, unknown>

export const DOCUMENT_TYPES = ['policy_wording','policy_schedule','endorsement','claims_manual','underwriting_guideline','product_brochure','regulatory_circular','sop','customer_communication','authority_matrix','faq','other'] as const
export const LINES_OF_BUSINESS = ['motor','home','health','life','travel','marine','liability','property','cyber','workers_comp','group','general'] as const
export const CLASSIFICATIONS = ['public','internal','confidential','restricted'] as const
export const LIFECYCLE_STATES = ['draft','processing','in_review','approved','published','archived','withdrawn','expired'] as const
