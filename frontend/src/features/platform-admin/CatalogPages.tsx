import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'
import { platformApi } from '@/services/api/platformApi'
import { ApiError } from '@/services/api/errors'
import { Button } from '@/components/ui/button'
import { Card, Badge } from '@/components/ui/card'
import { Checkbox, Field, Input, Select, Textarea } from '@/components/ui/form'
import { Modal } from '@/components/ui/dialog'
import { EmptyState, InlineAlert, QueryState } from '@/components/feedback/states'
import { PageHeader, StatusBadge } from '@/components/common/display'
import { formatBytes, formatCost, formatNumber, humanize } from '@/utils/format'
import { n, s, useWrite, type Row } from '@/features/tenant-admin/common'

const MB = 1024 * 1024, GB = 1024 * MB

/* ---------- Plans ---------- */
function PlanEditor({ plan, open, onOpenChange }: { plan: Row | null; open: boolean; onOpenChange: (o: boolean) => void }) {
  const editing = !!plan
  const [v, setV] = useState<Record<string, string>>({
    code: s(plan?.code, ''), name: s(plan?.name, ''), description: s(plan?.description, ''), max_users: s(plan?.max_users, '10'), max_documents: s(plan?.max_documents, '1000'),
    storage_gb: plan ? String(Math.round(((n(plan.max_storage_bytes) ?? 0) / GB) * 100) / 100) : '10', doc_mb: plan ? String(Math.round((n(plan.max_document_size_bytes) ?? 0) / MB)) : '50',
    monthly_ai_tokens: s(plan?.monthly_ai_tokens, '1000000'), monthly_ai_requests: s(plan?.monthly_ai_requests, '10000'), max_concurrent_chats: s(plan?.max_concurrent_chats, '5'),
    max_ingestion_jobs: s(plan?.max_ingestion_jobs, '5'), max_collections: s(plan?.max_collections, '20'), monthly_price: s(plan?.monthly_price, '0'), features: JSON.stringify(plan?.features ?? {}, null, 2),
  })
  const [err, setErr] = useState<string | null>(null)
  const set = (k: string) => (e: { target: { value: string } }) => setV({ ...v, [k]: e.target.value })
  const num = ['max_users', 'max_documents', 'storage_gb', 'doc_mb', 'monthly_ai_tokens', 'monthly_ai_requests', 'max_concurrent_chats', 'max_ingestion_jobs', 'max_collections', 'monthly_price']
  const invalid = num.some((k) => v[k] === '' || Number(v[k]) < 0 || Number.isNaN(Number(v[k]))) || !/^[a-z][a-z0-9_-]{1,39}$/.test(v.code) || !v.name.trim()
  const save = useWrite(() => {
    let features: unknown = {}
    try { features = JSON.parse(v.features || '{}') } catch { throw new ApiError({ status: 422, code: 'validation_failed' }) }
    return platformApi.upsertPlan(v.code, { code: v.code, name: v.name, description: v.description || undefined, max_users: Number(v.max_users), max_documents: Number(v.max_documents),
      max_storage_bytes: Math.round(Number(v.storage_gb) * GB), max_document_size_bytes: Math.round(Number(v.doc_mb) * MB), monthly_ai_tokens: Number(v.monthly_ai_tokens), monthly_ai_requests: Number(v.monthly_ai_requests),
      max_concurrent_chats: Number(v.max_concurrent_chats), max_ingestion_jobs: Number(v.max_ingestion_jobs), max_collections: Number(v.max_collections), monthly_price: Number(v.monthly_price), features })
  }, { invalidate: [['platform']], success: 'Plan saved.', silentError: true, onSuccess: () => onOpenChange(false) })
  return (
    <Modal open={open} onOpenChange={onOpenChange} size="lg" title={editing ? `Edit plan ${s(plan?.code)}` : 'New plan'} description="Storage is entered in GB and document size in MB; they are converted to bytes."
      footer={<><Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button><Button loading={save.isPending} disabled={invalid} onClick={() => { setErr(null); save.mutate(undefined, { onError: (e) => setErr(e instanceof ApiError ? (e.code === 'validation_failed' && !e.serverMessage ? 'Features must be valid JSON.' : e.message) : 'Something went wrong.') }) }}>Save plan</Button></>}>
      <form className="grid gap-3 sm:grid-cols-2" onSubmit={(e) => e.preventDefault()}>
        {err && <InlineAlert tone="danger" className="sm:col-span-2">{err}</InlineAlert>}
        <Field label="Code" required error={v.code && !/^[a-z][a-z0-9_-]{1,39}$/.test(v.code) ? 'Lower-case letters, digits, - or _.' : undefined}>{(p) => <Input {...p} disabled={editing} value={v.code} onChange={set('code')} />}</Field>
        <Field label="Name" required>{(p) => <Input {...p} value={v.name} onChange={set('name')} />}</Field>
        <Field label="Description" className="sm:col-span-2">{(p) => <Input {...p} value={v.description} onChange={set('description')} />}</Field>
        {[['max_users', 'Users'], ['max_documents', 'Documents'], ['storage_gb', 'Storage (GB)'], ['doc_mb', 'Max document size (MB)'], ['monthly_ai_tokens', 'AI tokens / month'], ['monthly_ai_requests', 'AI requests / month'], ['max_concurrent_chats', 'Concurrent chats'], ['max_ingestion_jobs', 'Ingestion jobs'], ['max_collections', 'Collections'], ['monthly_price', 'Monthly price']].map(([k, l]) => (
          <Field key={k} label={l} error={v[k] !== '' && (Number(v[k]) < 0 || Number.isNaN(Number(v[k]))) ? 'Enter a number, 0 or more.' : undefined}>{(p) => <Input {...p} type="number" min={0} step={k === 'storage_gb' || k === 'monthly_price' ? '0.01' : '1'} value={v[k]} onChange={set(k)} />}</Field>))}
        <Field label="Features (JSON)" className="sm:col-span-2">{(p) => <Textarea {...p} className="font-mono text-xs" rows={4} value={v.features} onChange={set('features')} />}</Field>
      </form>
    </Modal>
  )
}

