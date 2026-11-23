// In-memory stand-in for the backend, used only to take documentation screenshots with SAMPLE data.
import type { Page, Route } from '@playwright/test'

type R = Record<string, any>
let seq = 100
const nid = (p: string) => `${p}-${++seq}`
const iso = (minAgo = 0) => new Date(Date.now() - minAgo * 60_000).toISOString()

const MEMBER = ['search.use', 'chat.use', 'documents.read', 'collections.read', 'documents.download', 'feedback.submit']
const CONTRIB = [...MEMBER, 'documents.upload', 'documents.manage']
const ADMIN = [...CONTRIB, 'documents.delete', 'feedback.review', 'admin.dashboard.view', 'admin.users.manage', 'admin.roles.manage', 'admin.departments.manage',
  'admin.groups.manage', 'admin.collections.manage', 'admin.documents.manage', 'admin.ingestion.manage', 'admin.ai_config.manage', 'admin.rag_config.manage', 'admin.analytics.view',
  'admin.usage.view', 'admin.audit.view', 'admin.settings.manage', 'admin.reports.export', 'evaluation.manage', 'evaluation.run']
const PLATFORM = ['platform.dashboard.view', 'platform.tenants.view', 'platform.tenants.manage', 'platform.plans.manage', 'platform.ai.manage', 'platform.monitoring.view',
  'platform.security.view', 'platform.audit.view', 'platform.users.manage', 'platform.settings.manage', 'platform.break_glass.use', 'platform.quotas.manage']

const ROLE_DEFS: [string, string][] = [['tenant_admin', 'Tenant Administrator'], ['knowledge_manager', 'Knowledge Manager'], ['department_admin', 'Department Administrator'],
  ['auditor', 'Auditor'], ['document_contributor', 'Document Contributor'], ['member', 'Member'], ['external_partner', 'Broker / Agent']]
const ROLE_PERMS: Record<string, string[]> = {
  tenant_admin: ADMIN, member: [...MEMBER], document_contributor: CONTRIB, knowledge_manager: CONTRIB, department_admin: [...MEMBER, 'documents.upload'],
  auditor: ['admin.audit.view', 'admin.analytics.view', 'admin.usage.view', 'admin.reports.export'], external_partner: MEMBER.filter((p) => p !== 'documents.download'),
}
const ROLES: R[] = ROLE_DEFS.map(([code, name]) => ({ role_id: `role-${code}`, code, name, description: name, is_system: true, user_count: 0, permissions: ROLE_PERMS[code] ?? [], conflicts_with: [] }))
export const customRoles: R[] = []
const permsOfRoles = (codes: string[]) => [...new Set(codes.flatMap((c) => ROLE_PERMS[c] ?? (customRoles.find((r) => r.code === c)?.permissions as string[] | undefined) ?? []))]
const CATEGORY: Record<string, string> = { admin: 'administration', documents: 'documents', collections: 'collections', search: 'search', chat: 'chat', feedback: 'feedback', evaluation: 'evaluation' }
const ALL_PERMS = [...new Set(ADMIN)].map((code) => ({ permission_code: code, category: CATEGORY[code.split('.')[0]] ?? 'other', description: code }))
export const platform: { providers: R[]; models: R[] } = { providers: [], models: [] }

export const SAMPLE_TEXT = [
  { section: 'Section 2 > What is covered', clause: '2.1', page: 1, text: 'Flood damage. We cover loss of or damage to the insured vehicle caused by flood, storm, lightning, fire or explosion. Flood damage is covered under this section, subject to the excess shown in the schedule.' },
  { section: 'Section 3 > Excess', clause: '3.1', page: 1, text: 'The standard excess is 250 for every claim. A young driver excess of 400 is added when the driver is under 25 years of age.' },
]


