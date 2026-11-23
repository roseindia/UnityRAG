// DEVELOPMENT ONLY. Enabled with VITE_ENABLE_MOCK_API=true under `npm run dev`; excluded from production builds.
// All data here is clearly sample data. Endpoints that are not mocked answer 404 so gaps stay visible.
import type { AxiosAdapter, AxiosResponse, InternalAxiosRequestConfig } from 'axios'
import { apiClient } from '@/services/api/apiClient'

const now = () => new Date().toISOString()
const day = (i: number) => new Date(Date.now() - i * 86_400_000).toISOString().slice(0, 10)
const MEMBER_PERMS = ['search.use', 'chat.use', 'documents.read', 'collections.read', 'documents.download', 'feedback.submit', 'documents.upload']
const ADMIN_PERMS = [...MEMBER_PERMS, 'admin.dashboard.view', 'admin.users.manage', 'admin.roles.manage', 'admin.collections.manage', 'admin.documents.manage', 'admin.ingestion.manage', 'admin.analytics.view', 'admin.usage.view', 'admin.audit.view', 'admin.settings.manage', 'admin.ai_config.manage', 'admin.rag_config.manage', 'feedback.review', 'evaluation.manage', 'evaluation.run', 'admin.reports.export', 'admin.departments.manage', 'admin.groups.manage']
const PLATFORM_PERMS = ['platform.dashboard.view', 'platform.tenants.view', 'platform.tenants.manage', 'platform.plans.manage', 'platform.quotas.manage', 'platform.ai.manage', 'platform.users.manage', 'platform.monitoring.view', 'platform.security.view', 'platform.audit.view', 'platform.settings.manage', 'platform.break_glass.use']

type Persona = 'member' | 'admin' | 'platform'
let persona: Persona = 'member'
const profile = () => ({
  account_id: 'a-1', email: `${persona}@sample.invalid`, display_name: persona === 'platform' ? 'Sample Platform Operator' : persona === 'admin' ? 'Sample Tenant Admin' : 'Sample Claims Adjuster',
  tenant_id: persona === 'platform' ? '' : 't-1', user_id: 'u-1', user_type: 'employee', department_id: 'd-1', platform_role: persona === 'platform' ? 'platform_super_admin' : '',
  roles: [persona === 'admin' ? 'tenant_admin' : 'member'], permissions: persona === 'platform' ? [] : persona === 'admin' ? ADMIN_PERMS : MEMBER_PERMS, platform_permissions: persona === 'platform' ? PLATFORM_PERMS : [],
  lines_of_business: ['motor', 'home'], jurisdictions: ['UK'], clearance_rank: 1, mfa_verified: false,
  console: persona === 'platform' ? 'platform_admin' : persona === 'admin' ? 'tenant_admin' : 'user',
})
const tokens = () => ({ access_token: 'sample-access', refresh_token: 'sample-refresh', token_type: 'bearer', expires_at: new Date(Date.now() + 600_000).toISOString(), session_id: 's-1', tenant_id: 't-1', platform_role: persona === 'platform' ? 'platform_super_admin' : '',
  memberships: [{ tenant_id: 't-1', tenant_code: 'abc-motor', tenant_name: 'ABC Motor Insurance (sample)', tenant_status: 'active', membership_status: 'active', is_default: true }] })

const doc = (i: number) => ({ document_id: `doc-${i}`, collection_id: 'c-1', title: ['ABC Motor Comprehensive Policy Wording', 'Home Buildings Endorsement 2026', 'Property Claims Manual', 'Underwriting Referral Guide'][i % 4] + ' (sample)', document_type: ['policy_wording', 'endorsement', 'claims_manual', 'underwriting_guideline'][i % 4],
  insurance_line: ['motor', 'home', 'property', 'motor'][i % 4], classification: 'internal', lifecycle_state: 'published', size_bytes: 120_000 * (i + 1), updated_at: now(), created_at: now(), jurisdictions: ['UK'], current_version_id: 'v-1', legal_hold: false })
