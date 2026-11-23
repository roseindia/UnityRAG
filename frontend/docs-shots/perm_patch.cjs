const fs = require('fs')
let s = fs.readFileSync(__dirname + '/fakeBackend.ts', 'utf8')
const rep = (a, b) => { if (!s.includes(a)) throw new Error('missing: ' + a.slice(0, 60)); s = s.replace(a, b) }

// 1. roles carry their permissions; custom roles and a platform catalogue are kept in memory
rep("const ROLES = ROLE_DEFS.map(([code, name]) => ({ role_id: `role-${code}`, code, name, description: name, is_system: true, user_count: 0, permissions: [], conflicts_with: [] }))",
`const ROLE_PERMS: Record<string, string[]> = {
  tenant_admin: ADMIN, member: [...MEMBER], document_contributor: CONTRIB, knowledge_manager: CONTRIB, department_admin: [...MEMBER, 'documents.upload'],
  auditor: ['admin.audit.view', 'admin.analytics.view', 'admin.usage.view', 'admin.reports.export'], external_partner: MEMBER.filter((p) => p !== 'documents.download'),
}
const ROLES: R[] = ROLE_DEFS.map(([code, name]) => ({ role_id: \`role-\${code}\`, code, name, description: name, is_system: true, user_count: 0, permissions: ROLE_PERMS[code] ?? [], conflicts_with: [] }))
export const customRoles: R[] = []
const permsOfRoles = (codes: string[]) => [...new Set(codes.flatMap((c) => ROLE_PERMS[c] ?? (customRoles.find((r) => r.code === c)?.permissions as string[] | undefined) ?? []))]
const CATEGORY: Record<string, string> = { admin: 'administration', documents: 'documents', collections: 'collections', search: 'search', chat: 'chat', feedback: 'feedback', evaluation: 'evaluation' }
const ALL_PERMS = [...new Set(ADMIN)].map((code) => ({ permission_code: code, category: CATEGORY[code.split('.')[0]] ?? 'other', description: code }))
export const platform: { providers: R[]; models: R[] } = { providers: [], models: [] }`)

// 2. profile of a tenant user follows the roles it holds
rep("  const perms = persona === 'alice' ? ADMIN : persona === 'uma' ? CONTRIB : MEMBER\n",
    "  const perms = u ? permsOfRoles(u.roles) : persona === 'alice' ? ADMIN : persona === 'uma' ? CONTRIB : MEMBER\n")
rep("console: persona === 'alice' ? 'tenant_admin' : 'user' }", "console: perms.some((p) => p.startsWith('admin.')) ? 'tenant_admin' : 'user' }")
rep("const who = email.startsWith('platform') ? 'platform' : email.startsWith('alice') ? 'alice' : email.startsWith('uma') ? 'uma' : 'carlos'",
    "const who = email.startsWith('platform') ? 'platform' : email.startsWith('alice') ? 'alice' : email.startsWith('dana') ? 'dana' : email.startsWith('uma') ? 'uma' : 'carlos'")

// 3. tenant-side handlers
rep("    if (is('GET', /^\\/admin\\/roles/)) return json(route, ROLES)",
`    if (is('GET', /^\\/admin\\/roles/)) return json(route, [...ROLES, ...customRoles])
    if (is('POST', /^\\/admin\\/roles$/)) { const r = { role_id: \`role-\${body.code}\`, code: body.code, name: body.name, description: body.description ?? '', is_system: false, user_count: 0, permissions: body.permissions ?? [], conflicts_with: body.conflicts_with ?? [] }; customRoles.push(r); return json(route, r, 201) }
    if (is('GET', /^\\/admin\\/permissions$/)) return json(route, ALL_PERMS)
    mm = path.match(/^\\/admin\\/permissions\\/effective\\/([^/]+)$/)
    if (mm) return json(route, { permissions: permsOfRoles(state.users.find((u) => u.user_id === mm![1])?.roles ?? []) })`)

