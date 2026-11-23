import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { adminApi } from '@/services/api/adminApi'
import { useDebounced } from '@/hooks/useMisc'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Field, Input, Select, Textarea } from '@/components/ui/form'
import { Modal } from '@/components/ui/dialog'
import { ConfirmDialog } from '@/components/dialogs/ConfirmDialog'
import { EmptyState, InlineAlert, QueryState } from '@/components/feedback/states'
import { JsonViewer, PageHeader, StatusBadge } from '@/components/common/display'
import { DateRangePicker, defaultRange } from '@/components/forms/DateRangePicker'
import { s, useTenantKey, useWrite, type Row } from './common'

function SimpleCreate({ title, open, onOpenChange, fields, onSubmit, pending }: {
  title: string; open: boolean; onOpenChange: (o: boolean) => void; pending: boolean
  fields: { name: string; label: string; required?: boolean; options?: { value: string; label: string }[]; area?: boolean; pattern?: RegExp; hint?: string }[]
  onSubmit: (v: Record<string, string>) => void
}) {
  const [v, setV] = useState<Record<string, string>>({})
  const errs: Record<string, string> = {}
  fields.forEach((f) => { if (f.required && !(v[f.name] ?? '').trim()) errs[f.name] = 'This field is required.'; else if (f.pattern && v[f.name] && !f.pattern.test(v[f.name])) errs[f.name] = f.hint ?? 'Invalid format.' })
  const bad = Object.keys(errs).length > 0
  const [touched, setTouched] = useState(false)
  return (
    <Modal open={open} onOpenChange={onOpenChange} title={title} size="sm" footer={<><Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button><Button loading={pending} onClick={() => { setTouched(true); if (!bad) onSubmit(v) }}>Create</Button></>}>
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); setTouched(true); if (!bad) onSubmit(v) }} noValidate>
        {fields.map((f) => (
          <Field key={f.name} label={f.label} required={f.required} error={touched ? errs[f.name] : undefined} hint={f.hint}>
            {(p) => f.options ? <Select {...p} value={v[f.name] ?? ''} onChange={(e) => setV({ ...v, [f.name]: e.target.value })}><option value="">Select…</option>{f.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</Select>
              : f.area ? <Textarea {...p} value={v[f.name] ?? ''} onChange={(e) => setV({ ...v, [f.name]: e.target.value })} /> : <Input {...p} value={v[f.name] ?? ''} onChange={(e) => setV({ ...v, [f.name]: e.target.value })} />}
          </Field>))}
      </form>
    </Modal>
  )
}

function EditDepartment({ d, onClose }: { d: Row | null; onClose: () => void }) {
  const [name, setName] = useState(s(d?.name, ''))
  const [description, setDescription] = useState(s(d?.description, ''))
  const [status, setStatus] = useState(s(d?.status, 'active'))
  const save = useWrite(() => adminApi.updateDepartment(s(d!.department_id), { name: name.trim(), description, status }),
    { invalidate: [['admin', 'departments']], success: 'Department updated.', onSuccess: onClose })
  return (
    <Modal open={!!d} onOpenChange={(o) => !o && onClose()} size="sm" title={`Edit department ${s(d?.code)}`}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={save.isPending} disabled={!name.trim()} onClick={() => save.mutate(undefined)}>Save</Button></>}>
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (name.trim()) save.mutate(undefined) }}>
        <Field label="Name" required error={name.trim() ? undefined : 'Enter a name.'}>{(p) => <Input {...p} value={name} onChange={(e) => setName(e.target.value)} />}</Field>
        <Field label="Description">{(p) => <Textarea {...p} value={description} onChange={(e) => setDescription(e.target.value)} />}</Field>
        <Field label="Status" hint="Inactive departments cannot be assigned to new users.">{(p) => <Select {...p} value={status} onChange={(e) => setStatus(e.target.value)}><option value="active">Active</option><option value="inactive">Inactive</option></Select>}</Field>
      </form>
    </Modal>
  )
}

