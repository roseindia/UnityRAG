import { zodResolver } from '@hookform/resolvers/zod'
import { useQuery } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { useMemo, useState } from 'react'
import { Controller, useForm } from 'react-hook-form'
import { Link, useNavigate } from 'react-router-dom'
import { adminApi } from '@/services/api/adminApi'
import { ApiError, fieldErrors } from '@/services/api/errors'
import { createUserSchema, type CreateUserForm } from '@/schemas/admin'
import { useUrlState } from '@/hooks/useUrlState'
import { useDebounced } from '@/hooks/useMisc'
import { Button } from '@/components/ui/button'
import { Checkbox, Field, Input, Select } from '@/components/ui/form'
import { Modal } from '@/components/ui/dialog'
import { DataTable } from '@/components/tables/DataTable'
import { InlineAlert } from '@/components/feedback/states'
import { PageHeader, StatusBadge } from '@/components/common/display'
import { Badge } from '@/components/ui/card'
import { LINES_OF_BUSINESS, type Row } from '@/types/api'
import { formatDateTime, humanize } from '@/utils/format'
import { arrOf, s, useTenantKey, useWrite } from './common'

const DEFAULTS = { q: '', status: '', department_id: '', sort: 'display_name', offset: '0', limit: '25' }

function CreateUser({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const key = useTenantKey()
  const nav = useNavigate()
  const deps = useQuery({ queryKey: key('admin', 'departments'), queryFn: adminApi.departments, enabled: open })
  const roles = useQuery({ queryKey: key('admin', 'roles'), queryFn: adminApi.roles, enabled: open, retry: false })
  const [formErr, setFormErr] = useState<string | null>(null)
  const [existing, setExisting] = useState(false)
  const { register, handleSubmit, control, watch, setError, reset, formState: { errors } } = useForm<CreateUserForm>({
    resolver: zodResolver(createUserSchema),
    defaultValues: { user_type: 'employee', auth_provider: 'oidc', clearance_rank: 0, lines_of_business: [], roles: [], email: '', display_name: '' },
  })
  const provider = watch('auth_provider')
  const create = useWrite((v: CreateUserForm) => {
    const j = (v.jurisdictions ?? '').split(',').map((x) => x.trim()).filter(Boolean)
    return adminApi.createUser({
      email: v.email, display_name: v.display_name, user_type: v.user_type, department_id: v.department_id || undefined,
      lines_of_business: v.lines_of_business, jurisdictions: j, clearance_rank: Number(v.clearance_rank), roles: v.roles,
      auth_provider: v.auth_provider, ...(v.auth_provider === 'local' ? { password: v.password } : { external_subject: v.external_subject }),
    })
  }, {
    invalidate: [['admin', 'users']], success: 'User created.', silentError: true,
    onSuccess: (r) => { onOpenChange(false); reset(); if (r.user_id) nav(`/admin/users/${r.user_id}`) },
  })
  const onSubmit = handleSubmit((v) => {
    setFormErr(null)
    create.mutate(v, {
      onSuccess: (r) => setExisting(Boolean((r as Row).existing_identity)),
      onError: (e) => {
        const fe = fieldErrors(e)
        Object.entries(fe).forEach(([k, m]) => { if (k in v) setError(k as keyof CreateUserForm, { message: m }) })
        setFormErr(e instanceof ApiError ? e.message : 'Something went wrong.')
      },
    })
  })
  return (
    <Modal open={open} onOpenChange={onOpenChange} size="lg" title="Create user" description="If the email already has an account on the platform, that person is added to this organisation."
      footer={<><Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button><Button loading={create.isPending} onClick={() => void onSubmit()}>Create user</Button></>}>
      <form onSubmit={onSubmit} noValidate className="grid gap-3 sm:grid-cols-2">
        {formErr && <InlineAlert tone="danger" className="sm:col-span-2">{formErr}</InlineAlert>}
        {existing && <InlineAlert tone="info" className="sm:col-span-2">This person already had an account and was added to your organisation.</InlineAlert>}
        <Field label="Email" required error={errors.email?.message}>{(p) => <Input {...p} type="email" autoComplete="off" {...register('email')} />}</Field>
        <Field label="Display name" required error={errors.display_name?.message}>{(p) => <Input {...p} {...register('display_name')} />}</Field>
        <Field label="User type">{(p) => <Select {...p} {...register('user_type')}><option value="employee">Employee</option><option value="broker">Broker (external)</option><option value="agent">Agent (external)</option><option value="service">Service</option></Select>}</Field>
        <Field label="Department">{(p) => <Select {...p} {...register('department_id')}><option value="">None</option>{deps.data?.map((d) => <option key={s(d.department_id)} value={s(d.department_id)}>{s(d.name)}</option>)}</Select>}</Field>
        <Field label="Jurisdictions" hint="Comma-separated codes">{(p) => <Input {...p} {...register('jurisdictions')} />}</Field>
        <Field label="Clearance rank" hint="0 public … 3 restricted" error={errors.clearance_rank?.message}>{(p) => <Input {...p} type="number" min={0} max={3} {...register('clearance_rank')} />}</Field>
        <fieldset className="sm:col-span-2"><legend className="mb-1 text-sm font-medium">Lines of business</legend>
          <Controller control={control} name="lines_of_business" render={({ field }) => (
            <div className="grid grid-cols-2 gap-1 sm:grid-cols-4">{LINES_OF_BUSINESS.map((l) => (
              <Checkbox key={l} label={humanize(l)} checked={(field.value ?? []).includes(l)} onChange={(e) => field.onChange(e.target.checked ? [...(field.value ?? []), l] : (field.value ?? []).filter((x) => x !== l))} />
            ))}</div>)} /></fieldset>
        <fieldset className="sm:col-span-2"><legend className="mb-1 text-sm font-medium">Roles</legend>
          {roles.isError && <p className="text-xs text-ink-muted">You can assign roles later (requires the roles permission).</p>}
          <Controller control={control} name="roles" render={({ field }) => (
            <div className="grid grid-cols-2 gap-1 sm:grid-cols-3">{roles.data?.map((r) => (
              <Checkbox key={s(r.code)} label={s(r.name)} checked={(field.value ?? []).includes(s(r.code))} onChange={(e) => field.onChange(e.target.checked ? [...(field.value ?? []), s(r.code)] : (field.value ?? []).filter((x) => x !== s(r.code)))} />
            ))}</div>)} /></fieldset>
        <Field label="Authentication" className="sm:col-span-2">{(p) => <Select {...p} {...register('auth_provider')}><option value="oidc">Single sign-on (identity provider)</option><option value="local">Local account with an initial password</option></Select>}</Field>
        {provider === 'oidc'
          ? <Field label="Identity provider subject" required error={errors.external_subject?.message} className="sm:col-span-2">{(p) => <Input {...p} autoComplete="off" {...register('external_subject')} />}</Field>
          : <Field label="Initial password" required error={errors.password?.message} className="sm:col-span-2" hint="Share it out of band. The user should change it after signing in.">{(p) => <Input {...p} type="password" autoComplete="new-password" {...register('password')} />}</Field>}
      </form>
    </Modal>
  )
}

export default function UsersPage() {
  const key = useTenantKey()
  const nav = useNavigate()
  const [st, set] = useUrlState(DEFAULTS)
  const q = useDebounced(st.q)
  const [creating, setCreating] = useState(false)
  const limit = Number(st.limit), offset = Number(st.offset)
  const deps = useQuery({ queryKey: key('admin', 'departments'), queryFn: adminApi.departments, staleTime: 5 * 60_000 })
  const users = useQuery({ queryKey: key('admin', 'users', { ...st, q }), queryFn: ({ signal }) => adminApi.users({ q, status: st.status, department_id: st.department_id, sort: st.sort, limit, offset }, signal), placeholderData: (p) => p })
  const dep = useMemo(() => new Map((deps.data ?? []).map((d) => [s(d.department_id), s(d.name)])), [deps.data])
  const columns = useMemo<ColumnDef<Row, unknown>[]>(() => [
    { header: 'Name', cell: ({ row: { original: u } }) => <Link className="font-medium text-primary hover:underline" to={`/admin/users/${s(u.user_id)}`}>{s(u.display_name)}</Link> },
    { header: 'Email', cell: ({ row: { original: u } }) => s(u.email) },
    { header: 'Type', cell: ({ row: { original: u } }) => humanize(s(u.user_type, '')) },
    { header: 'Department', cell: ({ row: { original: u } }) => dep.get(s(u.department_id)) ?? '–' },
    { header: 'Roles', cell: ({ row: { original: u } }) => <span className="flex flex-wrap gap-1">{arrOf(u.roles).map((r) => <Badge key={r} tone="info">{humanize(r)}</Badge>)}</span> },
    { header: 'Status', cell: ({ row: { original: u } }) => <StatusBadge value={s(u.status, '')} /> },
    { header: 'Last active', cell: ({ row: { original: u } }) => formatDateTime(u.last_active_at as string) },
  ], [dep])
  return (
    <>
      <PageHeader title="Users" description="People in your organisation." actions={<Button onClick={() => setCreating(true)}>New user</Button>} />
      <div className="mb-3 grid gap-2 sm:grid-cols-4">
        <Field label="Name or email">{(p) => <Input {...p} type="search" value={st.q} onChange={(e) => set({ q: e.target.value })} />}</Field>
        <Field label="Status">{(p) => <Select {...p} value={st.status} onChange={(e) => set({ status: e.target.value })}><option value="">All</option><option value="active">Active</option><option value="inactive">Inactive</option><option value="suspended">Suspended</option></Select>}</Field>
        <Field label="Department">{(p) => <Select {...p} value={st.department_id} onChange={(e) => set({ department_id: e.target.value })}><option value="">All</option>{deps.data?.map((d) => <option key={s(d.department_id)} value={s(d.department_id)}>{s(d.name)}</option>)}</Select>}</Field>
        <Field label="Sort by">{(p) => <Select {...p} value={st.sort} onChange={(e) => set({ sort: e.target.value })}><option value="display_name">Name</option><option value="email">Email</option><option value="created_at">Newest</option><option value="last_active_at">Last active</option></Select>}</Field>
      </div>
      <DataTable caption="Users" columns={columns} rows={users.data?.items} total={users.data?.total} limit={limit} offset={offset} loading={users.isFetching} error={users.error}
        onRetry={() => void users.refetch()} rowKey={(u) => s(u.user_id)} onRowClick={(u) => nav(`/admin/users/${s(u.user_id)}`)} onPage={(o, l) => set({ offset: String(o), limit: String(l) }, { keepOffset: true })} />
      <CreateUser open={creating} onOpenChange={setCreating} />
    </>
  )
}
