import { describe, expect, it } from 'vitest'
import { createSseParser } from '@/services/api/sse'
import { ApiError, errorFromResponse, fieldErrors, userMessage } from '@/services/api/errors'
import { safeReturnTo, homeFor } from '@/utils/returnTo'
import { buildPermissionApi } from '@/hooks/usePermissions'
import { formatBytes, formatDateOnly, humanize, formatCompact } from '@/utils/format'
import { sanitizeHighlight } from '@/components/common/SafeHighlight'
import { relevanceDots } from '@/features/search/SearchPage'
import { parseCsv } from '@/features/tenant-admin/EvaluationPages'
import { copyWithFootnotes } from '@/features/chat/copyAnswer'
import { pollDelay } from '@/features/ingestion/JobTracker'
import { metadataSchema, validateFile } from '@/schemas/documents'
import { ragSchema, createUserSchema } from '@/schemas/admin'
import type { Profile } from '@/types/api'

describe('SSE parser', () => {
  it('parses meta, token, final and done events, including chunks split mid-event', () => {
    const seen: { event: string; data: string }[] = []
    const feed = createSseParser((e) => seen.push(e))
    feed('event: meta\ndata: {"conversation_id":"c1"}\n\nevent: tok')
    feed('en\ndata: {"text":"Hello "}\n\n')
    feed('event: final\r\ndata: {"answer":"x"}\r\n\r\nevent: done\ndata: {}\n\n')
    expect(seen.map((e) => e.event)).toEqual(['meta', 'token', 'final', 'done'])
    expect(JSON.parse(seen[1].data)).toEqual({ text: 'Hello ' })
  })
  it('ignores comments and joins multi-line data', () => {
    const seen: { event: string; data: string }[] = []
    createSseParser((e) => seen.push(e))(': keepalive\n\nevent: token\ndata: a\ndata: b\n\n')
    expect(seen).toEqual([{ event: 'token', data: 'a\nb' }])
  })
})

describe('error mapping', () => {
  it('builds an ApiError from the backend envelope and shows a catalogue message', () => {
    const e = errorFromResponse(429, { error: { code: 'rate_limited', message: 'Rate limit exceeded (20 requests per minute)', correlation_id: 'abc', details: [] } }, { 'retry-after': '60' })
    expect(e).toBeInstanceOf(ApiError)
    expect(e.code).toBe('rate_limited')
    expect(e.message).toBe('Too many requests. Please wait a moment.')
    expect(e.retryAfter).toBe(60)
    expect(e.correlationId).toBe('abc')
  })
  it('never exposes unknown server text; falls back to a generic message', () => {
    const e = errorFromResponse(500, { error: { code: 'weird_code', message: 'psycopg2.errors.UndefinedTable: relation x', correlation_id: 'r1' } })
    expect(e.message).not.toMatch(/psycopg2|relation/)
    expect(userMessage('weird_code')).toBe('Something went wrong. Please try again.')
  })
  it('maps validation details onto form fields', () => {
    const e = errorFromResponse(422, { error: { code: 'validation_failed', message: 'x', correlation_id: 'c', details: [{ field: 'body.chunk_size', message: 'must be 64-4000' }] } })
    expect(fieldErrors(e)).toMatchObject({ 'body.chunk_size': 'must be 64-4000', chunk_size: 'must be 64-4000' })
  })
  it('handles a body without an envelope (404 / 502)', () => {
    expect(errorFromResponse(404, undefined).code).toBe('not_found')
    expect(errorFromResponse(502, '<html>').code).toBe('internal_error')
  })
})

describe('returnTo validation (open redirect protection)', () => {
  it.each(['//evil.com', 'https://evil.com', '/\\evil.com', 'javascript:alert(1)', '/unknown/page', ''])('rejects %s', (x) => expect(safeReturnTo(x)).toBe('/'))
  it.each(['/chat/abc', '/admin/users?tab=roles', '/documents/1', '/platform/tenants'])('accepts %s', (x) => expect(safeReturnTo(x)).toBe(x))
  it('picks a console home', () => {
    expect(homeFor('platform_admin')).toBe('/platform')
    expect(homeFor('tenant_admin')).toBe('/admin')
    expect(homeFor('user')).toBe('/')
  })
})

const profile = (o: Partial<Profile>): Profile => ({ account_id: 'a', email: 'e', display_name: 'n', tenant_id: 't', user_id: 'u', user_type: 'employee', department_id: 'd', platform_role: '', roles: [], permissions: [], platform_permissions: [], lines_of_business: [], jurisdictions: [], clearance_rank: 0, mfa_verified: false, console: 'user', ...o })

describe('permission helpers (visibility derives from permission lists, never role codes)', () => {
  it('a member sees workspace but not admin or platform', () => {
    const p = buildPermissionApi(profile({ roles: ['tenant_admin'], permissions: ['chat.use', 'search.use'] }))
    expect(p.can('chat.use')).toBe(true)
    expect(p.hasAdminAccess).toBe(false) // role code is ignored
    expect(p.hasPlatformAccess).toBe(false)
  })
  it('any admin permission unlocks the admin tree; evaluation and feedback count', () => {
    expect(buildPermissionApi(profile({ permissions: ['admin.users.manage'] })).hasAdminAccess).toBe(true)
    expect(buildPermissionApi(profile({ permissions: ['feedback.review'] })).hasAdminAccess).toBe(true)
    expect(buildPermissionApi(profile({ permissions: ['evaluation.run'] })).hasAdminAccess).toBe(true)
  })
  it('platform access needs a platform role and permissions', () => {
    expect(buildPermissionApi(profile({ platform_role: 'platform_admin', platform_permissions: ['platform.tenants.view'] })).hasPlatformAccess).toBe(true)
    expect(buildPermissionApi(profile({ platform_role: 'platform_admin', platform_permissions: [] })).hasPlatformAccess).toBe(false)
    expect(buildPermissionApi(null).can('chat.use')).toBe(false)
  })
})