function AddTeamMember({ team, onClose }: { team: Row | null; onClose: () => void }) {
  const key = useTenantKey()
  const [term, setTerm] = useState('')
  const dq = useDebounced(term)
  const found = useQuery({ queryKey: key('admin', 'users', 'team-typeahead', dq), queryFn: () => adminApi.users({ q: dq, limit: 8 }), enabled: !!team && dq.length >= 2 })
  const add = useWrite((uid: string) => adminApi.addTeamMember(s(team!.team_id), uid), { invalidate: [['admin', 'teams']], success: 'Member added.' })
  return (
    <Modal open={!!team} onOpenChange={(o) => { if (!o) { setTerm(''); onClose() } }} size="sm" title={`Add a member to ${s(team?.name)}`} footer={<Button variant="secondary" onClick={onClose}>Done</Button>}>
      <Field label="Find a user by name or email" hint="Type at least 2 characters.">{(p) => <Input {...p} type="search" value={term} onChange={(e) => setTerm(e.target.value)} />}</Field>
      <ul className="mt-2">{found.data?.items.map((u) => <li key={s(u.user_id)} className="flex items-center justify-between gap-2 py-1"><span>{s(u.display_name)} <span className="text-xs text-ink-muted">{s(u.email)}</span></span>
        <Button size="sm" variant="secondary" loading={add.isPending && add.variables === s(u.user_id)} onClick={() => add.mutate(s(u.user_id))}>Add</Button></li>)}</ul>
      {found.data && found.data.items.length === 0 && <p className="mt-2 text-sm text-ink-muted">No users match.</p>}
    </Modal>
  )
}

function Departments() {
  const key = useTenantKey()
  const q = useQuery({ queryKey: key('admin', 'departments'), queryFn: adminApi.departments })
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<Row | null>(null)
  const [usage, setUsage] = useState<Row | null>(null)
  const [range, setRange] = useState(defaultRange)
  const u = useQuery({ queryKey: key('admin', 'department-usage', usage?.department_id, range), queryFn: () => adminApi.departmentUsage(s(usage!.department_id), range), enabled: !!usage })
  const create = useWrite((v: Record<string, string>) => adminApi.createDepartment({ code: v.code, name: v.name, description: v.description || undefined, parent_department_id: v.parent || undefined }),
    { invalidate: [['admin', 'departments']], success: 'Department created.', onSuccess: () => setCreating(false) })
  return (
    <Card><CardHeader title="Departments" actions={<Button size="sm" onClick={() => setCreating(true)}>New department</Button>} />
      <QueryState query={q} isEmpty={(d) => d.length === 0} empty={<EmptyState title="No departments yet" action={<Button onClick={() => setCreating(true)}>Create a department</Button>} />}>
        {(rows) => <div className="table-wrap border-0"><table className="tbl"><caption className="sr-only">Departments</caption><thead><tr><th scope="col">Code</th><th scope="col">Name</th><th scope="col">Parent</th><th scope="col">Users</th><th scope="col">Teams</th><th scope="col">Status</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead>
          <tbody>{rows.map((d) => <tr key={s(d.department_id)}><td className="font-mono text-xs">{s(d.code)}</td><td>{s(d.name)}</td><td>{rows.find((x) => x.department_id === d.parent_department_id)?.name as string ?? '–'}</td><td>{s(d.user_count)}</td><td>{s(d.team_count)}</td><td><StatusBadge value={s(d.status, '')} /></td>
            <td><span className="flex gap-1"><Button size="sm" variant="ghost" onClick={() => setEditing(d)}>Edit</Button><Button size="sm" variant="ghost" onClick={() => setUsage(d)}>Usage</Button></span></td></tr>)}</tbody></table></div>}
      </QueryState>
      <SimpleCreate title="New department" open={creating} onOpenChange={setCreating} pending={create.isPending} onSubmit={(v) => create.mutate(v)} fields={[
        { name: 'code', label: 'Code', required: true, pattern: /^[A-Za-z0-9_-]{2,30}$/, hint: '2 to 30 letters, digits, - or _' }, { name: 'name', label: 'Name', required: true },
        { name: 'parent', label: 'Parent department', options: (q.data ?? []).map((d) => ({ value: s(d.department_id), label: s(d.name) })) }, { name: 'description', label: 'Description', area: true }]} />
      {editing && <EditDepartment key={s(editing.department_id)} d={editing} onClose={() => setEditing(null)} />}
      <Modal open={!!usage} onOpenChange={(o) => !o && setUsage(null)} variant="drawer" title={`Usage: ${s(usage?.name)}`}>
        <div className="space-y-3"><DateRangePicker value={range} onChange={setRange} /><QueryState query={u}>{(d) => <JsonViewer value={d} />}</QueryState></div>
      </Modal>
    </Card>
  )
}

