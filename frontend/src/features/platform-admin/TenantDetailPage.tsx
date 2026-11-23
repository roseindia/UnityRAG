import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { platformApi, type TenantAction } from '@/services/api/platformApi'
import { ApiError } from '@/services/api/errors'
import { usePermissions } from '@/hooks/usePermissions'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Field, Input, Select, Switch } from '@/components/ui/form'
import { Modal } from '@/components/ui/dialog'
import { Tabs } from '@/components/ui/tabs'
import { TrendChart } from '@/components/charts/charts'
import { DateRangePicker, defaultRange } from '@/components/forms/DateRangePicker'
import { accentAllowed, contrastOnWhite } from '@/utils/contrast'
import { ConfirmDialog } from '@/components/dialogs/ConfirmDialog'
import { InlineAlert, QueryState } from '@/components/feedback/states'
import { JsonViewer, KeyValueList, PageHeader, QuotaBar, StatusBadge } from '@/components/common/display'
import { formatBytes, formatCompact, formatDateTime, formatNumber, humanize } from '@/utils/format'
import { n, s, useWrite, type Row } from '@/features/tenant-admin/common'
import type { QuotaSnapshot } from '@/types/api'

const QF: Record<string, (v: number) => string> = { storage: formatBytes, storage_bytes: formatBytes, max_storage_bytes: formatBytes, ai_tokens: formatCompact, monthly_ai_tokens: formatCompact }
const QUOTA_FIELDS = ['max_users', 'max_documents', 'max_storage_bytes', 'max_document_size_bytes', 'monthly_ai_tokens', 'monthly_ai_requests', 'max_concurrent_chats', 'max_ingestion_jobs', 'max_collections']
const ACTIONS: { action: TenantAction; label: string; consequence: string; show: (st: string) => boolean }[] = [
  { action: 'activate', label: 'Activate', consequence: 'Users of this tenant regain access on their next request.', show: (st) => st !== 'active' && st !== 'archived' },
  { action: 'suspend', label: 'Suspend', consequence: 'Every user of this tenant is blocked on their next request. Data is kept.', show: (st) => st === 'active' || st === 'trial' },
  { action: 'deactivate', label: 'Deactivate', consequence: 'The tenant is switched off and users cannot sign in. Data is kept.', show: (st) => st !== 'deactivated' && st !== 'archived' },
  { action: 'archive', label: 'Archive', consequence: 'The tenant is archived and removed from normal operation. This is intended to be permanent.', show: (st) => st !== 'archived' },
]