const MODELS = [
  { provider: 'local', model_name: 'extractive-v1', purpose: 'chat', dimensions: null, status: 'active' },
  { provider: 'ollama-chat', model_name: 'llama3.1:8b', purpose: 'chat', dimensions: null, status: 'approved' },
  { provider: 'openai', model_name: 'gpt-4o-mini', purpose: 'chat', dimensions: null, status: 'approved' },
  { provider: 'local', model_name: 'hashing-v1', purpose: 'embedding', dimensions: 384, status: 'active' },
  { provider: 'ollama-embed', model_name: 'nomic-embed-text', purpose: 'embedding', dimensions: 768, status: 'approved' },
  { provider: 'openai', model_name: 'text-embedding-3-small', purpose: 'embedding', dimensions: 1536, status: 'approved' },
  { provider: 'local', model_name: 'lexical-overlap-v1', purpose: 'rerank', dimensions: null, status: 'active' },
  { provider: 'local', model_name: 'rule-rewriter-v1', purpose: 'rewrite', dimensions: null, status: 'active' },
]
export const cfg: { ai: R[]; rag: R[] } = {
  ai: [{ version: 1, llm_provider: 'local', chat_model: 'extractive-v1', embedding_provider: 'local', embedding_model: 'hashing-v1', embedding_dimensions: 384, reranker_provider: 'local', reranker_model: 'lexical-overlap-v1', rewrite_model: 'rule-rewriter-v1', temperature: 0.2, max_output_tokens: 1024, distance_metric: 'cosine', change_reason: 'initial provisioning', created_at: iso(60 * 24 * 30) }],
  rag: [{ version: 1, chunking_strategy: 'structure_aware', chunk_size: 350, chunk_overlap: 40, parent_child: true, vector_top_k: 30, fts_top_k: 30, exact_top_k: 10, vector_weight: 1, fts_weight: 1, exact_weight: 1.5, rrf_k: 60, rerank_enabled: true, rerank_top_n: 20, final_top_k: 6, max_context_tokens: 3000, min_relevance: 0, hnsw_ef_search: 100, citation_required: true, query_rewriting: true,
    guardrails: { prompt_injection: 'block', pii_output: 'mask', regulated_decision: 'block' }, change_reason: 'initial provisioning', created_at: iso(60 * 24 * 30) }],
}

platform.providers.push({ provider_id: 'prov-local', code: 'local', name: 'Built-in local models', provider_type: 'local', base_url: null, region: 'local', is_enabled: true, allow_tenant_override: false, rate_limit_per_min: null, api_key_masked: null, health_status: 'healthy' })
platform.providers.push({ provider_id: 'prov-ollama-chat', code: 'ollama-chat', name: 'Ollama (chat)', provider_type: 'ollama', base_url: 'http://host.docker.internal:11434/v1', region: 'local', is_enabled: true, allow_tenant_override: false, rate_limit_per_min: null, api_key_masked: null, health_status: 'healthy' })
platform.providers.push({ provider_id: 'prov-ollama-embed', code: 'ollama-embed', name: 'Ollama (embeddings)', provider_type: 'ollama', base_url: 'http://host.docker.internal:11434', region: 'local', is_enabled: true, allow_tenant_override: false, rate_limit_per_min: null, api_key_masked: null, health_status: 'healthy' })
platform.providers.push({ provider_id: 'prov-openai', code: 'openai', name: 'OpenAI', provider_type: 'openai', base_url: null, region: 'global', is_enabled: true, allow_tenant_override: false, rate_limit_per_min: 600, api_key_masked: '****abcd', health_status: 'healthy' })
MODELS.forEach((x, i) => platform.models.push({ model_id: 'model-' + i, ...x, model_version: '', context_window: x.purpose === 'chat' ? 8192 : null, risk_class: 'low', is_default: false }))