describe('formatting', () => {
  it('formats bytes in base 1024 with units', () => { expect(formatBytes(0)).toBe('0 B'); expect(formatBytes(1536)).toBe('1.5 KB'); expect(formatBytes(5 * 1024 ** 3)).toBe('5.0 GB'); expect(formatBytes(null)).toBe('–') })
  it('shows effective dates without time-zone conversion', () => { expect(formatDateOnly('2026-01-01')).toBe('01 Jan 2026'); expect(formatDateOnly(null)).toBe('–') })
  it('humanizes codes and compacts token counts', () => { expect(humanize('policy_wording')).toBe('Policy wording'); expect(formatCompact(41_200_000)).toBe('41.2M') })
})

describe('sanitising', () => {
  it('keeps <mark> only and removes scripts, handlers and other tags', () => {
    const out = sanitizeHighlight('a <mark>flood</mark> <script>alert(1)</script><img src=x onerror=alert(1)><b onclick="x()">bold</b>')
    expect(out).toContain('<mark>flood</mark>')
    expect(out).not.toMatch(/script|onerror|onclick|<img|<b/)
  })
})

describe('search and evaluation helpers', () => {
  it('derives 1–5 relevance dots from the score relative to the best', () => {
    expect(relevanceDots(0.9, 0.9)).toBe(5)
    expect(relevanceDots(0.45, 0.9)).toBe(3)
    expect(relevanceDots(0.01, 0.9)).toBe(1)
    expect(relevanceDots(0, 0)).toBe(0)
  })
  it('parses CSV with quoted commas and escaped quotes', () => {
    expect(parseCsv('question,category\n"Is flood, storm covered?",motor\n"He said ""no""",home\n')).toEqual([['question', 'category'], ['Is flood, storm covered?', 'motor'], ['He said "no"', 'home']])
  })
})

describe('ingestion polling backoff (Design Document 6.6)', () => {
  it('polls at 2 s, then 4 s, then 8 s, capped at 15 s', () => {
    expect([1, 2, 3, 4, 5, 6, 7, 20].map(pollDelay)).toEqual([2000, 2000, 4000, 4000, 8000, 8000, 15000, 15000])
    expect(pollDelay(0)).toBe(2000)
  })
})

describe('copy with footnotes', () => {
  it('appends citations and the disclaimer to the copied answer (NFR-096)', () => {
    const t = copyWithFootnotes('Covered. [S1]', [{ marker: 'S1', document_id: 'd', title: 'Policy', version_label: '2026.1', section_path: 'Sec 2', page_from: 3 }], 'AI-generated.')
    expect(t).toContain('[S1] Policy (v2026.1, Sec 2, p. 3)')
    expect(t).toContain('AI-generated.')
  })
})

describe('validation schemas', () => {
  const ok = { collection_id: 'c', document_type: 'policy_wording', classification: 'internal', insurance_line: 'motor', jurisdictions: 'UK, IE', effective_from: '2026-01-01', effective_to: '2026-12-31' }
  it('accepts valid upload metadata', () => expect(metadataSchema.safeParse(ok).success).toBe(true))
  it('rejects an end date before the start date', () => {
    const r = metadataSchema.safeParse({ ...ok, effective_to: '2025-12-31' })
    expect(r.success).toBe(false)
    expect(r.success ? '' : r.error.issues[0].path.join('.')).toBe('effective_to')
  })
  it('rejects jurisdiction codes outside 2–10 characters', () => expect(metadataSchema.safeParse({ ...ok, jurisdictions: 'U' }).success).toBe(false))
  it('validates file types and empty files', () => {
    expect(validateFile(new File(['x'], 'a.exe'))).toMatch(/not supported/)
    expect(validateFile(new File([], 'a.pdf'))).toMatch(/empty/)
    expect(validateFile(new File(['x'], 'a.PDF'))).toBeNull()
  })
  it('mirrors server ranges for RAG config and requires a reason', () => {
    const base = { chunking_strategy: 'recursive', chunk_size: 800, chunk_overlap: 100, vector_top_k: 40, fts_top_k: 40, exact_top_k: 10, vector_weight: 1, fts_weight: 1, exact_weight: 1, rrf_k: 60, rerank_enabled: true, rerank_top_n: 20, final_top_k: 8, max_context_tokens: 6000, min_relevance: 0.2, hnsw_ef_search: 80, citation_required: true, query_rewriting: true, reason: 'tune recall' }
    expect(ragSchema.safeParse(base).success).toBe(true)
    expect(ragSchema.safeParse({ ...base, chunk_overlap: 900 }).success).toBe(false)
    expect(ragSchema.safeParse({ ...base, rrf_k: 5000 }).success).toBe(false)
    expect(ragSchema.safeParse({ ...base, hnsw_ef_search: 5 }).success).toBe(false)
    expect(ragSchema.safeParse({ ...base, reason: '' }).success).toBe(false)
  })
  it('requires a password for local users and a subject for SSO users', () => {
    const base = { email: 'a@b.co', display_name: 'A', user_type: 'employee', clearance_rank: 0 }
    expect(createUserSchema.safeParse({ ...base, auth_provider: 'local' }).success).toBe(false)
    expect(createUserSchema.safeParse({ ...base, auth_provider: 'local', password: 'x' }).success).toBe(true)
    expect(createUserSchema.safeParse({ ...base, auth_provider: 'oidc' }).success).toBe(false)
    expect(createUserSchema.safeParse({ ...base, auth_provider: 'oidc', external_subject: 'sub' }).success).toBe(true)
  })
})
