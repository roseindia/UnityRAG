import { zodResolver } from '@hookform/resolvers/zod'
import { useQuery } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { useMemo, useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useNavigate } from 'react-router-dom'
import { z } from 'zod'
import { platformApi } from '@/services/api/platformApi'
import { ApiError, fieldErrors } from '@/services/api/errors'
import { usePermissions } from '@/hooks/usePermissions'
import { useUrlState } from '@/hooks/useUrlState'
import { useDebounced } from '@/hooks/useMisc'
import { Button } from '@/components/ui/button'
import { Card, CardBody } from '@/components/ui/card'
import { Field, Input, Select } from '@/components/ui/form'
import { DataTable } from '@/components/tables/DataTable'
import { InlineAlert } from '@/components/feedback/states'
import { KeyValueList, PageHeader, StatusBadge } from '@/components/common/display'
import { formatBytes, formatNumber, timeAgo } from '@/utils/format'
import { s, useWrite, type Row } from '@/features/tenant-admin/common'

const DEFAULTS = { q: '', status: '', plan: '', sort: 'name', offset: '0', limit: '25' }

export function TenantsPage() {
  const nav = useNavigate()
  const p = usePermissions()
  const [st, set] = useUrlState(DEFAULTS)
  const q = useDebounced(st.q)
  const limit = Number(st.limit), offset = Number(st.offset)
  const plans = useQuery({ queryKey: ['platform', 'plans'], queryFn: platformApi.plans, staleTime: 60_000 })
  const list = useQuery({ queryKey: ['platform', 'tenants', { ...st, q }], queryFn: () => platformApi.tenants({ q, status: st.status, plan: st.plan, sort: st.sort, limit, offset }), placeholderData: (x) => x })
  const columns = useMemo<ColumnDef<Row, unknown>[]>(() => [
    { header: 'Code', cell: ({ row: { original: t } }) => <span className="font-mono text-xs">{s(t.code)}</span> },
    { header: 'Name', cell: ({ row: { original: t } }) => <Link className="font-medium text-primary hover:underline" to={`/platform/tenants/${s(t.tenant_id)}`}>{s(t.name)}</Link> },
    { header: 'Status', cell: ({ row: { original: t } }) => <StatusBadge value={s(t.status, '')} /> },
    { header: 'Plan', cell: ({ row: { original: t } }) => s(t.plan_code) },
    { header: 'Users', cell: ({ row: { original: t } }) => formatNumber(t.users_count as number) },
    { header: 'Documents', cell: ({ row: { original: t } }) => formatNumber(t.documents_count as number) },
    { header: 'Storage', cell: ({ row: { original: t } }) => formatBytes(t.storage_bytes as number) },
    { header: 'Last activity', cell: ({ row: { original: t } }) => timeAgo(t.last_activity_at as string) },
  ], [])
  return (
    <>
      <PageHeader title="Tenants" description="Insurance organisations on the platform." actions={p.platformCan('platform.tenants.manage') && <Button asChild><Link to="/platform/tenants/new">New tenant</Link></Button>} />
      <div className="mb-3 grid gap-2 sm:grid-cols-4">
        <Field label="Name or code">{(pp) => <Input {...pp} type="search" value={st.q} onChange={(e) => set({ q: e.target.value })} />}</Field>
        <Field label="Status">{(pp) => <Select {...pp} value={st.status} onChange={(e) => set({ status: e.target.value })}><option value="">All</option>{['active', 'trial', 'suspended', 'deactivated', 'archived'].map((x) => <option key={x}>{x}</option>)}</Select>}</Field>
        <Field label="Plan">{(pp) => <Select {...pp} value={st.plan} onChange={(e) => set({ plan: e.target.value })}><option value="">All</option>{plans.data?.map((x) => <option key={s(x.code)} value={s(x.code)}>{s(x.name)}</option>)}</Select>}</Field>
        <Field label="Sort by">{(pp) => <Select {...pp} value={st.sort} onChange={(e) => set({ sort: e.target.value })}><option value="name">Name</option><option value="created_at">Newest</option><option value="status">Status</option><option value="documents">Documents</option><option value="storage">Storage</option><option value="ai_usage">AI usage</option><option value="last_activity">Last activity</option></Select>}</Field>
      </div>
      <DataTable caption="Tenants" columns={columns} rows={list.data?.items} total={list.data?.total} limit={limit} offset={offset} loading={list.isFetching} error={list.error} onRetry={() => void list.refetch()}
        rowKey={(t) => s(t.tenant_id)} onRowClick={(t) => nav(`/platform/tenants/${s(t.tenant_id)}`)} onPage={(o, l) => set({ offset: String(o), limit: String(l) }, { keepOffset: true })} />
    </>
  )
}

const wizard = z.object({
  code: z.string().regex(/^[a-z0-9][a-z0-9-]{1,39}$/, 'Lower-case letters, digits and hyphens, 2 to 40 characters, starting with a letter or digit.'),
  name: z.string().trim().min(2, 'Enter the tenant name.').max(200),
  legal_entity: z.string().max(200).optional(),
  home_region: z.string().max(60).optional(),
  plan_code: z.string().min(1, 'Choose a plan.'),
  admin_email: z.string().trim().email('Enter a valid email address.'),
  admin_name: z.string().trim().min(1, 'Enter the administrator name.'),
  admin_password: z.string().min(1, 'Enter an initial password.'),
})
type W = z.infer<typeof wizard>
const STEPS: { title: string; fields: (keyof W)[] }[] = [
  { title: 'Identity', fields: ['code', 'name', 'legal_entity', 'home_region'] }, { title: 'Plan', fields: ['plan_code'] },
  { title: 'First administrator', fields: ['admin_email', 'admin_name', 'admin_password'] }, { title: 'Review', fields: [] },
]

