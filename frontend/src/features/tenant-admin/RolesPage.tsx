import { zodResolver } from '@hookform/resolvers/zod'
import { useQuery } from '@tanstack/react-query'
import { Lock } from 'lucide-react'
import { Fragment, useMemo, useState } from 'react'
import { Controller, useForm } from 'react-hook-form'
import { adminApi } from '@/services/api/adminApi'
import { ApiError, fieldErrors } from '@/services/api/errors'
import { roleSchema, type RoleForm } from '@/schemas/admin'
import { Button } from '@/components/ui/button'
import { Card, CardHeader } from '@/components/ui/card'
import { Checkbox, Field, Input, Textarea } from '@/components/ui/form'
import { Modal } from '@/components/ui/dialog'
import { ConfirmDialog } from '@/components/dialogs/ConfirmDialog'
import { InlineAlert, QueryState } from '@/components/feedback/states'
import { PageHeader } from '@/components/common/display'
import { humanize } from '@/utils/format'
import { arrOf, s, useTenantKey, useWrite, type Row } from './common'

function RoleEditor({ role, perms, roles, open, onOpenChange }: { role: Row | null; perms: Row[]; roles: Row[]; open: boolean; onOpenChange: (o: boolean) => void }) {
  const editing = !!role
  const [err, setErr] = useState<string | null>(null)
  const { register, handleSubmit, control, setError, formState: { errors } } = useForm<RoleForm>({
    resolver: zodResolver(roleSchema),
    values: { code: s(role?.code, ''), name: s(role?.name, ''), description: s(role?.description, ''), permissions: arrOf(role?.permissions), conflicts_with: arrOf(role?.conflicts_with) },
  })
  const save = useWrite((v: RoleForm) => editing ? adminApi.updateRole(s(role!.role_id), { name: v.name, description: v.description, permissions: v.permissions }) : adminApi.createRole(v),
    { invalidate: [['admin', 'roles']], success: 'Role saved.', silentError: true, onSuccess: () => onOpenChange(false) })
  const groups = useMemo(() => {
    const g = new Map<string, Row[]>()
    perms.forEach((p) => { const c = s(p.category, 'other'); g.set(c, [...(g.get(c) ?? []), p]) })
    return [...g.entries()]
  }, [perms])
  const submit = handleSubmit((v) => { setErr(null); save.mutate(v, { onError: (e) => { Object.entries(fieldErrors(e)).forEach(([k, m]) => { if (k in v) setError(k as keyof RoleForm, { message: m }) }); setErr(e instanceof ApiError ? (e.serverMessage ?? e.message) : 'Something went wrong.') } }) })
  return (
    <Modal open={open} onOpenChange={onOpenChange} size="lg" title={editing ? 'Edit custom role' : 'New custom role'}
      footer={<><Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button><Button loading={save.isPending} onClick={() => void submit()}>Save role</Button></>}>
      <form onSubmit={submit} noValidate className="space-y-3">
        {err && <InlineAlert tone="danger">{err}</InlineAlert>}
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Code" required error={errors.code?.message} hint="Cannot be changed later.">{(p) => <Input {...p} disabled={editing} {...register('code')} />}</Field>
          <Field label="Name" required error={errors.name?.message}>{(p) => <Input {...p} {...register('name')} />}</Field>
        </div>
        <Field label="Description">{(p) => <Textarea {...p} {...register('description')} />}</Field>
        <Controller control={control} name="permissions" render={({ field }) => (
          <fieldset><legend className="mb-1 text-sm font-medium">Permissions {errors.permissions && <span className="text-danger" role="alert"> – {errors.permissions.message}</span>}</legend>
            <div className="max-h-64 space-y-3 overflow-y-auto rounded-card border border-line p-3">{groups.map(([cat, list]) => (
              <div key={cat}><p className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-muted">{humanize(cat)}</p>
                <div className="grid gap-1 sm:grid-cols-2">{list.map((p) => { const code = s(p.permission_code); return <Checkbox key={code} label={<span className="font-mono text-xs">{code}</span>} checked={field.value.includes(code)} onChange={(e) => field.onChange(e.target.checked ? [...field.value, code] : field.value.filter((x) => x !== code))} /> })}</div></div>
            ))}</div></fieldset>)} />
        {!editing && <Controller control={control} name="conflicts_with" render={({ field }) => (
          <fieldset><legend className="mb-1 text-sm font-medium">Conflicts with (segregation of duties)</legend>
            <div className="flex flex-wrap gap-3">{roles.map((r) => <Checkbox key={s(r.code)} label={s(r.name)} checked={(field.value ?? []).includes(s(r.code))} onChange={(e) => field.onChange(e.target.checked ? [...(field.value ?? []), s(r.code)] : (field.value ?? []).filter((x) => x !== s(r.code)))} />)}</div></fieldset>)} />}
      </form>
    </Modal>
  )
}