function Teams() {
  const key = useTenantKey()
  const deps = useQuery({ queryKey: key('admin', 'departments'), queryFn: adminApi.departments })
  const q = useQuery({ queryKey: key('admin', 'teams'), queryFn: () => adminApi.teams() })
  const [creating, setCreating] = useState(false)
  const [addTo, setAddTo] = useState<Row | null>(null)
  const create = useWrite((v: Record<string, string>) => adminApi.createTeam({ department_id: v.department_id, name: v.name, description: v.description || undefined }),
    { invalidate: [['admin', 'teams']], success: 'Team created.', onSuccess: () => setCreating(false) })
  return (
    <Card className="mt-4"><CardHeader title="Teams" actions={<Button size="sm" onClick={() => setCreating(true)} disabled={!deps.data?.length}>New team</Button>} />
      <QueryState query={q} isEmpty={(d) => d.length === 0} empty={<EmptyState title="No teams yet" description={deps.data?.length ? undefined : 'Create a department first.'} />}>
        {(rows) => <div className="table-wrap border-0"><table className="tbl"><caption className="sr-only">Teams</caption><thead><tr><th scope="col">Name</th><th scope="col">Department</th><th scope="col">Members</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead>
          <tbody>{rows.map((t) => <tr key={s(t.team_id)}><td>{s(t.name)}</td><td>{s(deps.data?.find((d) => d.department_id === t.department_id)?.name)}</td><td>{s(t.members)}</td><td><Button size="sm" variant="ghost" onClick={() => setAddTo(t)}>Add member</Button></td></tr>)}</tbody></table></div>}
      </QueryState>
      <AddTeamMember team={addTo} onClose={() => setAddTo(null)} />
      <SimpleCreate title="New team" open={creating} onOpenChange={setCreating} pending={create.isPending} onSubmit={(v) => create.mutate(v)} fields={[
        { name: 'department_id', label: 'Department', required: true, options: (deps.data ?? []).map((d) => ({ value: s(d.department_id), label: s(d.name) })) }, { name: 'name', label: 'Name', required: true }, { name: 'description', label: 'Description', area: true }]} />
    </Card>
  )
}

export function OrganisationPage() {
  return (<><PageHeader title="Departments and teams" /><Departments /><Teams /></>)
}