export function TenantNewPage() {
  const nav = useNavigate()
  const plans = useQuery({ queryKey: ['platform', 'plans'], queryFn: platformApi.plans })
  const [step, setStep] = useState(0)
  const [err, setErr] = useState<string | null>(null)
  const { register, getValues, setError, clearErrors, formState: { errors } } = useForm<W>({ resolver: zodResolver(wizard), defaultValues: { code: '', name: '', legal_entity: '', home_region: '', plan_code: '', admin_email: '', admin_name: '', admin_password: '' }, mode: 'onBlur' })
  const create = useWrite((v: W) => platformApi.createTenant({ code: v.code, name: v.name, legal_entity: v.legal_entity || undefined, home_region: v.home_region || undefined, plan_code: v.plan_code, admin_email: v.admin_email, admin_name: v.admin_name, admin_password: v.admin_password }),
    { success: 'Tenant created.', silentError: true, onSuccess: (r) => nav(`/platform/tenants/${s((r.tenant as Row | undefined)?.tenant_id ?? r.tenant_id)}`) })
  // Validate only this step's fields against their own schema (independent of the other steps' still-empty fields).
  const next = () => {
    const values = getValues()
    let ok = true
    for (const f of STEPS[step].fields) {
      const r = wizard.shape[f].safeParse(values[f])
      if (r.success) clearErrors(f)
      else { ok = false; setError(f, { type: 'validate', message: r.error.issues[0]?.message ?? 'Invalid value.' }) }
    }
    if (ok) setStep(step + 1)
  }
  const v = getValues()
  return (
    <>
      <PageHeader title="New tenant" description={`Step ${step + 1} of ${STEPS.length}: ${STEPS[step].title}. Earlier entries are kept when you go back.`} />
      <Card className="max-w-2xl"><CardBody>
        <ol className="mb-4 flex gap-2 text-xs" aria-label="Steps">{STEPS.map((x, i) => <li key={x.title} aria-current={i === step ? 'step' : undefined} className={i === step ? 'font-semibold text-primary' : i < step ? 'text-success' : 'text-ink-muted'}>{i + 1}. {x.title}</li>)}</ol>
        <form noValidate onSubmit={(e) => e.preventDefault()} className="space-y-3">
          {err && <InlineAlert tone="danger">{err}</InlineAlert>}
          <div className={step === 0 ? 'space-y-3' : 'hidden'}>
            <Field label="Tenant code" required error={errors.code?.message} hint="Used in URLs and cannot be changed.">{(p) => <Input {...p} autoComplete="off" {...register('code')} />}</Field>
            <Field label="Name" required error={errors.name?.message}>{(p) => <Input {...p} {...register('name')} />}</Field>
            <Field label="Legal entity" error={errors.legal_entity?.message}>{(p) => <Input {...p} {...register('legal_entity')} />}</Field>
            <Field label="Home region" error={errors.home_region?.message}>{(p) => <Input {...p} {...register('home_region')} />}</Field>
          </div>
          <div className={step === 1 ? '' : 'hidden'}>
            <Field label="Plan" required error={errors.plan_code?.message}>{(p) => <Select {...p} {...register('plan_code')}><option value="">Select a plan…</option>{plans.data?.map((x) => <option key={s(x.code)} value={s(x.code)}>{s(x.name)}</option>)}</Select>}</Field>
          </div>
          <div className={step === 2 ? 'space-y-3' : 'hidden'}>
            <Field label="Administrator email" required error={errors.admin_email?.message}>{(p) => <Input {...p} type="email" autoComplete="off" {...register('admin_email')} />}</Field>
            <Field label="Administrator name" required error={errors.admin_name?.message}>{(p) => <Input {...p} {...register('admin_name')} />}</Field>
            <Field label="Initial password" required error={errors.admin_password?.message} hint="Hand it over out of band.">{(p) => <Input {...p} type="password" autoComplete="new-password" {...register('admin_password')} />}</Field>
          </div>
          {step === 3 && <KeyValueList items={[{ label: 'Code', value: v.code }, { label: 'Name', value: v.name }, { label: 'Legal entity', value: v.legal_entity || '–' }, { label: 'Region', value: v.home_region || '–' }, { label: 'Plan', value: v.plan_code }, { label: 'Administrator', value: `${v.admin_name} <${v.admin_email}>` }]} />}
          <div className="flex justify-between pt-2">
            <Button variant="secondary" onClick={() => (step === 0 ? nav('/platform/tenants') : setStep(step - 1))}>{step === 0 ? 'Cancel' : 'Back'}</Button>
            {step < 3 ? <Button onClick={next}>Next</Button> : <Button loading={create.isPending} onClick={() => { setErr(null); create.mutate(getValues(), { onError: (e) => { const fe = fieldErrors(e); Object.entries(fe).forEach(([k, m]) => { if (k in wizard.shape) setError(k as keyof W, { message: m }) }); setErr(e instanceof ApiError ? (e.serverMessage ?? e.message) : 'Something went wrong.'); if (Object.keys(fe).some((k) => ['code', 'name'].includes(k))) setStep(0) } }) }}>Create tenant</Button>}
          </div>
        </form>
      </CardBody></Card>
      <p className="mt-2 text-xs text-ink-muted">The response includes the new tenant and its initial administrator.</p>
    </>
  )
}