function Quotas({ id, t }: { id: string; t: Row }) {
  const [edit, setEdit] = useState(false)
  const [vals, setVals] = useState<Record<string, string>>({})
  const [reason, setReason] = useState('')
  const save = useWrite(() => platformApi.setQuotas(id, { ...Object.fromEntries(Object.entries(vals).filter(([, v]) => v !== '').map(([k, v]) => [k, Number(v)])), reason }), { invalidate: [['platform']], success: 'Quotas updated.', onSuccess: () => { setEdit(false); setReason(''); setVals({}) } })
  const quotas = (t.quotas ?? []) as QuotaSnapshot[]
  return (
    <Card><CardHeader title="Quotas" description="Plan value, override and usage. Each change needs a reason." actions={<Button size="sm" onClick={() => setEdit(true)}>Edit quotas</Button>} />
      <CardBody className="grid gap-4 md:grid-cols-2">{quotas.length === 0 ? <p className="text-sm text-ink-muted">No quota information.</p> : quotas.map((q) => <QuotaBar key={q.metric} label={humanize(q.metric)} used={q.used} limit={q.limit} format={QF[q.metric] ?? formatNumber} />)}</CardBody>
      <Modal open={edit} onOpenChange={setEdit} size="lg" title="Edit quotas" description="Leave a field empty to keep its current value. Storage is in bytes." footer={<><Button variant="secondary" onClick={() => setEdit(false)}>Cancel</Button><Button loading={save.isPending} disabled={reason.trim().length < 5 || Object.values(vals).every((v) => v === '')} onClick={() => save.mutate(undefined)}>Save quotas</Button></>}>
        <div className="grid gap-3 sm:grid-cols-2">{QUOTA_FIELDS.map((f) => <Field key={f} label={humanize(f)} error={vals[f] && (Number(vals[f]) < 0 || !Number.isInteger(Number(vals[f]))) ? 'Enter a whole number, 0 or more.' : undefined}>{(p) => <Input {...p} type="number" min={0} value={vals[f] ?? ''} onChange={(e) => setVals({ ...vals, [f]: e.target.value })} />}</Field>)}
          <Field label="Reason for change" required className="sm:col-span-2" hint="At least 5 characters. Recorded in the audit log.">{(p) => <Input {...p} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field></div>
      </Modal>
    </Card>
  )
}

function Subscription({ id, t, canManage }: { id: string; t: Row; canManage: boolean }) {
  const plans = useQuery({ queryKey: ['platform', 'plans'], queryFn: platformApi.plans })
  const [plan, setPlan] = useState(s(t.plan_code, ''))
  const [apply, setApply] = useState(false)
  const m = useWrite(() => platformApi.changePlan(id, plan, apply), { invalidate: [['platform']], success: 'Plan changed.' })
  return (
    <Card><CardHeader title="Subscription" /><CardBody className="space-y-3">
      <KeyValueList items={[{ label: 'Current plan', value: s(t.plan_name ?? t.plan_code) }, { label: 'Subscription status', value: <StatusBadge value={s(t.subscription_status, '')} /> }, { label: 'Trial ends', value: formatDateTime(t.trial_ends_at as string) }]} />
      {canManage && <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); if (plan && plan !== t.plan_code) m.mutate(undefined) }}>
        <Field label="Change plan" className="w-64">{(p) => <Select {...p} value={plan} onChange={(e) => setPlan(e.target.value)}>{plans.data?.map((x) => <option key={s(x.code)} value={s(x.code)}>{s(x.name)}</option>)}</Select>}</Field>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="accent-primary" checked={apply} onChange={(e) => setApply(e.target.checked)} />Apply the plan's quotas</label>
        <Button type="submit" loading={m.isPending} disabled={!plan || plan === t.plan_code}>Change plan</Button></form>}
      {Array.isArray(t.subscriptions) && <div className="table-wrap"><table className="tbl"><caption className="sr-only">Subscription history</caption><thead><tr><th scope="col">Plan</th><th scope="col">Status</th><th scope="col">Starts</th></tr></thead><tbody>{(t.subscriptions as Row[]).map((x, i) => <tr key={i}><td>{s(x.plan_code)}</td><td><StatusBadge value={s(x.status, '')} /></td><td>{formatDateTime(x.starts_at as string)}</td></tr>)}</tbody></table></div>}
    </CardBody></Card>
  )
}

function Features({ id, t, canManage }: { id: string; t: Row; canManage: boolean }) {
  const features = (t.features ?? {}) as Record<string, boolean>
  const [flag, setFlag] = useState('')
  const set = useWrite((a: { flag: string; enabled: boolean }) => platformApi.setFeature(id, a.flag, a.enabled), { invalidate: [['platform']], success: 'Feature updated.' })
  return (
    <Card><CardHeader title="Features" description="Feature flags for this tenant, including support access (break_glass_support)." /><CardBody className="space-y-3">
      {Object.keys(features).length === 0 && <p className="text-sm text-ink-muted">No flags set.</p>}
      <ul className="grid gap-2 sm:grid-cols-2">{Object.entries(features).map(([k, v]) => <li key={k} className="flex items-center justify-between rounded-control border border-line px-3 py-2"><span className="font-mono text-xs">{k}</span><Switch label={`${k} enabled`} checked={v} disabled={!canManage || set.isPending} onChange={(e) => set.mutate({ flag: k, enabled: e })} /></li>)}</ul>
      {canManage && <form className="flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); if (/^[a-z][a-z0-9_]{2,60}$/.test(flag)) { set.mutate({ flag, enabled: true }); setFlag('') } }}>
        <Field label="Add a flag" hint="Lower-case with underscores" className="w-64">{(p) => <Input {...p} value={flag} onChange={(e) => setFlag(e.target.value)} />}</Field><Button type="submit" variant="secondary" disabled={!/^[a-z][a-z0-9_]{2,60}$/.test(flag)}>Enable flag</Button></form>}
    </CardBody></Card>
  )
}