export function PlansPage() {
  const q = useQuery({ queryKey: ['platform', 'plans'], queryFn: platformApi.plans })
  const [edit, setEdit] = useState<{ plan: Row | null } | null>(null)
  return (
    <>
      <PageHeader title="Plans and features" actions={<Button onClick={() => setEdit({ plan: null })}>New plan</Button>} />
      <Card><QueryState query={q} isEmpty={(d) => d.length === 0} empty={<EmptyState title="No plans" />}>{(rows) => (
        <div className="table-wrap border-0"><table className="tbl"><caption className="sr-only">Plan comparison</caption>
          <thead><tr><th scope="col">Plan</th><th scope="col">Users</th><th scope="col">Documents</th><th scope="col">Storage</th><th scope="col">Max file</th><th scope="col">Tokens / month</th><th scope="col">Requests / month</th><th scope="col">Chats</th><th scope="col">Jobs</th><th scope="col">Collections</th><th scope="col">Price</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead>
          <tbody>{rows.map((p) => <tr key={s(p.code)}><td><span className="font-medium">{s(p.name)}</span><span className="block font-mono text-xs text-ink-muted">{s(p.code)}</span></td><td>{formatNumber(n(p.max_users))}</td><td>{formatNumber(n(p.max_documents))}</td><td>{formatBytes(n(p.max_storage_bytes))}</td><td>{formatBytes(n(p.max_document_size_bytes))}</td><td>{formatNumber(n(p.monthly_ai_tokens))}</td><td>{formatNumber(n(p.monthly_ai_requests))}</td><td>{s(p.max_concurrent_chats)}</td><td>{s(p.max_ingestion_jobs)}</td><td>{s(p.max_collections)}</td><td>{formatCost(n(p.monthly_price))}</td><td><Button size="sm" variant="secondary" onClick={() => setEdit({ plan: p })}>Edit</Button></td></tr>)}</tbody></table></div>)}</QueryState></Card>
      {edit && <PlanEditor plan={edit.plan} open onOpenChange={(o) => !o && setEdit(null)} />}
    </>
  )
}

