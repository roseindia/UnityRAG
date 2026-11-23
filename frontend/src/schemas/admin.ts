import { z } from 'zod'
import { LINES_OF_BUSINESS } from '@/types/api'

export const createUserSchema = z.object({
  email: z.string().trim().min(1, 'Enter an email address.').email('Enter a valid email address.'),
  display_name: z.string().trim().min(1, 'Enter a display name.').max(200),
  user_type: z.enum(['employee', 'broker', 'agent', 'service']),
  department_id: z.string().optional(),
  lines_of_business: z.array(z.enum(LINES_OF_BUSINESS)).default([]),
  jurisdictions: z.string().optional(),
  clearance_rank: z.coerce.number().int().min(0, 'Between 0 and 3.').max(3, 'Between 0 and 3.'),
  roles: z.array(z.string()).default([]),
  auth_provider: z.enum(['local', 'oidc']),
  external_subject: z.string().optional(),
  password: z.string().optional(),
}).superRefine((v, ctx) => {
  if (v.auth_provider === 'local' && !v.password) ctx.addIssue({ code: 'custom', path: ['password'], message: 'Enter an initial password for a local account.' })
  if (v.auth_provider === 'oidc' && !v.external_subject) ctx.addIssue({ code: 'custom', path: ['external_subject'], message: 'Enter the identity provider subject.' })
})
export type CreateUserForm = z.input<typeof createUserSchema>

export const roleSchema = z.object({
  code: z.string().regex(/^[a-z][a-z0-9_]{2,39}$/, 'Lower-case letters, digits and underscores, 3 to 40 characters.'),
  name: z.string().trim().min(1, 'Enter a name.').max(120),
  description: z.string().max(500).optional(),
  permissions: z.array(z.string()).min(1, 'Choose at least one permission.'),
  conflicts_with: z.array(z.string()).default([]),
})
export type RoleForm = z.input<typeof roleSchema>

export const settingsSchema = z.object({
  require_mfa_for_admin: z.boolean(),
  session_idle_minutes: z.coerce.number().int().min(5, 'At least 5.').max(1440, 'At most 1,440.'),
  session_absolute_hours: z.coerce.number().int().min(1, 'At least 1.').max(168, 'At most 168.'),
  store_query_text: z.boolean(),
  conversation_retention_days: z.coerce.number().int().min(1, 'At least 1 day.').max(3650),
  default_language: z.string().min(2).max(10),
})
export type SettingsForm = z.input<typeof settingsSchema>

/** Mirrors the server ranges (Design Document 11.8); the server stays authoritative. */
export const ragSchema = z.object({
  chunking_strategy: z.enum(['fixed', 'recursive', 'structure_aware']),
  chunk_size: z.coerce.number().int().min(64, '64 to 4,000.').max(4000, '64 to 4,000.'),
  chunk_overlap: z.coerce.number().int().min(0),
  vector_top_k: z.coerce.number().int().min(1).max(500),
  fts_top_k: z.coerce.number().int().min(1).max(500),
  exact_top_k: z.coerce.number().int().min(0).max(500),
  vector_weight: z.coerce.number().min(0).max(10),
  fts_weight: z.coerce.number().min(0).max(10),
  exact_weight: z.coerce.number().min(0).max(10),
  rrf_k: z.coerce.number().int().min(1, '1 to 1,000.').max(1000, '1 to 1,000.'),
  rerank_enabled: z.boolean(),
  rerank_top_n: z.coerce.number().int().min(1).max(200),
  final_top_k: z.coerce.number().int().min(1).max(100),
  max_context_tokens: z.coerce.number().int().min(256).max(200000),
  min_relevance: z.coerce.number().min(0).max(1),
  hnsw_ef_search: z.coerce.number().int().min(10, '10 to 1,000.').max(1000, '10 to 1,000.'),
  citation_required: z.boolean(),
  query_rewriting: z.boolean(),
  reason: z.string().trim().min(5, 'Give a reason for the change (at least 5 characters).'),
}).refine((v) => v.chunk_overlap < v.chunk_size, { path: ['chunk_overlap'], message: 'Overlap must be smaller than the chunk size.' })
export type RagForm = z.input<typeof ragSchema>

export const aiSchema = z.object({
  llm_provider: z.string().min(1), chat_model: z.string().min(1),
  embedding_provider: z.string().min(1), embedding_model: z.string().min(1), embedding_dimensions: z.coerce.number().int().min(1),
  reranker_provider: z.string().optional(), reranker_model: z.string().optional(), rewrite_model: z.string().optional(),
  temperature: z.coerce.number().min(0, '0 to 2.').max(2, '0 to 2.'),
  max_output_tokens: z.coerce.number().int().min(16).max(32000),
  distance_metric: z.enum(['cosine', 'inner_product', 'l2']),
  reason: z.string().trim().min(5, 'Give a reason for the change (at least 5 characters).'),
})
export type AiForm = z.input<typeof aiSchema>
