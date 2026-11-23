import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { adminApi } from '@/services/api/adminApi'
import { ApiError } from '@/services/api/errors'
import { usePermissions } from '@/hooks/usePermissions'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader, Badge } from '@/components/ui/card'
import { Tabs } from '@/components/ui/tabs'
import { Field, Input, Select } from '@/components/ui/form'
import { Modal } from '@/components/ui/dialog'
import { ConfirmDialog } from '@/components/dialogs/ConfirmDialog'
import { CopyButton } from '@/components/common/CopyButton'
import { InlineAlert, QueryState } from '@/components/feedback/states'
import { JsonViewer, KeyValueList, PageHeader, StatusBadge } from '@/components/common/display'
import { formatDateTime, humanize } from '@/utils/format'
import { arrOf, s, useTenantKey, useWrite, type Row } from './common'

export default function UserDetailPage() {
  const { id = '' } = useParams()
  const key = useTenantKey()
  const p = usePermissions()
  const [sp, setSp] = useSearchParams()
  const tab = sp.get('tab') ?? 'profile'
  const user = useQuery({ queryKey: key('admin', 'user', id), queryFn: () => adminApi.user(id), retry: false })
  const roles = useQuery({ queryKey: key('admin', 'roles'), queryFn: adminApi.roles, enabled: p.can('admin.roles.manage') })
  const eff = useQuery({ queryKey: key('admin', 'effective', id), queryFn: () => adminApi.effectivePermissions(id), enabled: p.can('admin.roles.manage') && tab === 'permissions' })
  const logins = useQuery({ queryKey: key('admin', 'logins', id), queryFn: () => adminApi.userLogins(id), enabled: tab === 'sessions' })
  const activity = useQuery({ queryKey: key('admin', 'activity', id), queryFn: () => adminApi.userActivity(id), enabled: tab === 'activity' })
  const groups = useQuery({ queryKey: key('admin', 'groups'), queryFn: adminApi.groups, enabled: p.can('admin.groups.manage') && tab === 'groups' })
  const [roleId, setRoleId] = useState('')
  const [roleErr, setRoleErr] = useState<string | null>(null)
  const [deact, setDeact] = useState(false)
  const [revoke, setRevoke] = useState(false)
  const [reset, setReset] = useState<Row | null>(null)
  const inv = [['admin', 'user', id], ['admin', 'users'], ['admin', 'effective', id]]
  const assign = useWrite((rid: string) => adminApi.assignRole(id, rid), { invalidate: inv, success: 'Role assigned.', silentError: true })
  const unassign = useWrite((rid: string) => adminApi.unassignRole(id, rid), { invalidate: inv, success: 'Role removed.' })
  const activate = useWrite(() => adminApi.activateUser(id), { invalidate: inv, success: 'User activated.' })
  const resetPw = useWrite(() => adminApi.passwordReset(id), { onSuccess: (r) => setReset(r) })
  const [edit, setEdit] = useState(false)

  return (
    <QueryState query={user}>
      {(u) => {
        const active = s(u.status) === 'active'
        const mine = new Set(arrOf(u.roles))
        const roleList = roles.data ?? []
        return (
          <>
            <PageHeader title={s(u.display_name)} description={s(u.email)} actions={<>
              {active ? <Button variant="secondary" onClick={() => setDeact(true)}>Deactivate</Button> : <Button variant="secondary" loading={activate.isPending} onClick={() => activate.mutate(undefined)}>Activate</Button>}
              <Button variant="secondary" onClick={() => setRevoke(true)}>Revoke sessions</Button>
              <Button variant="secondary" loading={resetPw.isPending} onClick={() => resetPw.mutate(undefined)}>Reset password</Button>
              <Button onClick={() => setEdit(true)}>Edit</Button>
            </>} />
            <InlineAlert className="mb-3">Changes to attributes and roles take effect on the user's next request.</InlineAlert>
            <Tabs value={tab} onValueChange={(v) => setSp({ tab: v }, { replace: true })} tabs={[
              { value: 'profile', label: 'Profile', content: (
                <Card><CardBody><KeyValueList items={[
                  { label: 'Status', value: <StatusBadge value={s(u.status, '')} /> }, { label: 'User type', value: humanize(s(u.user_type, '')) },
                  { label: 'Business unit', value: s(u.business_unit) }, { label: 'Country', value: s(u.country) },
                  { label: 'Lines of business', value: arrOf(u.lines_of_business).map(humanize).join(', ') || '–' }, { label: 'Jurisdictions', value: arrOf(u.jurisdictions).join(', ') || '–' },
                  { label: 'Clearance rank', value: s(u.clearance_rank) }, { label: 'Last active', value: formatDateTime(u.last_active_at as string) },
                ]} /></CardBody></Card>) },
              { value: 'roles', label: 'Roles', hidden: !p.can('admin.roles.manage'), content: (
                <Card><CardHeader title="Assigned roles" /><CardBody className="space-y-3">
                  <ul className="flex flex-wrap gap-2">{arrOf(u.roles).map((code) => {
                    const r = roleList.find((x) => s(x.code) === code)
                    return <li key={code} className="flex items-center gap-1 rounded-pill bg-info-bg px-2 py-1 text-sm">{humanize(code)}
                      {r && <button type="button" className="rounded-full px-1 text-danger hover:bg-danger-bg" aria-label={`Remove role ${humanize(code)}`} onClick={() => unassign.mutate(s(r.role_id))}>×</button>}</li>
                  })}{arrOf(u.roles).length === 0 && <li className="text-sm text-ink-muted">No roles assigned.</li>}</ul>
                  <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); setRoleErr(null); assign.mutate(roleId, { onError: (er) => setRoleErr(er instanceof ApiError ? (er.serverMessage ?? er.message) : 'Could not assign the role.') }) }}>
                    <Field label="Add a role" className="w-64">{(pr) => <Select {...pr} value={roleId} onChange={(e) => setRoleId(e.target.value)}><option value="">Select…</option>{roleList.filter((r) => !mine.has(s(r.code))).map((r) => <option key={s(r.role_id)} value={s(r.role_id)}>{s(r.name)}</option>)}</Select>}</Field>
                    <Button type="submit" disabled={!roleId} loading={assign.isPending}>Assign</Button>
                  </form>
                  {roleErr && <InlineAlert tone="danger" title="Role not assigned">{roleErr}</InlineAlert>}
                  <p className="text-xs text-ink-muted">Administrator and auditor roles are mutually exclusive (segregation of duties).</p>
                </CardBody></Card>) },
              { value: 'groups', label: 'Groups', hidden: !p.can('admin.groups.manage'), content: (
                <Card><CardBody><QueryState query={groups}>{(g) => <ul className="flex flex-wrap gap-2">{g.filter((x) => arrOf(u.group_ids).includes(s(x.group_id))).map((x) => <li key={s(x.group_id)}><Badge tone="info">{s(x.name)}</Badge></li>)}
                  {arrOf(u.group_ids).length === 0 && <li className="text-sm text-ink-muted">Not a member of any group. Manage members under Groups.</li>}</ul>}</QueryState></CardBody></Card>) },
              { value: 'permissions', label: 'Effective permissions', hidden: !p.can('admin.roles.manage'), content: (
                <Card><CardHeader title="Effective permissions" description="Union of the permissions from the user's current roles." />
                  <QueryState query={eff}>{(e) => <CardBody><ul className="grid gap-1 sm:grid-cols-2 lg:grid-cols-3">{arrOf(e.permissions).map((x) => <li key={x} className="font-mono text-xs">{x}</li>)}</ul></CardBody>}</QueryState></Card>) },
              { value: 'sessions', label: 'Sessions & logins', content: (
                <Card><CardHeader title="Login history" /><QueryState query={logins} isEmpty={(d) => d.length === 0}>{(rows) =>
                  <div className="table-wrap border-0"><table className="tbl"><caption className="sr-only">Login history</caption><thead><tr><th scope="col">When</th><th scope="col">Outcome</th><th scope="col">IP</th><th scope="col">Method</th></tr></thead>
                    <tbody>{rows.map((r, i) => <tr key={i}><td>{formatDateTime((r.occurred_at ?? r.created_at) as string)}</td><td><StatusBadge value={s(r.outcome ?? r.status, '')} /></td><td className="font-mono text-xs">{s(r.ip_address ?? r.ip)}</td><td>{s(r.method ?? r.auth_method)}</td></tr>)}</tbody></table></div>}</QueryState></Card>) },
              { value: 'activity', label: 'Activity', content: (
                <Card><CardHeader title="Daily aggregates and recent audit events" /><QueryState query={activity}>{(a) => <CardBody><JsonViewer value={a} /></CardBody>}</QueryState></Card>) },
            ]} />
            <ConfirmDialog open={deact} onOpenChange={setDeact} level="reason" minReason={5} title="Deactivate user" confirmLabel="Deactivate user"
              description={<>Deactivate <strong>{s(u.display_name)}</strong>? Active sessions will be revoked immediately.</>}
              onConfirm={async () => { await adminApi.deactivateUser(id); await Promise.resolve(); inv.forEach(() => undefined); activate.reset(); void user.refetch() }} />
            <ConfirmDialog open={revoke} onOpenChange={setRevoke} title="Revoke sessions" confirmLabel="Revoke sessions" description={<>Sign <strong>{s(u.display_name)}</strong> out on every device?</>}
              onConfirm={async () => { await adminApi.revokeSessions(id) }} />
            <Modal open={!!reset} onOpenChange={(o) => !o && setReset(null)} title="Password reset token" size="sm" dismissible={false}
              description="Shown once. Hand it over out of band. It is single-use and is never displayed again."
              footer={<Button onClick={() => setReset(null)}>I have copied it</Button>}>
              <div className="flex items-center gap-2 rounded-control bg-canvas p-3 font-mono text-sm break-all">{s(reset?.token ?? reset?.reset_token)}<CopyButton text={s(reset?.token ?? reset?.reset_token, '')} label="Copy token" /></div>
              {reset?.expires_at ? <p className="mt-2 text-xs text-ink-muted">Expires {formatDateTime(reset.expires_at as string)}.</p> : null}
            </Modal>
            <EditUser u={u} open={edit} onOpenChange={setEdit} id={id} inv={inv} />
          </>
        )
      }}
    </QueryState>
  )
}