function Admins({ id, canManage }: { id: string; canManage: boolean }) {
  const q = useQuery({ queryKey: ['platform', 'tenant', id, 'admins'], queryFn: () => platformApi.tenantAdmins(id) })
  const [open, setOpen] = useState(false)
  const [v, setV] = useState({ email: '', display_name: '', password: '' })
  const ok = /^\S+@\S+\.\S+$/.test(v.email) && v.display_name.trim() && v.password
  const add = useWrite(() => platformApi.addTenantAdmin(id, { email: v.email, display_name: v.display_name, password: v.password }), { invalidate: [['platform']], success: 'Administrator added.', onSuccess: () => { setOpen(false); setV({ email: '', display_name: '', password: '' }); void q.refetch() } })
  return (
    <Card><CardHeader title="Administrators" actions={canManage && <Button size="sm" onClick={() => setOpen(true)}>Add administrator</Button>} />
      <QueryState query={q} isEmpty={(d) => d.length === 0}>{(rows) => <ul>{rows.map((a, i) => <li key={i} className="flex items-center justify-between border-b border-line px-4 py-2 last:border-0"><span><span className="font-medium">{s(a.display_name)}</span><span className="block text-xs text-ink-muted">{s(a.email)}</span></span><StatusBadge value={s(a.status, '')} /></li>)}</ul>}</QueryState>
      <Modal open={open} onOpenChange={setOpen} size="sm" title="Add tenant administrator" footer={<><Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button><Button loading={add.isPending} disabled={!ok} onClick={() => add.mutate(undefined)}>Add</Button></>}>
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (ok) add.mutate(undefined) }}>
          <Field label="Email" required error={v.email && !/^\S+@\S+\.\S+$/.test(v.email) ? 'Enter a valid email address.' : undefined}>{(p) => <Input {...p} type="email" value={v.email} onChange={(e) => setV({ ...v, email: e.target.value })} />}</Field>
          <Field label="Display name" required>{(p) => <Input {...p} value={v.display_name} onChange={(e) => setV({ ...v, display_name: e.target.value })} />}</Field>
          <Field label="Initial password" required>{(p) => <Input {...p} type="password" autoComplete="new-password" value={v.password} onChange={(e) => setV({ ...v, password: e.target.value })} />}</Field>
        </form></Modal>
    </Card>
  )
}