const series = Array.from({ length: 30 }, (_, i) => ({ usage_date: day(29 - i), searches: 40 + ((i * 7) % 25), chats: 20 + ((i * 5) % 15), active_users: 8 + (i % 6), tokens: 20000 + i * 900, estimated_cost: 1.2 + i * 0.05 }))

const CITES = [
  { marker: 'S1', document_id: 'doc-0', version_id: 'v-1', chunk_id: 'ch-1', title: 'ABC Motor Comprehensive Policy Wording (sample)', version_label: '2026.1', section_path: 'Section 2 > What is covered', clause_ref: '2.1', page_from: 1, page_to: 1, effective_from: '2026-01-01', effective_to: '2026-12-31', lifecycle_state: 'published', score: 0.87, verified: true },
]
const ANSWER = 'Based on the approved sources: the policy covers accidental loss of or damage to your vehicle, including damage caused by fire, theft and flood. [S1] Check the excess that applies to your policy schedule.'

function route(cfg: InternalAxiosRequestConfig): { status: number; data: unknown } {
  const url = (cfg.url ?? '').replace(cfg.baseURL ?? '', '')
  const method = (cfg.method ?? 'get').toLowerCase()
  const body = typeof cfg.data === 'string' && cfg.data ? JSON.parse(cfg.data) : {}
  const is = (m: string, re: RegExp) => method === m && re.test(url)
  if (is('post', /^\/auth\/login/)) { const e = String(body.email ?? ''); persona = e.startsWith('platform') ? 'platform' : e.startsWith('admin') ? 'admin' : 'member'; return { status: 200, data: tokens() } }
  if (is('post', /^\/auth\/refresh/)) return { status: 200, data: tokens() }
  if (is('post', /^\/auth\/logout/)) return { status: 200, data: { message: 'Logged out' } }
  if (is('get', /^\/auth\/me/)) return { status: 200, data: profile() }
  if (is('get', /^\/auth\/sessions/)) return { status: 200, data: [{ session_id: 's-1', user_agent: 'Sample browser', ip_address: '127.0.0.1', created_at: now(), last_seen_at: now() }] }
  if (is('get', /^\/collections/)) return { status: 200, data: [{ collection_id: 'c-1', code: 'motor', name: 'Motor policies (sample)', can_write: true }, { collection_id: 'c-2', code: 'claims', name: 'Claims manuals (sample)', can_write: false }] }
  if (is('get', /^\/documents\/[^/]+\/preview/)) return { status: 200, data: { document_id: 'doc-0', title: 'ABC Motor Comprehensive Policy Wording (sample)', version_id: 'v-1', page_number: 1, page_label: '1', pages_total: 3, text: 'Section 2 – What is covered\n2.1 We will pay for accidental loss of or damage to your vehicle, including damage caused by fire, theft and flood.\nContact: [EMAIL REDACTED]', low_confidence: false } }
  if (is('get', /^\/documents\/[^/?]+$/)) return { status: 200, data: { ...doc(0), versions: [{ version_id: 'v-1', version_seq: 1, version_label: '2026.1', original_filename: 'policy.pdf', state: 'published', page_count: 3, size_bytes: 120000, created_at: now() }] } }
  if (is('get', /^\/documents/)) return { status: 200, data: { items: Array.from({ length: 4 }, (_, i) => doc(i)), total: 4, limit: 50, offset: 0 } }
  if (is('get', /^\/ingestion\/jobs\//)) return { status: 200, data: { job_id: 'j-1', document_id: 'doc-0', version_id: 'v-1', job_type: 'ingest', status: 'running', stage: 'embed', attempt: 1, max_attempts: 5, queued_at: now() } }
  if (is('get', /^\/search\/facets/)) return { status: 200, data: { collection: [{ value: 'c-1', label: 'Motor policies (sample)', count: 3 }], document_type: [{ value: 'policy_wording', label: 'policy_wording', count: 2 }], line_of_business: [{ value: 'motor', label: 'motor', count: 3 }, { value: 'home', label: 'home', count: 1 }] } }
  if (is('get', /^\/search\/history/)) return { status: 200, data: { items: [{ search_id: 'sr-1', mode: 'hybrid', query_text: 'flood damage excess', result_count: 3, latency_ms: 140, created_at: now() }], total: 1, limit: 25, offset: 0 } }
  if (is('post', /^\/search/)) return { status: 200, data: { search_id: 'sr-2', mode: body.mode ?? 'hybrid', query: body.query, latency_ms: 120, cache_hit: false, results: CITES.map((c, i) => ({ chunk_id: `ch-${i + 1}`, document_id: c.document_id, version_id: 'v-1', title: c.title, section_path: c.section_path, clause_ref: c.clause_ref, page_from: 1, page_to: 1, content: 'We will pay for accidental loss of or damage to your vehicle, including damage caused by fire, theft and flood.', highlight: 'accidental loss of or damage to your vehicle, including damage caused by fire, theft and <mark>flood</mark>.', document_type: 'policy_wording', line_of_business: 'motor', jurisdictions: ['UK'], effective_from: '2026-01-01', effective_to: '2026-12-31', lifecycle_state: 'published', version_label: '2026.1', score: 0.87, explanation: { matched_branches: ['fts', 'vector'], branch_ranks: { fts: 1, vector: 2 }, branch_scores: {}, rrf_score: 0.032, rerank_score: 0.87 } })) } }
  if (is('get', /^\/conversations\/[^/]+$/)) return { status: 200, data: { conversation_id: 'cv-1', title: 'Flood cover (sample)', message_count: 2, created_at: now(), updated_at: now(), messages: [{ message_id: 'm-1', seq: 1, role: 'user', content: 'Is flood damage covered?', created_at: now() }, { message_id: 'm-2', seq: 2, role: 'assistant', content: ANSWER, answer_status: 'answered', evidence_strength: 'high', warnings: [], created_at: now(), citations: CITES }] } }
  if (is('get', /^\/conversations/)) return { status: 200, data: { items: [{ conversation_id: 'cv-1', title: 'Flood cover (sample)', message_count: 2, created_at: now(), updated_at: now() }], total: 1, limit: 50, offset: 0 } }
  if (is('post', /^\/feedback/)) return { status: 201, data: { feedback_id: 'f-1' } }
  if (is('get', /^\/admin\/dashboard/)) return { status: 200, data: { totals: { total_users: 24, active_users: 18, total_documents: 142, indexed_documents: 130, failed_ingestion_jobs: 2, searches: 1210, chats: 640, tokens: 2_400_000, estimated_cost: 31.4, avg_search_latency_ms: 180, abstentions: 22, feedback_positive: 80, feedback_negative: 12, feedback_satisfaction_pct: 87 }, series, quotas: [{ metric: 'users', used: 24, limit: 50, pct: 48 }, { metric: 'storage', used: 8_500_000_000, limit: 10_000_000_000, pct: 85 }, { metric: 'ai_tokens', used: 2_400_000, limit: 2_400_000, pct: 100 }], cost_note: 'Sample data. Costs are estimates.' } }
  if (is('get', /^\/admin\/ingestion\/jobs/)) return { status: 200, data: { items: [{ job_id: 'j-9', document_id: 'doc-1', version_id: 'v-1', job_type: 'ingest', status: 'failed', stage: 'parse', attempt: 3, max_attempts: 5, error_code: 'parse_error', error_message: 'Unsupported encoding', queued_at: now() }], total: 1, limit: 25, offset: 0 } }
  if (is('get', /^\/admin\/ingestion\/summary/)) return { status: 200, data: { by_status: { queued: 3, running: 1, retrying: 0, failed: 1, dead_letter: 1, quarantined: 0 } } }
  if (is('get', /^\/admin\/analytics\/search/)) return { status: 200, data: { summary: { searches: 1210, zero_result: 34, avg_latency_ms: 180, p95_latency_ms: 610, cache_hits: 300 }, by_mode: [{ mode: 'hybrid', n: 1000, avg_latency_ms: 190 }] } }
  if (is('get', /^\/platform\/dashboard/)) return { status: 200, data: { tenants: { total: 6, active: 4, suspended: 1, trial: 1, inactive: 0 }, users: { total_accounts: 120, active_accounts: 110, active_last_30_days: 90, tenant_users: 118 }, content: { documents: 900, chunks: 40000, storage_bytes: 52_000_000_000, active_ingestion_jobs: 3 }, usage: { searches: 9000, chats: 4000, tokens: 18_000_000, estimated_cost: 240.5, ingestion_failure_rate: 1.4, ingestion_failures: 5 }, series, top_tenants: [{ tenant_id: 't-1', code: 'abc-motor', name: 'ABC Motor', requests: 5000, tokens: 9_000_000, estimated_cost: 120 }], recent_events: [], health: { api: { status: 'up' }, database: { status: 'up' }, redis: { status: 'up' }, workers: { status: 'up' } }, alerts: [{ severity: 'warning', message: 'abc-motor: storage at 85% of quota' }], cost_note: 'Sample data.' } }
  return { status: 404, data: { error: { code: 'not_found', message: `Mock: ${method.toUpperCase()} ${url} is not mocked`, correlation_id: 'mock0000mock0000', details: [] } } }
}

const adapter: AxiosAdapter = (cfg) => {
  const { status, data } = route(cfg as InternalAxiosRequestConfig)
  const res: AxiosResponse = { data, status, statusText: String(status), headers: {}, config: cfg as InternalAxiosRequestConfig }
  return status >= 400 ? Promise.reject(Object.assign(new Error(`HTTP ${status}`), { isAxiosError: true, response: res, config: cfg, code: 'ERR_BAD_REQUEST' })) : Promise.resolve(res)
}

export function installMockApi() {
  apiClient.defaults.adapter = adapter
  const realFetch = window.fetch.bind(window)
  window.fetch = async (input, init) => {
    const u = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    if (!u.endsWith('/chat/stream')) return realFetch(input, init)
    const enc = new TextEncoder()
    const ev = (e: string, d: unknown) => enc.encode(`event: ${e}\ndata: ${JSON.stringify(d)}\n\n`)
    const parts = ANSWER.split(/(?<=\.) /)
    const stream = new ReadableStream({
      async start(c) {
        c.enqueue(ev('meta', { conversation_id: 'cv-1', correlation_id: 'mock0000mock0000', disclaimer: 'AI-generated knowledge assistance based on approved documents (sample). It is not a decision.' }))
        for (const p of parts) { await new Promise((r) => setTimeout(r, 350)); c.enqueue(ev('token', { text: `${p} ` })) }
        c.enqueue(ev('final', { conversation_id: 'cv-1', message_id: 'm-9', answer: ANSWER, status: 'answered', evidence_strength: 'high', warnings: [], ai_generated: true, citations: CITES, latency_ms: 1200, disclaimer: 'AI-generated knowledge assistance based on approved documents (sample). It is not a decision.' }))
        c.enqueue(ev('done', {})); c.close()
      },
    })
    return new Response(stream, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
  }
  const badge = document.createElement('div')
  badge.textContent = 'MOCK API: development sample data'
  badge.setAttribute('role', 'status')
  badge.style.cssText = 'position:fixed;bottom:8px;left:8px;z-index:9999;background:#8A5A00;color:#fff;font:12px sans-serif;padding:4px 8px;border-radius:6px'
  document.body.appendChild(badge)
}