export default function RolesPage() {
  const key = useTenantKey()
  const roles = useQuery({ queryKey: key('admin', 'roles'), queryFn: adminApi.roles })
  const perms = useQuery({ queryKey: key('admin', 'permissions'), queryFn: adminApi.permissions, staleTime: 5 * 60_000 })
  const [editor, setEditor] = useState<{ role: Row | null } | null>(null)
  const [del, setDel] = useState<Row | null>(null)
  const grouped = useMemo(() => {
    const g = new Map<string, Row[]>()
    ;(perms.data ?? []).forEach((p) => { const c = s(p.category, 'other'); g.set(c, [...(g.get(c) ?? []), p]) })
    return [...g.entries()]
  }, [perms.data])
  return (
    <>
      <PageHeader title="Roles and permissions" description="System roles are locked. Create a custom role to tailor access." actions={<Button onClick={() => setEditor({ role: null })}>New custom role</Button>} />
      <Card>
        <CardHeader title="Permission matrix" />
        <QueryState query={roles}>{(rs) => (
          <div className="table-wrap border-0 max-h-[70vh] overflow-y-auto">
            <table className="tbl"><caption className="sr-only">Permissions by role</caption>
              <thead><tr><th scope="col" className="sticky left-0 bg-canvas">Permission</th>{rs.map((r) => <th key={s(r.role_id)} scope="col" className="text-center">
                <span className="flex items-center justify-center gap-1">{Boolean(r.is_system) && <Lock className="h-3 w-3" aria-label="System role, read-only" />}{s(r.name)}</span>
                {!r.is_system && <span className="mt-1 flex justify-center gap-1 normal-case"><Button size="sm" variant="ghost" onClick={() => setEditor({ role: r })}>Edit</Button><Button size="sm" variant="ghost" className="text-danger" onClick={() => setDel(r)}>Delete</Button></span>}
              </th>)}</tr></thead>
              <tbody>{grouped.map(([cat, list]) => (<Fragment key={cat}>
                <tr><th scope="rowgroup" colSpan={rs.length + 1} className="bg-info-bg text-primary">{humanize(cat)}</th></tr>
                {list.map((p) => <tr key={s(p.permission_code)}><th scope="row" className="sticky left-0 whitespace-nowrap bg-surface font-mono text-xs normal-case text-ink">{s(p.permission_code)}</th>
                  {rs.map((r) => <td key={s(r.role_id)} className="text-center">{arrOf(r.permissions).includes(s(p.permission_code)) ? <span aria-label="Granted">✓</span> : <span className="text-ink-muted" aria-label="Not granted">–</span>}</td>)}</tr>)}
              </Fragment>))}</tbody></table>
          </div>)}</QueryState>
      </Card>
      {editor && perms.data && roles.data && <RoleEditor role={editor.role} perms={perms.data} roles={roles.data} open onOpenChange={(o) => !o && setEditor(null)} />}
      <ConfirmDialog open={!!del} onOpenChange={(o) => !o && setDel(null)} title="Delete role" confirmLabel="Delete role" description={<>Delete the custom role <strong>{s(del?.name)}</strong>? Users holding it lose its permissions.</>}
        onConfirm={async () => { await adminApi.deleteRole(s(del!.role_id)); void roles.refetch() }} />
    </>
  )
}