// 4. approved models come from the platform catalogue
rep("available_models: MODELS })", "available_models: platform.models.filter((m) => ['approved', 'active'].includes(m.status) && platform.providers.find((p) => p.code === m.provider)?.is_enabled !== false) })")

// 5. platform handlers
rep("    if (path.startsWith('/platform/')) return json(route, [])",
`    if (is('GET', /^\\/platform\\/ai-providers$/)) return json(route, platform.providers)
    if (is('POST', /^\\/platform\\/ai-providers$/)) { const p = { provider_id: nid('prov'), code: body.code, name: body.name, provider_type: body.provider_type, base_url: body.base_url, region: body.region, is_enabled: body.is_enabled ?? true, allow_tenant_override: body.allow_tenant_override ?? false, rate_limit_per_min: body.rate_limit_per_min, api_key_masked: body.api_key ? '****' + String(body.api_key).slice(-4) : null, health_status: 'unknown' }; platform.providers.push(p); return json(route, p, 201) }
    mm = path.match(/^\\/platform\\/ai-providers\\/([^/]+)\\/health-check$/)
    if (mm && m === 'POST') return json(route, { health_status: 'healthy', detail: 'reachable' })
    if (is('GET', /^\\/platform\\/models$/)) return json(route, platform.models.filter((x) => !url.searchParams.get('purpose') || x.purpose === url.searchParams.get('purpose')))
    if (is('POST', /^\\/platform\\/models$/)) { const pr = platform.providers.find((p) => p.provider_id === body.provider_id); const x = { model_id: nid('model'), model_name: body.model_name, model_version: body.model_version, provider: pr?.code, purpose: body.purpose, dimensions: body.dimensions, context_window: body.context_window, input_cost_per_1k: body.input_cost_per_1k, output_cost_per_1k: body.output_cost_per_1k, risk_class: body.risk_class, status: 'proposed', is_default: false }; platform.models.push(x); return json(route, x, 201) }
    mm = path.match(/^\\/platform\\/models\\/([^/]+)$/)
    if (mm && m === 'PUT') { const x = platform.models.find((q2) => q2.model_id === mm![1]); if (x) Object.assign(x, body); return json(route, x ?? {}) }
    if (path.startsWith('/platform/')) return json(route, [])`)

// 6. seed the catalogue with the built-in provider and the sample models used by the AI screenshots
rep("export interface State {", `platform.providers.push({ provider_id: 'prov-local', code: 'local', name: 'Built-in local models', provider_type: 'local', base_url: null, region: 'local', is_enabled: true, allow_tenant_override: false, rate_limit_per_min: null, api_key_masked: null, health_status: 'healthy' })
platform.providers.push({ provider_id: 'prov-ollama-chat', code: 'ollama-chat', name: 'Ollama (chat)', provider_type: 'ollama', base_url: 'http://host.docker.internal:11434/v1', region: 'local', is_enabled: true, allow_tenant_override: false, rate_limit_per_min: null, api_key_masked: null, health_status: 'healthy' })
platform.providers.push({ provider_id: 'prov-ollama-embed', code: 'ollama-embed', name: 'Ollama (embeddings)', provider_type: 'ollama', base_url: 'http://host.docker.internal:11434', region: 'local', is_enabled: true, allow_tenant_override: false, rate_limit_per_min: null, api_key_masked: null, health_status: 'healthy' })
platform.providers.push({ provider_id: 'prov-openai', code: 'openai', name: 'OpenAI', provider_type: 'openai', base_url: null, region: 'global', is_enabled: true, allow_tenant_override: false, rate_limit_per_min: 600, api_key_masked: '****abcd', health_status: 'healthy' })
MODELS.forEach((x, i) => platform.models.push({ model_id: 'model-' + i, ...x, model_version: '', context_window: x.purpose === 'chat' ? 8192 : null, risk_class: 'low', is_default: false }))

export interface State {`)
fs.writeFileSync(__dirname + '/fakeBackend.ts', s)
console.log('patched')
