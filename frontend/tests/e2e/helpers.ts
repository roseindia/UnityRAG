import { expect, type Page, type Route } from '@playwright/test'

export type Persona = 'member' | 'admin' | 'platform'

const MEMBER = ['search.use', 'chat.use', 'documents.read', 'collections.read', 'documents.download', 'feedback.submit', 'documents.upload']
const ADMIN = [...MEMBER, 'admin.dashboard.view', 'admin.users.manage', 'admin.audit.view', 'admin.ingestion.manage']
const now = () => new Date().toISOString()

export const profileFor = (p: Persona) => ({
  account_id: 'a1', email: `${p}@example.test`, display_name: `E2E ${p}`, tenant_id: 't1', user_id: 'u1', user_type: 'employee', department_id: 'd1',
  platform_role: p === 'platform' ? 'platform_admin' : '', roles: [p], permissions: p === 'platform' ? [] : p === 'admin' ? ADMIN : MEMBER,
  platform_permissions: p === 'platform' ? ['platform.dashboard.view', 'platform.tenants.view'] : [], lines_of_business: ['motor'], jurisdictions: ['UK'], clearance_rank: 1,
  mfa_verified: false, console: p === 'platform' ? 'platform_admin' : p === 'admin' ? 'tenant_admin' : 'user',
})