/* ---------- AI providers ---------- */
const PTYPES = ['openai', 'azure_openai', 'ollama', 'huggingface', 'openai_compatible', 'local']

function ProviderEditor({ p, open, onOpenChange }: { p: Row | null; open: boolean; onOpenChange: (o: boolean) => void }) {
  const editing = !!p
  const [v, setV] = useState({ code: s(p?.code, ''), name: s(p?.name, ''), provider_type: s(p?.provider_type, 'openai'), base_url: s(p?.base_url, ''), api_version: s(p?.api_version, ''), region: s(p?.region, ''), rate: s(p?.rate_limit_per_min, ''), enabled: p ? Boolean(p.is_enabled) : true, override: Boolean(p?.allow_tenant_override), api_key: '' })
  const bad = !v.name.trim() || (!editing && !/^[a-z][a-z0-9_-]{1,39}$/.test(v.code)) || (!!v.base_url && !/^https?:\/\//.test(v.base_url))
  const save = useWrite(() => {
    const body = { name: v.name, base_url: v.base_url || undefined, api_version: v.api_version || undefined, region: v.region || undefined, is_enabled: v.enabled, allow_tenant_override: v.override, rate_limit_per_min: v.rate ? Number(v.rate) : undefined, ...(v.api_key ? { api_key: v.api_key } : {}) }
    return editing ? platformApi.updateProvider(s(p!.provider_id), body) : platformApi.createProvider({ ...body, code: v.code, provider_type: v.provider_type })
  }, { invalidate: [['platform']], success: 'Provider saved.', onSuccess: () => { setV((x) => ({ ...x, api_key: '' })); onOpenChange(false) } }) // the key field is cleared after saving
  return (
    <Modal open={open} onOpenChange={onOpenChange} size="lg" title={editing ? `Edit provider ${s(p?.code)}` : 'New AI provider'} footer={<><Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button><Button loading={save.isPending} disabled={bad} onClick={() => save.mutate(undefined)}>Save provider</Button></>}>
      <form className="grid gap-3 sm:grid-cols-2" onSubmit={(e) => e.preventDefault()} autoComplete="off">
        <Field label="Code" required>{(f) => <Input {...f} disabled={editing} value={v.code} onChange={(e) => setV({ ...v, code: e.target.value })} />}</Field>
        <Field label="Name" required>{(f) => <Input {...f} value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} />}</Field>
        <Field label="Type">{(f) => <Select {...f} disabled={editing} value={v.provider_type} onChange={(e) => setV({ ...v, provider_type: e.target.value })}>{PTYPES.map((t) => <option key={t} value={t}>{humanize(t)}</option>)}</Select>}</Field>
        <Field label="Base URL" error={v.base_url && !/^https?:\/\//.test(v.base_url) ? 'Must start with http:// or https://' : undefined}>{(f) => <Input {...f} value={v.base_url} onChange={(e) => setV({ ...v, base_url: e.target.value })} />}</Field>
        <Field label="API version">{(f) => <Input {...f} value={v.api_version} onChange={(e) => setV({ ...v, api_version: e.target.value })} />}</Field>
        <Field label="Region">{(f) => <Input {...f} value={v.region} onChange={(e) => setV({ ...v, region: e.target.value })} />}</Field>
        <Field label="Rate limit (per minute)">{(f) => <Input {...f} type="number" min={1} value={v.rate} onChange={(e) => setV({ ...v, rate: e.target.value })} />}</Field>
        <Field label="API key" hint={editing ? `Write-only. ${s(p?.api_key_masked, 'No key stored')}. Leave empty to keep the stored key.` : 'Write-only. It is never shown again.'}>
          {(f) => <Input {...f} type="password" autoComplete="new-password" placeholder={editing ? `${s(p?.api_key_masked, '')} (stored)` : ''} value={v.api_key} onChange={(e) => setV({ ...v, api_key: e.target.value })} />}</Field>
        <Checkbox label="Enabled" checked={v.enabled} onChange={(e) => setV({ ...v, enabled: e.target.checked })} />
        <Checkbox label="Tenants may override" checked={v.override} onChange={(e) => setV({ ...v, override: e.target.checked })} />
      </form>
    </Modal>
  )
}

export function ProvidersPage() {
  const q = useQuery({ queryKey: ['platform', 'providers'], queryFn: platformApi.providers })
  const [edit, setEdit] = useState<{ p: Row | null } | null>(null)
  const [health, setHealth] = useState<Record<string, Row>>({})
  const check = useWrite((id: string) => platformApi.healthCheck(id), { silentError: true })
  return (
    <>
      <PageHeader title="AI providers" description="API keys are write-only: they are never displayed, copied or logged." actions={<Button onClick={() => setEdit({ p: null })}>New provider</Button>} />
      <Card><QueryState query={q} isEmpty={(d) => d.length === 0} empty={<EmptyState title="No providers configured" />}>{(rows) => (
        <div className="table-wrap border-0"><table className="tbl"><caption className="sr-only">AI providers</caption>
          <thead><tr><th scope="col">Provider</th><th scope="col">Type</th><th scope="col">Base URL</th><th scope="col">Region</th><th scope="col">Key</th><th scope="col">Enabled</th><th scope="col">Override</th><th scope="col">Rate limit</th><th scope="col">Health</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead>
          <tbody>{rows.map((p) => { const id = s(p.provider_id); const h = health[id]; return (
            <tr key={id}><td><span className="font-medium">{s(p.name)}</span><span className="block font-mono text-xs text-ink-muted">{s(p.code)}</span></td><td>{humanize(s(p.provider_type, ''))}</td><td className="max-w-[180px] truncate">{s(p.base_url)}</td><td>{s(p.region)}</td>
              <td className="font-mono text-xs">{s(p.api_key_masked, 'none')}</td><td>{p.is_enabled ? 'Yes' : 'No'}</td><td>{p.allow_tenant_override ? 'Yes' : 'No'}</td><td>{s(p.rate_limit_per_min)}</td>
              <td><StatusBadge value={s(h?.health_status ?? p.health_status, 'unknown')} />{h?.detail ? <span className="block text-xs text-ink-muted">{typeof h.detail === 'string' ? h.detail : JSON.stringify(h.detail)}</span> : null}</td>
              <td><span className="flex gap-1"><Button size="sm" variant="secondary" loading={check.isPending && check.variables === id} onClick={() => check.mutate(id, { onSuccess: (r) => setHealth((x) => ({ ...x, [id]: r })), onError: (e) => toast.error(e instanceof ApiError ? e.message : 'Health check failed.') })}>Health check</Button><Button size="sm" variant="ghost" onClick={() => setEdit({ p })}>Edit</Button></span></td></tr>) })}</tbody></table></div>)}</QueryState></Card>
      {edit && <ProviderEditor p={edit.p} open onOpenChange={(o) => !o && setEdit(null)} />}
    </>
  )
}

/* ---------- Model catalogue ---------- */
const MSTATUS = ['proposed', 'approved', 'active', 'deprecated', 'retired']

export function ModelsPage() {
  const [purpose, setPurpose] = useState('')
  const q = useQuery({ queryKey: ['platform', 'models', purpose], queryFn: () => platformApi.models(purpose || undefined) })
  const providers = useQuery({ queryKey: ['platform', 'providers'], queryFn: platformApi.providers })
  const [creating, setCreating] = useState(false)
  const [v, setV] = useState({ provider_id: '', model_name: '', model_version: '', purpose: 'chat', dimensions: '', context_window: '', in_cost: '', out_cost: '', risk_class: 'low' })
  const create = useWrite(() => platformApi.createModel({ provider_id: v.provider_id, model_name: v.model_name, model_version: v.model_version || undefined, purpose: v.purpose, dimensions: v.dimensions ? Number(v.dimensions) : undefined, context_window: v.context_window ? Number(v.context_window) : undefined, input_cost_per_1k: v.in_cost ? Number(v.in_cost) : undefined, output_cost_per_1k: v.out_cost ? Number(v.out_cost) : undefined, risk_class: v.risk_class }),
    { invalidate: [['platform', 'models']], success: 'Model added as proposed.', onSuccess: () => setCreating(false) })
  const upd = useWrite((a: { id: string; body: Record<string, unknown> }) => platformApi.updateModel(a.id, a.body), { invalidate: [['platform', 'models']], success: 'Model updated.' })
  return (
    <>
      <PageHeader title="Model catalogue" description="Lifecycle: proposed → approved → active → deprecated → retired." actions={<><Select aria-label="Filter by purpose" value={purpose} onChange={(e) => setPurpose(e.target.value)} className="w-40"><option value="">All purposes</option>{['chat', 'embedding', 'rerank', 'rewrite', 'judge'].map((x) => <option key={x} value={x}>{humanize(x)}</option>)}</Select><Button onClick={() => setCreating(true)}>New model</Button></>} />
      <Card><QueryState query={q} isEmpty={(d) => d.length === 0} empty={<EmptyState title="No models" />}>{(rows) => (
        <div className="table-wrap border-0"><table className="tbl"><caption className="sr-only">Models</caption>
          <thead><tr><th scope="col">Model</th><th scope="col">Provider</th><th scope="col">Purpose</th><th scope="col">Dims</th><th scope="col">Context</th><th scope="col">Cost / 1k in · out</th><th scope="col">Risk</th><th scope="col">Status</th><th scope="col">Default</th></tr></thead>
          <tbody>{rows.map((m) => <tr key={s(m.model_id)}><td>{s(m.model_name)} <span className="text-xs text-ink-muted">{s(m.model_version, '')}</span></td><td>{s(m.provider ?? m.provider_code)}</td><td>{humanize(s(m.purpose, ''))}</td><td>{s(m.dimensions)}</td><td>{formatNumber(n(m.context_window))}</td><td>{formatCost(n(m.input_cost_per_1k))} · {formatCost(n(m.output_cost_per_1k))}</td><td>{humanize(s(m.risk_class, ''))}</td>
            <td><Select aria-label={`Status of ${s(m.model_name)}`} className="w-32 py-1" value={s(m.status)} onChange={(e) => upd.mutate({ id: s(m.model_id), body: { status: e.target.value } })}>{MSTATUS.map((x) => <option key={x} value={x}>{humanize(x)}</option>)}</Select></td>
            <td><input type="checkbox" className="accent-primary" aria-label={`Default model ${s(m.model_name)}`} checked={Boolean(m.is_default)} onChange={(e) => upd.mutate({ id: s(m.model_id), body: { is_default: e.target.checked } })} /></td></tr>)}</tbody></table></div>)}</QueryState></Card>
      <Modal open={creating} onOpenChange={setCreating} size="lg" title="New model" footer={<><Button variant="secondary" onClick={() => setCreating(false)}>Cancel</Button><Button loading={create.isPending} disabled={!v.provider_id || !v.model_name.trim()} onClick={() => create.mutate(undefined)}>Add model</Button></>}>
        <form className="grid gap-3 sm:grid-cols-2" onSubmit={(e) => e.preventDefault()}>
          <Field label="Provider" required>{(p) => <Select {...p} value={v.provider_id} onChange={(e) => setV({ ...v, provider_id: e.target.value })}><option value="">Select…</option>{providers.data?.map((x) => <option key={s(x.provider_id)} value={s(x.provider_id)}>{s(x.name)}</option>)}</Select>}</Field>
          <Field label="Model name" required>{(p) => <Input {...p} value={v.model_name} onChange={(e) => setV({ ...v, model_name: e.target.value })} />}</Field>
          <Field label="Version">{(p) => <Input {...p} value={v.model_version} onChange={(e) => setV({ ...v, model_version: e.target.value })} />}</Field>
          <Field label="Purpose">{(p) => <Select {...p} value={v.purpose} onChange={(e) => setV({ ...v, purpose: e.target.value })}>{['chat', 'embedding', 'rerank', 'rewrite', 'judge'].map((x) => <option key={x} value={x}>{humanize(x)}</option>)}</Select>}</Field>
          <Field label="Embedding dimensions">{(p) => <Input {...p} type="number" min={1} value={v.dimensions} onChange={(e) => setV({ ...v, dimensions: e.target.value })} />}</Field>
          <Field label="Context window">{(p) => <Input {...p} type="number" min={1} value={v.context_window} onChange={(e) => setV({ ...v, context_window: e.target.value })} />}</Field>
          <Field label="Input cost per 1k tokens">{(p) => <Input {...p} type="number" min={0} step="0.0001" value={v.in_cost} onChange={(e) => setV({ ...v, in_cost: e.target.value })} />}</Field>
          <Field label="Output cost per 1k tokens">{(p) => <Input {...p} type="number" min={0} step="0.0001" value={v.out_cost} onChange={(e) => setV({ ...v, out_cost: e.target.value })} />}</Field>
          <Field label="Risk class">{(p) => <Select {...p} value={v.risk_class} onChange={(e) => setV({ ...v, risk_class: e.target.value })}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option></Select>}</Field>
        </form>
      </Modal>
    </>
  )
}

/* ---------- Platform users ---------- */
const ROLES = ['platform_super_admin', 'platform_admin', 'platform_operator', 'platform_security', 'platform_support']

export function PlatformUsersPage() {
  const q = useQuery({ queryKey: ['platform', 'users'], queryFn: platformApi.users })
  const [edit, setEdit] = useState<{ u: Row | null } | null>(null)
  const [v, setV] = useState({ email: '', display_name: '', role: 'platform_support', password: '', status: 'active' })
  const open = (u: Row | null) => { setV({ email: s(u?.email, ''), display_name: s(u?.display_name, ''), role: s(u?.platform_role ?? u?.role, 'platform_support'), password: '', status: s(u?.status, 'active') }); setEdit({ u }) }
  const emailOk = /^\S+@\S+\.\S+$/.test(v.email)
  const save = useWrite(() => platformApi.setUser({ email: v.email, display_name: v.display_name || undefined, role: v.role, status: v.status, ...(v.password ? { password: v.password } : {}) }), { invalidate: [['platform', 'users']], success: 'Platform user saved.', onSuccess: () => setEdit(null) })
  return (
    <>
      <PageHeader title="Platform users" description="Staff who operate the platform. They have no access to tenant content." actions={<Button onClick={() => open(null)}>Add user</Button>} />
      <Card><QueryState query={q} isEmpty={(d) => d.length === 0}>{(rows) => (
        <div className="table-wrap border-0"><table className="tbl"><caption className="sr-only">Platform users</caption><thead><tr><th scope="col">Name</th><th scope="col">Email</th><th scope="col">Role</th><th scope="col">Status</th><th scope="col">MFA</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead>
          <tbody>{rows.map((u, i) => <tr key={i}><td>{s(u.display_name)}</td><td>{s(u.email)}</td><td>{humanize(s(u.platform_role ?? u.role, ''))}</td><td><StatusBadge value={s(u.status, '')} /></td><td>{u.mfa_enabled === undefined ? '–' : u.mfa_enabled ? <Badge tone="success">Enrolled</Badge> : <Badge tone="warning">Not enrolled</Badge>}</td><td><Button size="sm" variant="secondary" onClick={() => open(u)}>Edit</Button></td></tr>)}</tbody></table></div>)}</QueryState></Card>
      <Modal open={!!edit} onOpenChange={(o) => !o && setEdit(null)} size="sm" title={edit?.u ? 'Edit platform user' : 'Add platform user'} footer={<><Button variant="secondary" onClick={() => setEdit(null)}>Cancel</Button><Button loading={save.isPending} disabled={!emailOk} onClick={() => save.mutate(undefined)}>Save</Button></>}>
        <form className="space-y-3" onSubmit={(e) => e.preventDefault()}>
          <Field label="Email" required error={v.email && !emailOk ? 'Enter a valid email address.' : undefined}>{(p) => <Input {...p} type="email" disabled={!!edit?.u} value={v.email} onChange={(e) => setV({ ...v, email: e.target.value })} />}</Field>
          <Field label="Display name">{(p) => <Input {...p} value={v.display_name} onChange={(e) => setV({ ...v, display_name: e.target.value })} />}</Field>
          <Field label="Role">{(p) => <Select {...p} value={v.role} onChange={(e) => setV({ ...v, role: e.target.value })}>{ROLES.map((r) => <option key={r} value={r}>{humanize(r)}</option>)}</Select>}</Field>
          <Field label="Status">{(p) => <Select {...p} value={v.status} onChange={(e) => setV({ ...v, status: e.target.value })}><option value="active">Active</option><option value="disabled">Disabled</option></Select>}</Field>
          <Field label={edit?.u ? 'New password (optional)' : 'Initial password'}>{(p) => <Input {...p} type="password" autoComplete="new-password" value={v.password} onChange={(e) => setV({ ...v, password: e.target.value })} />}</Field>
        </form></Modal>
    </>
  )
}

/* ---------- Platform settings ---------- */
export function PlatformSettingsPage() {
  const q = useQuery({ queryKey: ['platform', 'settings'], queryFn: platformApi.settings })
  const [edit, setEdit] = useState<{ key: string; text: string } | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const save = useWrite(() => { let value: unknown; try { value = JSON.parse(edit!.text) } catch { throw new ApiError({ status: 422, code: 'validation_failed' }) } return platformApi.putSetting(edit!.key, value) },
    { invalidate: [['platform', 'settings']], success: 'Setting saved.', silentError: true, onSuccess: () => setEdit(null) })
  return (
    <>
      <PageHeader title="Platform settings" />
      <Card><QueryState query={q}>{(d) => (
        <div className="table-wrap border-0"><table className="tbl"><caption className="sr-only">Platform settings</caption><thead><tr><th scope="col">Key</th><th scope="col">Value</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead>
          <tbody>{Object.entries(d).map(([k, val]) => <tr key={k}><td className="font-mono text-xs">{k}</td><td className="max-w-md truncate font-mono text-xs">{JSON.stringify((val as Row)?.value ?? val)}</td><td><Button size="sm" variant="secondary" onClick={() => { setErr(null); setEdit({ key: k, text: JSON.stringify((val as Row)?.value ?? val, null, 2) }) }}>Edit</Button></td></tr>)}</tbody></table></div>)}</QueryState></Card>
      <Modal open={!!edit} onOpenChange={(o) => !o && setEdit(null)} title={`Edit ${edit?.key}`} footer={<><Button variant="secondary" onClick={() => setEdit(null)}>Cancel</Button><Button loading={save.isPending} onClick={() => { setErr(null); save.mutate(undefined, { onError: (e) => setErr(e instanceof ApiError && !e.serverMessage ? 'The value must be valid JSON.' : (e as Error).message) }) }}>Save</Button></>}>
        {err && <InlineAlert tone="danger" className="mb-2">{err}</InlineAlert>}
        <Field label="Value (JSON)">{(p) => <Textarea {...p} className="font-mono text-xs" rows={8} value={edit?.text ?? ''} onChange={(e) => setEdit(edit && { ...edit, text: e.target.value })} />}</Field>
      </Modal>
    </>
  )
}