export interface State {
  tenants: R[]; plans: R[]; depts: R[]; teams: R[]; groups: R[]; users: R[]; collections: R[]; docs: R[]; jobs: Record<string, R>
  tenantCreated: boolean; jobPolls: number
}
export const state: State = {
  tenants: [
    { tenant_id: 't-nw', code: 'northwind', name: 'Northwind Mutual', status: 'active', plan_code: 'professional', users_count: 42, documents_count: 1280, storage_bytes: 2_100_000_000, last_activity_at: iso(35), created_at: iso(60 * 24 * 90) },
    { tenant_id: 't-bw', code: 'bluewater', name: 'Bluewater Assurance', status: 'trial', plan_code: 'trial', users_count: 6, documents_count: 31, storage_bytes: 48_000_000, last_activity_at: iso(60 * 5), created_at: iso(60 * 24 * 12) },
  ],
  plans: [
    { code: 'trial', name: 'Trial' }, { code: 'starter', name: 'Starter' }, { code: 'professional', name: 'Professional' }, { code: 'enterprise', name: 'Enterprise' },
  ],
  depts: [], teams: [], groups: [], users: [], collections: [], docs: [], jobs: {}, tenantCreated: false, jobPolls: 0,
}

const json = (route: Route, data: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', headers: { 'x-correlation-id': 'doc-shots' }, body: JSON.stringify(data) })
const err = (route: Route, status: number, code: string, message: string) => json(route, { error: { code, message, correlation_id: 'abcd1234ef567890', details: [] } }, status)
const page = <T,>(items: T[], limit = 25) => ({ items, total: items.length, limit, offset: 0 })

function personaOf(token: string): string { return token.replace('tok-', '') }
function profile(persona: string) {
  if (persona === 'platform') return { account_id: 'a-p', email: 'platform@example.test', display_name: 'Pat Platform', tenant_id: null, user_id: null, user_type: 'employee', department_id: null, platform_role: 'super', roles: [], permissions: [], platform_permissions: PLATFORM, lines_of_business: [], jurisdictions: [], clearance_rank: 0, mfa_verified: false, console: 'platform_admin' }
  const u = state.users.find((x) => x.persona === persona)
  const perms = u ? permsOfRoles(u.roles) : persona === 'alice' ? ADMIN : persona === 'uma' ? CONTRIB : MEMBER
  return { account_id: `a-${persona}`, email: u?.email ?? `${persona}@acme.example`, display_name: u?.display_name ?? persona, tenant_id: 't-acme', user_id: u?.user_id ?? 'u-x', user_type: 'employee', department_id: u?.department_id ?? null,
    platform_role: '', roles: u?.roles ?? [], permissions: perms, platform_permissions: [], lines_of_business: u?.lines_of_business ?? [], jurisdictions: u?.jurisdictions ?? [], clearance_rank: u?.clearance_rank ?? 1, mfa_verified: false, console: perms.some((p) => p.startsWith('admin.')) ? 'tenant_admin' : 'user' }
}

const sse = (events: [string, unknown][]) => events.map(([e, d]) => `event: ${e}\ndata: ${JSON.stringify(d)}\n\n`).join('')

export async function installFake(pg: Page) {
  await pg.route('**/api/v1/**', async (route) => {
    const req = route.request()
    const url = new URL(req.url())
    const path = url.pathname.replace('/api/v1', '')
    const m = req.method()
    const body: R = (() => { try { return JSON.parse(req.postData() ?? '{}') } catch { return {} } })()
    const auth = req.headers()['authorization'] ?? ''
    const persona = personaOf(auth.replace('Bearer ', ''))
    const is = (method: string, re: RegExp) => m === method && re.test(path)
    const q = (url.searchParams.get('q') ?? '').toLowerCase()

    // ---------------------------------------------------------------- auth
    if (is('POST', /^\/auth\/login/)) {
      const email = String(body.email ?? '').toLowerCase()
      const who = email.startsWith('platform') ? 'platform' : email.startsWith('alice') ? 'alice' : email.startsWith('dana') ? 'dana' : email.startsWith('uma') ? 'uma' : 'carlos'
      const memberships = who === 'platform' ? [] : [{ tenant_id: 't-acme', tenant_code: 'acme', tenant_name: 'Acme Insurance', tenant_status: 'active', membership_status: 'active', is_default: true }]
      return json(route, { access_token: `tok-${who}`, refresh_token: `ref-${who}`, expires_at: new Date(Date.now() + 3_600_000).toISOString(), session_id: 's1', tenant_id: who === 'platform' ? null : 't-acme', platform_role: who === 'platform' ? 'super' : '', memberships })
    }
    if (is('GET', /^\/auth\/me/)) return json(route, profile(persona))
    if (is('POST', /^\/auth\/logout/)) return json(route, { message: 'ok' })

    // ---------------------------------------------------------------- platform
    if (is('GET', /^\/platform\/dashboard/)) return json(route, { totals: { tenants: state.tenants.length, active_tenants: 2, total_users: 48, total_documents: 1311 }, series: [], alerts: [] })
    if (is('GET', /^\/platform\/plans/)) return json(route, state.plans)
    if (is('GET', /^\/platform\/tenants$/)) return json(route, page(state.tenants.filter((t) => !q || `${t.name}${t.code}`.toLowerCase().includes(q))))
    if (is('POST', /^\/platform\/tenants$/)) {
      const t = { tenant_id: 't-acme', code: body.code, name: body.name, legal_entity: body.legal_entity, home_region: body.home_region ?? 'default', status: body.plan_code === 'trial' ? 'trial' : 'active', plan_code: body.plan_code, plan_name: state.plans.find((p) => p.code === body.plan_code)?.name, users_count: 1, documents_count: 0, chunks_count: 0, storage_bytes: 0, ai_tokens_month: 0, last_activity_at: null, created_at: iso(), branding: {} }
      state.tenants.unshift(t)
      state.users.push({ user_id: 'u-alice', persona: 'alice', email: body.admin_email, display_name: body.admin_name, user_type: 'employee', department_id: null, roles: ['tenant_admin'], status: 'active', lines_of_business: [], jurisdictions: ['*'], clearance_rank: 3, group_ids: [], last_active_at: null })
      return json(route, { tenant: t, initial_admin: { user_id: 'u-alice', email: body.admin_email } }, 201)
    }
    let mm = path.match(/^\/platform\/tenants\/([^/]+)(\/.*)?$/)
    if (mm && m === 'GET') {
      const t = state.tenants.find((x) => x.tenant_id === mm![1])
      if (!t) return err(route, 404, 'not_found', 'Not found')
      if (mm[2] === '/admins') return json(route, state.users.filter((u) => u.roles.includes('tenant_admin')).map((u) => ({ user_id: u.user_id, email: u.email, display_name: u.display_name, status: u.status })))
      if (!mm[2]) return json(route, t)
      return json(route, {})
    }
    if (is('GET', /^\/platform\/ai-providers$/)) return json(route, platform.providers)
    if (is('POST', /^\/platform\/ai-providers$/)) { const p = { provider_id: nid('prov'), code: body.code, name: body.name, provider_type: body.provider_type, base_url: body.base_url, region: body.region, is_enabled: body.is_enabled ?? true, allow_tenant_override: body.allow_tenant_override ?? false, rate_limit_per_min: body.rate_limit_per_min, api_key_masked: body.api_key ? '****' + String(body.api_key).slice(-4) : null, health_status: 'unknown' }; platform.providers.push(p); return json(route, p, 201) }
    mm = path.match(/^\/platform\/ai-providers\/([^/]+)\/health-check$/)
    if (mm && m === 'POST') return json(route, { health_status: 'healthy', detail: 'reachable' })
    if (is('GET', /^\/platform\/models$/)) return json(route, platform.models.filter((x) => !url.searchParams.get('purpose') || x.purpose === url.searchParams.get('purpose')))
    if (is('POST', /^\/platform\/models$/)) { const pr = platform.providers.find((p) => p.provider_id === body.provider_id); const x = { model_id: nid('model'), model_name: body.model_name, model_version: body.model_version, provider: pr?.code, purpose: body.purpose, dimensions: body.dimensions, context_window: body.context_window, input_cost_per_1k: body.input_cost_per_1k, output_cost_per_1k: body.output_cost_per_1k, risk_class: body.risk_class, status: 'proposed', is_default: false }; platform.models.push(x); return json(route, x, 201) }
    mm = path.match(/^\/platform\/models\/([^/]+)$/)
    if (mm && m === 'PUT') { const x = platform.models.find((q2) => q2.model_id === mm![1]); if (x) Object.assign(x, body); return json(route, x ?? {}) }
    if (path.startsWith('/platform/')) return json(route, [])

    // ---------------------------------------------------------------- tenant administration
    if (is('GET', /^\/admin\/dashboard/)) return json(route, { totals: { total_users: state.users.length, active_users: state.users.length, total_documents: state.docs.length, failed_ingestion_jobs: 0, total_collections: state.collections.length }, series: [], quotas: [{ metric: 'users', used: state.users.length, limit: 500, pct: 1 }, { metric: 'documents', used: state.docs.length, limit: 100000, pct: 0 }] })
    if (is('GET', /^\/admin\/roles/)) return json(route, [...ROLES, ...customRoles])
    if (is('POST', /^\/admin\/roles$/)) { const r = { role_id: `role-${body.code}`, code: body.code, name: body.name, description: body.description ?? '', is_system: false, user_count: 0, permissions: body.permissions ?? [], conflicts_with: body.conflicts_with ?? [] }; customRoles.push(r); return json(route, r, 201) }
    if (is('GET', /^\/admin\/permissions$/)) return json(route, ALL_PERMS)
    mm = path.match(/^\/admin\/permissions\/effective\/([^/]+)$/)
    if (mm) return json(route, { permissions: permsOfRoles(state.users.find((u) => u.user_id === mm![1])?.roles ?? []) })
    if (is('GET', /^\/admin\/departments$/)) return json(route, state.depts.map((d) => ({ ...d, user_count: state.users.filter((u) => u.department_id === d.department_id).length, team_count: state.teams.filter((t) => t.department_id === d.department_id).length })))
    if (is('POST', /^\/admin\/departments$/)) { const d = { department_id: nid('dep'), code: body.code, name: body.name, description: body.description, status: 'active', parent_department_id: body.parent_department_id ?? null }; state.depts.push(d); return json(route, d, 201) }
    if (is('GET', /^\/admin\/teams/)) return json(route, state.teams.map((t) => ({ ...t, members: 0 })))
    if (is('POST', /^\/admin\/teams$/)) { const t = { team_id: nid('team'), department_id: body.department_id, name: body.name }; state.teams.push(t); return json(route, t, 201) }
    if (is('GET', /^\/admin\/groups$/)) return json(route, state.groups.map((g) => ({ ...g, members: state.users.filter((u) => u.group_ids.includes(g.group_id)).length })))
    if (is('POST', /^\/admin\/groups$/)) { const g = { group_id: nid('grp'), name: body.name, description: body.description ?? '' }; state.groups.push(g); return json(route, g, 201) }
    mm = path.match(/^\/admin\/groups\/([^/]+)\/members(?:\/([^/]+))?$/)
    if (mm) {
      if (m === 'GET') return json(route, state.users.filter((u) => u.group_ids.includes(mm![1])))
      if (m === 'POST') { state.users.find((u) => u.user_id === body.user_id)?.group_ids.push(mm[1]); return json(route, { message: 'ok' }) }
    }
    if (is('GET', /^\/admin\/users$/)) {
      const rows = state.users.filter((u) => !q || `${u.display_name}${u.email}`.toLowerCase().includes(q))
      return json(route, page(rows.map((u) => ({ ...u })), Number(url.searchParams.get('limit') ?? 25)))
    }
    if (is('POST', /^\/admin\/users$/)) {
      const who = String(body.email).startsWith('uma') ? 'uma' : 'carlos'
      const u = { user_id: nid('u'), persona: who, email: body.email, display_name: body.display_name, user_type: body.user_type, department_id: body.department_id ?? null, roles: body.roles?.length ? body.roles : ['member'], status: 'active', lines_of_business: body.lines_of_business ?? [], jurisdictions: body.jurisdictions ?? [], clearance_rank: body.clearance_rank ?? 1, group_ids: [] as string[], last_active_at: null }
      state.users.push(u)
      return json(route, u, 201)
    }
    mm = path.match(/^\/admin\/users\/([^/]+)(\/.*)?$/)
    if (mm) {
      const u = state.users.find((x) => x.user_id === mm![1])
      if (!u) return err(route, 404, 'not_found', 'Not found')
      if (!mm[2] && m === 'GET') return json(route, u)
      if (mm[2] === '/roles' && m === 'POST') { const code = String(body.role_id).replace('role-', ''); if (!u.roles.includes(code)) u.roles.push(code); return json(route, { message: 'ok' }) }
      if (mm[2]?.startsWith('/permissions') || mm[2] === '/logins') return json(route, [])
      return json(route, {})
    }
    if (is('GET', /^\/admin\/permissions\/effective/)) return json(route, { permissions: MEMBER })
    if (is('GET', /^\/admin\/collections$/)) return json(route, state.collections.map((c) => ({ ...c, document_count: state.docs.filter((d) => d.collection_id === c.collection_id).length })))
    if (is('POST', /^\/admin\/collections$/)) {
      const c = { collection_id: nid('col'), code: body.code, name: body.name, description: body.description, line_of_business: body.line_of_business, classification: body.classification ?? 'internal', jurisdictions: body.jurisdictions ?? [], retention_days: body.retention_days, auto_publish: body.auto_publish ?? true, status: 'active', access: [] as R[], can_write: true }
      state.collections.push(c)
      return json(route, c, 201)
    }
    mm = path.match(/^\/admin\/collections\/([^/]+)(\/.*)?$/)
    if (mm) {
      const c = state.collections.find((x) => x.collection_id === mm![1])
      if (!c) return err(route, 404, 'not_found', 'Not found')
      if (!mm[2] && m === 'GET') return json(route, c)
      if (mm[2] === '/access' && m === 'PUT') { c.access = (req.postDataJSON() as R[]).map((r) => ({ ...r })); return json(route, c) }
      return json(route, { documents: state.docs.length })
    }
    if (is('GET', /^\/admin\/documents$/)) return json(route, page(state.docs.map((d) => ({ ...d })), 50))
    if (is('GET', /^\/admin\/ingestion\/jobs/)) return json(route, page(Object.values(state.jobs), 25))
    if (is('GET', /^\/admin\/config$/)) return json(route, { ai: cfg.ai[0], rag: cfg.rag[0], tenant_overridable_settings: null, available_models: platform.models.filter((m) => ['approved', 'active'].includes(m.status) && platform.providers.find((p) => p.code === m.provider)?.is_enabled !== false) })
    if (is('PUT', /^\/admin\/config\/(ai|rag)$/)) {
      const kind = path.endsWith('/ai') ? 'ai' : 'rag'
      const { reason, ...changes } = body
      const next = { ...cfg[kind][0], ...changes, version: cfg[kind][0].version + 1, change_reason: reason, created_at: iso() }
      cfg[kind].unshift(next)
      return json(route, next)
    }
    mm = path.match(/^\/admin\/config\/history\/(ai|rag)$/)
    if (mm) return json(route, cfg[mm[1] as 'ai' | 'rag'])
    if (path.startsWith('/admin/')) return json(route, {})

    // ---------------------------------------------------------------- everyday user
    if (is('GET', /^\/collections/)) {
      const usable = state.collections.filter((c) => (persona === 'uma' ? c.access.some((a: R) => a.principal_type === 'role' && a.permission !== 'read') : c.access.some((a: R) => a.principal_type === 'department')))
      return json(route, usable.map((c) => ({ collection_id: c.collection_id, code: c.code, name: c.name, can_write: persona === 'uma' })))
    }
    if (is('POST', /^\/documents$/)) {
      const id = nid('doc'); const job = nid('job')
      state.docs.push({ document_id: id, collection_id: state.collections[0].collection_id, title: 'ACME Motor Policy Wording Sample', document_type: 'policy_wording', insurance_line: 'motor', classification: 'internal', lifecycle_state: 'published', size_bytes: 2300, created_at: iso(), updated_at: iso() })
      state.jobs[job] = { job_id: job, document_id: id, version_id: 'v1', job_type: 'ingest', status: 'running', stage: 'embed', attempt: 1, max_attempts: 5 }
      state.jobPolls = 0
      return json(route, { document_id: id, version_id: 'v1', job_id: job }, 202)
    }
    mm = path.match(/^\/ingestion\/jobs\/([^/]+)/)
    if (mm && m === 'GET') {
      const j = state.jobs[mm[1]]; state.jobPolls += 1
      if (state.jobPolls >= 2) { j.status = 'succeeded'; j.stage = 'publish' }
      return json(route, j)
    }
    if (is('GET', /^\/documents\/[^/]+\/preview/)) return json(route, { document_id: 'doc', title: 'ACME Motor Policy Wording Sample', version_id: 'v1', page_number: 1, pages_total: 1, text: 'SECTION 2. WHAT IS COVERED\n\n2.1 Flood damage. We cover loss of or damage to the insured vehicle caused by flood, storm, lightning, fire or explosion. Flood damage is covered under this section, subject to the excess shown in the schedule.\n2.2 Theft. We cover theft or attempted theft of the insured vehicle.' })
    if (is('GET', /^\/documents\/[^/]+$/)) return json(route, state.docs[0] ?? {})
    if (is('GET', /^\/documents/)) return json(route, page(state.docs.map((d) => ({ ...d })), 50))
    if (is('GET', /^\/search\/facets/)) return json(route, { line_of_business: [{ value: 'motor', label: 'motor', count: 1 }], document_type: [{ value: 'policy_wording', label: 'policy_wording', count: 1 }], collection: state.collections.map((c) => ({ value: c.collection_id, label: c.name, count: 1 })) })
    if (is('POST', /^\/search$/)) {
      return json(route, { search_id: 's1', mode: 'hybrid', query: body.query ?? '', latency_ms: 84, cache_hit: false,
        results: SAMPLE_TEXT.map((x, i) => ({ chunk_id: `ch${i}`, document_id: 'doc', version_id: 'v1', title: 'ACME Motor Policy Wording Sample', section_path: x.section, clause_ref: x.clause, page_from: x.page, page_to: x.page, content: x.text,
          highlight: x.text.replace(/(flood|excess)/gi, '<mark>$1</mark>'), document_type: 'policy_wording', jurisdictions: ['US'], effective_from: '2026-01-01', effective_to: null, lifecycle_state: 'published', version_label: '2026.1', score: 0.9 - i * 0.3 })) })
    }
    if (is('GET', /^\/search\/history/) || is('GET', /^\/conversations/)) return json(route, page([], 50))
    if (is('POST', /^\/chat\/stream/)) {
      const cite = { marker: 'S1', document_id: 'doc', chunk_id: 'ch0', title: 'ACME Motor Policy Wording Sample', version_label: '2026.1', section_path: 'Section 2 > What is covered', clause_ref: '2.1', page_from: 1, page_to: 1, effective_from: '2026-01-01', effective_to: null, lifecycle_state: 'published', verified: true }
      const answer = 'Yes. Flood damage to the insured vehicle is covered, subject to the excess shown in your schedule [S1]. The standard excess is 250 per claim, and a young driver excess of 400 is added for drivers under 25 [S2].'
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body: sse([
        ['meta', { conversation_id: 'cv1', correlation_id: 'x', disclaimer: 'AI-generated guidance based on approved documents.' }],
        ['token', { text: answer }],
        ['final', { conversation_id: 'cv1', message_id: 'm1', answer, status: 'answered', evidence_strength: 'high', warnings: [], ai_generated: true,
          citations: [cite, { ...cite, marker: 'S2', chunk_id: 'ch1', section_path: 'Section 3 > Excess', clause_ref: '3.1' }], disclaimer: 'AI-generated guidance based on approved documents.' }],
        ['done', {}]]) })
    }
    if (is('POST', /^\/feedback/)) return json(route, { feedback_id: 'f1' }, 201)
    return json(route, [])
  })
}