const json = (route: Route, data: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', headers: { 'x-correlation-id': 'e2e-cid' }, body: JSON.stringify(data) })
const err = (route: Route, status: number, code: string, message = 'x') => json(route, { error: { code, message, correlation_id: 'abcd1234ef567890', details: [] } }, status)

export const CITATION = { marker: 'S1', document_id: 'doc1', chunk_id: 'ch1', title: 'ABC Motor Comprehensive Policy Wording', version_label: '2026.1', section_path: 'Section 2 > What is covered', clause_ref: '2.1', page_from: 1, page_to: 1, effective_from: '2026-01-01', effective_to: '2026-12-31', lifecycle_state: 'published', verified: true }
export const ANSWER = 'Flood damage is covered. [S1] Check your schedule.'

const sse = (events: [string, unknown][]) => events.map(([e, d]) => `event: ${e}\ndata: ${JSON.stringify(d)}\n\n`).join('')

export interface Stub { persona: Persona; jobStatus: string; calls: { url: string; method: string; body?: string | null }[]; failDocuments: boolean }

/** Stubs the backend at the network layer. All values are test data. */
export async function stubApi(page: Page, persona: Persona = 'member'): Promise<Stub> {
  const stub: Stub = { persona, jobStatus: 'running', calls: [], failDocuments: false }
  await page.route('**/api/v1/**', async (route) => {
    const req = route.request()
    const url = new URL(req.url())
    const path = url.pathname.replace('/api/v1', '')
    const m = req.method()
    stub.calls.push({ url: path + url.search, method: m, body: req.postData() })
    const is = (method: string, re: RegExp) => m === method && re.test(path)
    if (is('POST', /^\/auth\/login/)) {
      const body = JSON.parse(req.postData() ?? '{}')
      if (body.password === 'wrong') return err(route, 401, 'invalid_credentials')
      return json(route, { access_token: 'e2e-access', refresh_token: 'e2e-refresh', expires_at: new Date(Date.now() + 600_000).toISOString(), session_id: 's1', tenant_id: 't1', platform_role: '', memberships: [{ tenant_id: 't1', tenant_code: 'abc', tenant_name: 'ABC Insurance', tenant_status: 'active', membership_status: 'active', is_default: true }] })
    }
    if (is('GET', /^\/auth\/me/)) return json(route, profileFor(stub.persona))
    if (is('POST', /^\/auth\/logout/)) return json(route, { message: 'ok' })
    if (is('GET', /^\/collections/)) return json(route, [{ collection_id: 'c1', code: 'motor', name: 'Motor policies', can_write: true }])
    if (is('GET', /^\/documents\/[^/]+\/preview/)) return json(route, { document_id: 'doc1', title: CITATION.title, version_id: 'v1', page_number: 1, pages_total: 2, text: 'Section 2. Flood damage is covered. Contact [EMAIL REDACTED]' })
    if (is('GET', /^\/documents/)) return stub.failDocuments ? err(route, 500, 'internal_error') : json(route, { items: [{ document_id: 'doc1', collection_id: 'c1', title: 'ABC Motor Comprehensive Policy Wording', document_type: 'policy_wording', insurance_line: 'motor', classification: 'internal', lifecycle_state: 'published', size_bytes: 1024, created_at: now(), updated_at: now() }], total: 1, limit: 50, offset: 0 })
    if (is('POST', /^\/documents$/)) return json(route, { document_id: 'doc2', version_id: 'v1', job_id: 'job1' }, 202)
    if (is('GET', /^\/ingestion\/jobs\//)) return json(route, { job_id: 'job1', document_id: 'doc2', version_id: 'v1', job_type: 'ingest', status: stub.jobStatus, stage: stub.jobStatus === 'succeeded' ? 'publish' : 'embed', attempt: 1, max_attempts: 5 })
    if (is('GET', /^\/search\/facets/)) return json(route, { line_of_business: [{ value: 'motor', label: 'motor', count: 1 }] })
    if (is('POST', /^\/search/)) return json(route, { search_id: 's1', mode: 'hybrid', query: 'flood', latency_ms: 90, cache_hit: false, results: [{ chunk_id: 'ch1', document_id: 'doc1', version_id: 'v1', title: CITATION.title, section_path: CITATION.section_path, clause_ref: '2.1', page_from: 1, page_to: 1, content: 'Flood damage is covered.', highlight: 'damage caused by <mark>flood</mark>', document_type: 'policy_wording', jurisdictions: ['UK'], effective_from: '2026-01-01', effective_to: '2026-12-31', lifecycle_state: 'published', version_label: '2026.1', score: 0.9 }] })
    if (is('GET', /^\/search\/history/) || is('GET', /^\/conversations/)) return json(route, { items: [], total: 0, limit: 50, offset: 0 })
    if (is('POST', /^\/chat\/stream/)) {
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body: sse([
        ['meta', { conversation_id: 'cv1', correlation_id: 'x', disclaimer: 'AI-generated guidance based on approved documents.' }],
        ['token', { text: 'Flood damage is covered. [S1] ' }],
        ['final', { conversation_id: 'cv1', message_id: 'm1', answer: ANSWER, status: 'answered', evidence_strength: 'high', warnings: [], ai_generated: true, citations: [CITATION], disclaimer: 'AI-generated guidance based on approved documents.' }],
        ['done', {}],
      ]) })
    }
    if (is('POST', /^\/feedback/)) return json(route, { feedback_id: 'f1' }, 201)
    if (is('GET', /^\/admin\/dashboard/)) return json(route, { totals: { total_users: 5, active_users: 4, total_documents: 10, failed_ingestion_jobs: 0 }, series: [], quotas: [{ metric: 'users', used: 5, limit: 50, pct: 10 }] })
    if (is('GET', /^\/admin\/ingestion\/jobs/)) return json(route, { items: [], total: 0, limit: 25, offset: 0 })
    if (is('GET', /^\/admin\/audit\/verify/)) return json(route, { valid: true, events: 3 })
    if (path.startsWith('/admin/')) return err(route, 403, 'permission_denied')
    return err(route, 404, 'not_found')
  })
  return stub
}

export async function login(page: Page, start = '/') {
  await page.goto(start)
  await expect(page.getByRole('heading', { name: 'UnityRAG' })).toBeVisible()
  await page.getByLabel('Email').fill('person@example.test')
  await page.getByLabel('Password').fill('not-a-real-password')
  await page.getByRole('button', { name: 'Sign in' }).click()
}