function EditProfile({ id, t, open, onOpenChange }: { id: string; t: Row; open: boolean; onOpenChange: (o: boolean) => void }) {
  const b = (t.branding ?? {}) as Record<string, unknown>
  const [name, setName] = useState(s(t.name, ''))
  const [legal, setLegal] = useState(s(t.legal_entity, ''))
  const [region, setRegion] = useState(s(t.home_region, ''))
  const [accent, setAccent] = useState(s(b.accent_color, ''))
  const [logo, setLogo] = useState(s(b.logo_url, ''))
  const accentBad = !!accent && !accentAllowed(accent)
  const logoBad = !!logo && !/^https:\/\//.test(logo)
  const bad = !name.trim() || accentBad || logoBad
  const save = useWrite(() => platformApi.updateTenant(id, {
    name: name.trim(), legal_entity: legal || undefined, home_region: region || undefined,
    branding: { ...b, ...(accent ? { accent_color: accent } : {}), ...(logo ? { logo_url: logo } : {}) },
  }), { invalidate: [['platform']], success: 'Tenant profile saved.', onSuccess: () => onOpenChange(false) })
  return (
    <Modal open={open} onOpenChange={onOpenChange} title="Edit tenant profile" description="The tenant code cannot be changed."
      footer={<><Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button><Button loading={save.isPending} disabled={bad} onClick={() => save.mutate(undefined)}>Save</Button></>}>
      <form className="grid gap-3 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); if (!bad) save.mutate(undefined) }}>
        <Field label="Name" required error={name.trim() ? undefined : 'Enter a name.'} className="sm:col-span-2">{(p) => <Input {...p} value={name} onChange={(e) => setName(e.target.value)} />}</Field>
        <Field label="Legal entity">{(p) => <Input {...p} value={legal} onChange={(e) => setLegal(e.target.value)} />}</Field>
        <Field label="Home region">{(p) => <Input {...p} value={region} onChange={(e) => setRegion(e.target.value)} />}</Field>
        <Field label="Accent colour" hint="#RRGGBB. Applied only if it has at least 4.5:1 contrast on white." error={accentBad ? `Contrast is ${(contrastOnWhite(accent) ?? 0).toFixed(2)}:1 (or the format is wrong). The default colour stays in use.` : undefined}>
          {(p) => <Input {...p} value={accent} placeholder="#2B4C7E" onChange={(e) => setAccent(e.target.value)} />}</Field>
        <Field label="Logo URL" hint="https only" error={logoBad ? 'Must start with https://' : undefined}>{(p) => <Input {...p} value={logo} onChange={(e) => setLogo(e.target.value)} />}</Field>
      </form>
    </Modal>
  )
}

function UsageTab({ id }: { id: string }) {
  const [range, setRange] = useState(defaultRange)
  const q = useQuery({ queryKey: ['platform', 'tenant', id, 'usage', range], queryFn: () => platformApi.tenantUsage(id, range) })
  return (
    <div className="space-y-4">
      <DateRangePicker value={range} onChange={setRange} />
      <QueryState query={q}>{(d) => {
        const series = ((d.series ?? []) as Row[]).map((r) => ({ ...r, usage_date: String(r.usage_date) })) as Record<string, string | number | null>[]
        return (<>
          <TrendChart title="Daily usage" data={series} xKey="usage_date" series={[{ key: 'searches', label: 'Searches' }, { key: 'chats', label: 'Chats' }, { key: 'active_users', label: 'Active users' }]} />
          <Card><CardHeader title="Quota utilisation" /><CardBody className="grid gap-4 md:grid-cols-2">{((d.quotas ?? []) as QuotaSnapshot[]).map((q2) => <QuotaBar key={q2.metric} label={humanize(q2.metric)} used={q2.used} limit={q2.limit} format={QF[q2.metric] ?? formatNumber} />)}</CardBody></Card>
          <p className="text-xs text-ink-muted">{s(d.cost_note, 'Costs are estimates.')}</p>
        </>)
      }}</QueryState>
    </div>
  )
}