export function GroupsPage() {
  const key = useTenantKey()
  const q = useQuery({ queryKey: key('admin', 'groups'), queryFn: adminApi.groups })
  const [creating, setCreating] = useState(false)
  const create = useWrite((v: Record<string, string>) => adminApi.createGroup({ name: v.name, description: v.description || undefined }), { invalidate: [['admin', 'groups']], success: 'Group created.', onSuccess: () => setCreating(false) })
  return (
    <>
      <PageHeader title="Groups" description="Document visibility can be granted to groups." actions={<Button onClick={() => setCreating(true)}>New group</Button>} />
      <Card><QueryState query={q} isEmpty={(d) => d.length === 0} empty={<EmptyState title="No groups yet" action={<Button onClick={() => setCreating(true)}>Create a group</Button>} />}>
        {(rows) => <div className="table-wrap border-0"><table className="tbl"><caption className="sr-only">Groups</caption><thead><tr><th scope="col">Name</th><th scope="col">Description</th><th scope="col">Members</th></tr></thead>
          <tbody>{rows.map((g) => <tr key={s(g.group_id)}><td><Link className="font-medium text-primary hover:underline" to={`/admin/groups/${s(g.group_id)}`}>{s(g.name)}</Link></td><td>{s(g.description)}</td><td>{s(g.members ?? g.member_count)}</td></tr>)}</tbody></table></div>}
      </QueryState></Card>
      <SimpleCreate title="New group" open={creating} onOpenChange={setCreating} pending={create.isPending} onSubmit={(v) => create.mutate(v)} fields={[{ name: 'name', label: 'Name', required: true }, { name: 'description', label: 'Description', area: true }]} />
    </>
  )
}

export function GroupDetailPage() {
  const { id = '' } = useParams()
  const key = useTenantKey()
  const groups = useQuery({ queryKey: key('admin', 'groups'), queryFn: adminApi.groups })
  const members = useQuery({ queryKey: key('admin', 'group', id, 'members'), queryFn: () => adminApi.groupMembers(id) })
  const [term, setTerm] = useState('')
  const dq = useDebounced(term)
  const found = useQuery({ queryKey: key('admin', 'users', 'typeahead', dq), queryFn: () => adminApi.users({ q: dq, limit: 8 }), enabled: dq.length >= 2 })
  const [remove, setRemove] = useState<Row | null>(null)
  const add = useWrite((uid: string) => adminApi.addGroupMember(id, uid), { invalidate: [['admin', 'group', id, 'members'], ['admin', 'groups']], success: 'Member added.' })
  const g = groups.data?.find((x) => s(x.group_id) === id)
  return (
    <>
      <PageHeader title={s(g?.name, 'Group')} description={s(g?.description, '')} />
      <InlineAlert className="mb-3">Access to documents shared with this group updates within seconds of a membership change.</InlineAlert>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card><CardHeader title="Members" /><QueryState query={members} isEmpty={(d) => d.length === 0} empty={<EmptyState title="No members yet" />}>
          {(rows) => <ul>{rows.map((m) => <li key={s(m.user_id)} className="flex items-center justify-between gap-2 border-b border-line px-4 py-2 last:border-0"><span><span className="font-medium">{s(m.display_name)}</span><span className="block text-xs text-ink-muted">{s(m.email)}</span></span><Button size="sm" variant="ghost" className="text-danger" onClick={() => setRemove(m)}>Remove</Button></li>)}</ul>}</QueryState></Card>
        <Card><CardHeader title="Add a member" /><CardBody className="space-y-2">
          <Field label="Find a user by name or email" hint="Type at least 2 characters.">{(p) => <Input {...p} type="search" value={term} onChange={(e) => setTerm(e.target.value)} />}</Field>
          <ul>{found.data?.items.map((u) => <li key={s(u.user_id)} className="flex items-center justify-between gap-2 py-1"><span>{s(u.display_name)} <span className="text-xs text-ink-muted">{s(u.email)}</span></span>
            <Button size="sm" variant="secondary" loading={add.isPending && add.variables === s(u.user_id)} disabled={members.data?.some((m) => m.user_id === u.user_id)} onClick={() => add.mutate(s(u.user_id))}>Add</Button></li>)}</ul>
        </CardBody></Card>
      </div>
      <ConfirmDialog open={!!remove} onOpenChange={(o) => !o && setRemove(null)} title="Remove member" confirmLabel="Remove member" description={<>Remove <strong>{s(remove?.display_name)}</strong> from this group? They lose access to documents shared with it.</>}
        onConfirm={async () => { await adminApi.removeGroupMember(id, s(remove!.user_id)); void members.refetch() }} />
    </>
  )
}
