import { useQuery } from '@tanstack/react-query'
import { Trash2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { adminApi } from '@/services/api/adminApi'
import { ApiError } from '@/services/api/errors'
import { useAuth } from '@/contexts/AuthContext'
import { useDebounced } from '@/hooks/useMisc'
import { Button } from '@/components/ui/button'
import { Input, Select } from '@/components/ui/form'
import { ConfirmDialog } from '@/components/dialogs/ConfirmDialog'
import { InlineAlert } from '@/components/feedback/states'
import { Badge } from '@/components/ui/card'
import type { Row } from '@/types/api'

export interface Rule { principal_type: string; principal_id?: string | null; effect: 'allow' | 'deny'; permission?: string; origin?: string }
const TYPES = ['user', 'group', 'role', 'department', 'team', 'everyone']
const sig = (r: Rule) => `${r.principal_type}|${r.principal_id ?? ''}|${r.effect}|${r.permission ?? ''}`

/**
 * Replaces the whole rule set (PUT). Shows a diff and asks for confirmation first. Deny always wins.
 * `withPermission` is true for collections (read / write / manage); documents only carry allow / deny.
 */
export function AccessRuleEditor({ initial, withPermission, onSave }: { initial: Rule[]; withPermission?: boolean; onSave: (rules: Rule[]) => Promise<unknown> }) {
  const { profile } = useAuth()
  const editable = initial.filter((r) => !r.origin || r.origin === 'platform_policy')
  const locked = initial.filter((r) => r.origin && r.origin !== 'platform_policy')
  const [rules, setRules] = useState<Rule[]>(editable)
  const [confirm, setConfirm] = useState(false)
  const [term, setTerm] = useState('')
  const dq = useDebounced(term)
  const k = (x: string) => [profile?.tenant_id, 'admin', x]
  const users = useQuery({ queryKey: [...k('users'), 'principal', dq], queryFn: () => adminApi.users({ q: dq, limit: 6 }), enabled: dq.length >= 2 })
  const groups = useQuery({ queryKey: k('groups'), queryFn: adminApi.groups, staleTime: 60_000 })
  const roles = useQuery({ queryKey: k('roles'), queryFn: adminApi.roles, staleTime: 60_000, retry: false })
  const deps = useQuery({ queryKey: k('departments'), queryFn: adminApi.departments, staleTime: 60_000 })
  const teams = useQuery({ queryKey: k('teams'), queryFn: () => adminApi.teams(), staleTime: 60_000 })

  const options = (type: string): { id: string; label: string }[] => {
    const pick = (rows: Row[] | undefined, idf: string, lf: string) => (rows ?? []).map((r) => ({ id: String(r[idf]), label: String(r[lf]) }))
    if (type === 'group') return pick(groups.data, 'group_id', 'name')
    if (type === 'role') return pick(roles.data, 'role_id', 'name')
    if (type === 'department') return pick(deps.data, 'department_id', 'name')
    if (type === 'team') return pick(teams.data, 'team_id', 'name')
    return []
  }
  const labelFor = (r: Rule) => {
    if (r.principal_type === 'everyone') return 'Everyone'
    if (r.principal_type === 'user') return users.data?.items.find((u) => u.user_id === r.principal_id)?.display_name as string ?? r.principal_id ?? ''
    return options(r.principal_type).find((o) => o.id === r.principal_id)?.label ?? r.principal_id ?? ''
  }

  const diff = useMemo(() => {
    const a = new Set(editable.map(sig)), b = new Set(rules.map(sig))
    return { added: rules.filter((r) => !a.has(sig(r))), removed: editable.filter((r) => !b.has(sig(r))) }
  }, [editable, rules])
  const dirty = diff.added.length + diff.removed.length > 0
  const incomplete = rules.some((r) => r.principal_type !== 'everyone' && !r.principal_id)
  const [draft, setDraft] = useState<Rule>({ principal_type: 'group', principal_id: '', effect: 'allow', ...(withPermission ? { permission: 'read' } : {}) })

  return (
    <div className="space-y-3">
      <InlineAlert tone="warning">Deny always wins. Saving replaces the entire rule set, so removed rows lose access.</InlineAlert>
      {locked.length > 0 && <p className="text-xs text-ink-muted">{locked.length} rule(s) are managed by synchronisation and cannot be edited here.</p>}
      <div className="table-wrap"><table className="tbl"><caption className="sr-only">Access rules</caption>
        <thead><tr><th scope="col">Principal type</th><th scope="col">Principal</th><th scope="col">Effect</th>{withPermission && <th scope="col">Permission</th>}<th scope="col"><span className="sr-only">Remove</span></th></tr></thead>
        <tbody>
          {rules.length === 0 && <tr><td colSpan={5} className="text-ink-muted">No rules. Only administrators can access this item.</td></tr>}
          {rules.map((r, i) => (
            <tr key={i}><td>{r.principal_type}</td><td>{labelFor(r)}</td><td><Badge tone={r.effect === 'deny' ? 'danger' : 'success'}>{r.effect}</Badge></td>{withPermission && <td>{r.permission}</td>}
              <td><Button size="sm" variant="ghost" aria-label={`Remove rule for ${labelFor(r)}`} onClick={() => setRules(rules.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" aria-hidden /></Button></td></tr>))}
        </tbody></table></div>
      <fieldset className="rounded-card border border-line p-3"><legend className="px-1 text-sm font-medium">Add a rule</legend>
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs font-medium">Type<Select className="mt-1 w-36" value={draft.principal_type} onChange={(e) => setDraft({ ...draft, principal_type: e.target.value, principal_id: '' })}>{TYPES.map((t) => <option key={t} value={t}>{t}</option>)}</Select></label>
          {draft.principal_type === 'user' && (
            <label className="relative text-xs font-medium">Find user<Input className="mt-1 w-56" type="search" value={term} onChange={(e) => setTerm(e.target.value)} placeholder="Name or email" />
              {users.data && users.data.items.length > 0 && !draft.principal_id && <ul className="absolute z-10 mt-1 w-full rounded-control border border-line bg-surface shadow-raised">{users.data.items.map((u) => <li key={String(u.user_id)}><button type="button" className="w-full px-2 py-1 text-left hover:bg-canvas" onClick={() => { setDraft({ ...draft, principal_id: String(u.user_id) }); setTerm(String(u.display_name)) }}>{String(u.display_name)}</button></li>)}</ul>}
            </label>)}
          {!['user', 'everyone'].includes(draft.principal_type) && (
            <label className="text-xs font-medium">Principal<Select className="mt-1 w-48" value={draft.principal_id ?? ''} onChange={(e) => setDraft({ ...draft, principal_id: e.target.value })}><option value="">Select…</option>{options(draft.principal_type).map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}</Select></label>)}
          <label className="text-xs font-medium">Effect<Select className="mt-1 w-28" value={draft.effect} onChange={(e) => setDraft({ ...draft, effect: e.target.value as 'allow' | 'deny' })}><option value="allow">Allow</option><option value="deny">Deny</option></Select></label>
          {withPermission && <label className="text-xs font-medium">Permission<Select className="mt-1 w-28" value={draft.permission} onChange={(e) => setDraft({ ...draft, permission: e.target.value })}><option value="read">Read</option><option value="write">Write</option><option value="manage">Manage</option></Select></label>}
          <Button variant="secondary" disabled={draft.principal_type !== 'everyone' && !draft.principal_id} onClick={() => { if (!rules.some((r) => sig(r) === sig(draft))) setRules([...rules, draft]); setDraft({ ...draft, principal_id: '' }); setTerm('') }}>Add rule</Button>
        </div>
      </fieldset>
      <div className="flex gap-2"><Button disabled={!dirty || incomplete} onClick={() => setConfirm(true)}>Review and save</Button><Button variant="ghost" disabled={!dirty} onClick={() => setRules(editable)}>Reset</Button></div>
      <ConfirmDialog open={confirm} onOpenChange={setConfirm} level="reason" minReason={5} destructive={false} title="Confirm access changes" confirmLabel="Save access rules"
        description={<div className="space-y-2"><p>This replaces the whole rule set.</p>
          {diff.added.length > 0 && <div><p className="font-medium text-success">Added ({diff.added.length})</p><ul className="list-disc pl-5">{diff.added.map((r) => <li key={sig(r)}>{r.effect} {r.principal_type} {labelFor(r)}{r.permission ? ` (${r.permission})` : ''}</li>)}</ul></div>}
          {diff.removed.length > 0 && <div><p className="font-medium text-danger">Removed ({diff.removed.length})</p><ul className="list-disc pl-5">{diff.removed.map((r) => <li key={sig(r)}>{r.effect} {r.principal_type} {labelFor(r)}{r.permission ? ` (${r.permission})` : ''}</li>)}</ul></div>}</div>}
        onConfirm={async () => { try { await onSave(rules.map(({ origin: _o, ...rest }) => rest)) } catch (e) { throw e instanceof ApiError ? e : new Error('Failed') } }} />
    </div>
  )
}