export default function TenantDetailPage() {
  const { id = '' } = useParams()
  const p = usePermissions()
  const [sp, setSp] = useSearchParams()
  const q = useQuery({ queryKey: ['platform', 'tenant', id], queryFn: () => platformApi.tenant(id), retry: false })
  const [act, setAct] = useState<(typeof ACTIONS)[number] | null>(null)
  const [editing, setEditing] = useState(false)
  const manage = p.platformCan('platform.tenants.manage')
  const audit = useQuery({ queryKey: ['platform', 'tenant', id, 'audit'], queryFn: () => platformApi.tenantAudit(id, { limit: 50 }), enabled: p.platformCan('platform.audit.view') && sp.get('tab') === 'audit' })
  return (
    <QueryState query={q}>{(t) => {
      const st = s(t.status)
      return (<>
        <PageHeader title={s(t.name)} description={`Code ${s(t.code)}`} actions={<><StatusBadge value={st} />{manage && <Button variant="secondary" onClick={() => setEditing(true)}>Edit profile</Button>}{manage && ACTIONS.filter((a) => a.show(st)).map((a) => <Button key={a.action} variant={a.action === 'activate' ? 'primary' : 'secondary'} className={a.action === 'archive' || a.action === 'suspend' ? 'border-danger text-danger' : ''} onClick={() => setAct(a)}>{a.label}</Button>)}</>} />
        <Tabs value={sp.get('tab') ?? 'overview'} onValueChange={(v) => setSp({ tab: v }, { replace: true })} tabs={[
          { value: 'overview', label: 'Overview', content: <Card><CardBody><KeyValueList items={[{ label: 'Legal entity', value: s(t.legal_entity) }, { label: 'Home region', value: s(t.home_region) }, { label: 'Plan', value: s(t.plan_name ?? t.plan_code) }, { label: 'Created', value: formatDateTime(t.created_at as string) },
            { label: 'Users', value: formatNumber(n(t.users_count)) }, { label: 'Documents', value: formatNumber(n(t.documents_count)) }, { label: 'Chunks', value: formatNumber(n(t.chunks_count)) }, { label: 'Storage', value: formatBytes(n(t.storage_bytes)) },
            { label: 'AI tokens this month', value: formatCompact(n(t.ai_tokens_month)) }, { label: 'Last activity', value: formatDateTime(t.last_activity_at as string) }]} /></CardBody></Card> },
          { value: 'usage', label: 'Usage', content: <UsageTab id={id} /> },
          { value: 'quotas', label: 'Quotas', content: <Quotas id={id} t={t} /> },
          { value: 'subscription', label: 'Subscription', content: <Subscription id={id} t={t} canManage={p.platformCan('platform.plans.manage')} /> },
          { value: 'features', label: 'Features', content: <Features id={id} t={t} canManage={p.platformCan('platform.quotas.manage')} /> },
          { value: 'admins', label: 'Administrators', content: <Admins id={id} canManage={manage} /> },
          { value: 'audit', label: 'Audit', hidden: !p.platformCan('platform.audit.view'), content: <Card><CardHeader title="Platform events for this tenant" /><QueryState query={audit} isEmpty={(d) => d.items.length === 0}>{(d) => <div className="table-wrap border-0"><table className="tbl"><caption className="sr-only">Tenant audit</caption><thead><tr><th scope="col">Time</th><th scope="col">Category</th><th scope="col">Action</th><th scope="col">Outcome</th></tr></thead><tbody>{d.items.map((e, i) => <tr key={i}><td>{formatDateTime(e.occurred_at as string)}</td><td>{s(e.category)}</td><td>{humanize(s(e.action, ''))}</td><td><StatusBadge value={s(e.outcome, '')} /></td></tr>)}</tbody></table></div>}</QueryState></Card> },
          { value: 'branding', label: 'Branding', content: <Card><CardHeader title="Branding" description="Applied to the tenant workspace only if its accent colour passes 4.5:1 contrast. Never changes the platform console." /><CardBody><JsonViewer value={t.branding ?? {}} /></CardBody></Card> },
        ]} />
        {editing && <EditProfile id={id} t={t} open onOpenChange={setEditing} />}
        <ConfirmDialog open={!!act} onOpenChange={(o) => !o && setAct(null)} level="strong" destructive={act?.action !== 'activate'} title={`${act?.label} tenant`} confirmLabel={`${act?.label} ${s(t.name)}`}
          description={<><p>You are about to <strong>{act?.label.toLowerCase()}</strong> <strong>{s(t.name)}</strong>.</p><InlineAlert tone="warning" className="mt-2">{act?.consequence} It takes effect on each user's next request.</InlineAlert></>}
          onConfirm={async (reason) => { try { await platformApi.tenantAction(id, act!.action, reason); void q.refetch() } catch (e) { throw e instanceof ApiError ? e : new Error('Failed') } }} />
      </>)
    }}</QueryState>
  )
}