function EditUser({ u, open, onOpenChange, id, inv }: { u: Row; open: boolean; onOpenChange: (o: boolean) => void; id: string; inv: unknown[][] }) {
  const [name, setName] = useState(s(u.display_name, ''))
  const [clear, setClear] = useState(String(u.clearance_rank ?? 0))
  const [juris, setJuris] = useState(arrOf(u.jurisdictions).join(', '))
  const bad = Number(clear) < 0 || Number(clear) > 3 || !name.trim()
  const m = useWrite(() => adminApi.updateUser(id, { display_name: name.trim(), clearance_rank: Number(clear), jurisdictions: juris.split(',').map((x) => x.trim()).filter(Boolean) }),
    { invalidate: inv, success: 'User updated.', onSuccess: () => onOpenChange(false) })
  return (
    <Modal open={open} onOpenChange={onOpenChange} title="Edit user" size="sm" footer={<><Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button><Button loading={m.isPending} disabled={bad} onClick={() => m.mutate(undefined)}>Save</Button></>}>
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (!bad) m.mutate(undefined) }}>
        <Field label="Display name" required>{(p) => <Input {...p} value={name} onChange={(e) => setName(e.target.value)} />}</Field>
        <Field label="Clearance rank" hint="0 public … 3 restricted" error={Number(clear) < 0 || Number(clear) > 3 ? 'Between 0 and 3.' : undefined}>{(p) => <Input {...p} type="number" value={clear} onChange={(e) => setClear(e.target.value)} />}</Field>
        <Field label="Jurisdictions" hint="Comma-separated codes">{(p) => <Input {...p} value={juris} onChange={(e) => setJuris(e.target.value)} />}</Field>
      </form>
    </Modal>
  )
}
