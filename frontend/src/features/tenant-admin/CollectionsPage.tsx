import { zodResolver } from '@hookform/resolvers/zod'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { z } from 'zod'
import { adminApi } from '@/services/api/adminApi'
import { ApiError, fieldErrors } from '@/services/api/errors'
import { Button } from '@/components/ui/button'
import { Card, CardBody } from '@/components/ui/card'
import { Checkbox, Field, Input, Select, Textarea } from '@/components/ui/form'
import { Modal } from '@/components/ui/dialog'
import { Tabs } from '@/components/ui/tabs'
import { AccessRuleEditor, type Rule } from '@/components/forms/AccessRuleEditor'
import { ConfirmDialog } from '@/components/dialogs/ConfirmDialog'
import { EmptyState, InlineAlert, QueryState } from '@/components/feedback/states'
import { JsonViewer, KeyValueList, PageHeader, StatusBadge } from '@/components/common/display'
import { CLASSIFICATIONS, LINES_OF_BUSINESS } from '@/types/api'
import { humanize } from '@/utils/format'
import { arrOf, s, useTenantKey, useWrite } from './common'

const schema = z.object({
  code: z.string().regex(/^[A-Za-z0-9_-]{2,40}$/, '2 to 40 letters, digits, - or _.'),
  name: z.string().trim().min(1, 'Enter a name.').max(200),
  description: z.string().max(1000).optional(),
  line_of_business: z.string().optional(),
  jurisdictions: z.string().optional(),
  classification: z.enum(CLASSIFICATIONS),
  retention_days: z.union([z.coerce.number().int().min(1, 'At least 1 day.'), z.literal('')]).optional(),
  auto_publish: z.boolean(),
})
type Form = z.input<typeof schema>

function CollectionForm({ initial, editing, onSubmit, pending, serverErrors, formError }: { initial?: Record<string, unknown>; editing: boolean; onSubmit: (v: Record<string, unknown>) => void; pending: boolean; serverErrors?: Record<string, string>; formError?: string | null }) {
  const { register, handleSubmit, formState: { errors } } = useForm<Form>({
    resolver: zodResolver(schema),
    values: { code: s(initial?.code, ''), name: s(initial?.name, ''), description: s(initial?.description, ''), line_of_business: s(initial?.line_of_business, ''), jurisdictions: arrOf(initial?.jurisdictions).join(', '),
      classification: (s(initial?.classification, 'internal') as 'internal'), retention_days: initial?.retention_days ? Number(initial.retention_days) : '', auto_publish: initial ? Boolean(initial.auto_publish) : true },
  })
  const err = (k: string, local?: string) => local ?? serverErrors?.[k]
  return (
    <form noValidate className="grid gap-3 sm:grid-cols-2" onSubmit={handleSubmit((v) => {
      const j = (v.jurisdictions ?? '').split(',').map((x) => x.trim()).filter(Boolean)
      onSubmit({ ...(editing ? {} : { code: v.code }), name: v.name, description: v.description || undefined, line_of_business: v.line_of_business || undefined, jurisdictions: j, classification: v.classification, retention_days: v.retention_days === '' || v.retention_days === undefined ? undefined : Number(v.retention_days), auto_publish: v.auto_publish })
    })}>
      {formError && <InlineAlert tone="danger" title="The collection was not saved" className="sm:col-span-2">{formError}</InlineAlert>}
      <Field label="Code" required error={err('code', errors.code?.message)}>{(p) => <Input {...p} disabled={editing} {...register('code')} />}</Field>
      <Field label="Name" required error={err('name', errors.name?.message)}>{(p) => <Input {...p} {...register('name')} />}</Field>
      <Field label="Description" className="sm:col-span-2">{(p) => <Textarea {...p} {...register('description')} />}</Field>
      <Field label="Line of business">{(p) => <Select {...p} {...register('line_of_business')}><option value="">Any</option>{LINES_OF_BUSINESS.map((l) => <option key={l} value={l}>{humanize(l)}</option>)}</Select>}</Field>
      <Field label="Classification">{(p) => <Select {...p} {...register('classification')}>{CLASSIFICATIONS.map((l) => <option key={l} value={l}>{humanize(l)}</option>)}</Select>}</Field>
      <Field label="Jurisdictions" hint="Comma-separated codes">{(p) => <Input {...p} {...register('jurisdictions')} />}</Field>
      <Field label="Retention (days)" error={err('retention_days', errors.retention_days?.message)}>{(p) => <Input {...p} type="number" min={1} {...register('retention_days')} />}</Field>
      <div className="sm:col-span-2"><Checkbox label="Publish documents automatically after ingestion" {...register('auto_publish')} /></div>
      <div className="sm:col-span-2"><Button type="submit" loading={pending}>{editing ? 'Save changes' : 'Create collection'}</Button></div>
    </form>
  )
}

export function CollectionsPage() {
  const key = useTenantKey()
  const nav = useNavigate()
  const q = useQuery({ queryKey: key('admin', 'collections'), queryFn: adminApi.collections })
  const [creating, setCreating] = useState(false)
  const [errs, setErrs] = useState<Record<string, string>>({})
  const [formError, setFormError] = useState<string | null>(null)
  const create = useWrite((v: Record<string, unknown>) => adminApi.createCollection(v), { invalidate: [['admin', 'collections']], success: 'Collection created.', silentError: true, onSuccess: (r) => { setCreating(false); if (r.collection_id) nav(`/admin/collections/${s(r.collection_id)}`) } })
  return (
    <>
      <PageHeader title="Collections" description="Collections group documents and control who can read or write them." actions={<Button onClick={() => setCreating(true)}>New collection</Button>} />
      <Card><QueryState query={q} isEmpty={(d) => d.length === 0} empty={<EmptyState title="No collections yet" action={<Button onClick={() => setCreating(true)}>Create a collection</Button>} />}>
        {(rows) => <div className="table-wrap border-0"><table className="tbl"><caption className="sr-only">Collections</caption><thead><tr><th scope="col">Code</th><th scope="col">Name</th><th scope="col">Line</th><th scope="col">Classification</th><th scope="col">Documents</th><th scope="col">Status</th></tr></thead>
          <tbody>{rows.map((c) => <tr key={s(c.collection_id)}><td className="font-mono text-xs">{s(c.code)}</td><td><Link className="font-medium text-primary hover:underline" to={`/admin/collections/${s(c.collection_id)}`}>{s(c.name)}</Link></td><td>{humanize(s(c.line_of_business, ''))}</td><td>{humanize(s(c.classification, ''))}</td><td>{s(c.document_count ?? c.documents)}</td><td><StatusBadge value={s(c.status, '')} /></td></tr>)}</tbody></table></div>}
      </QueryState></Card>
      <Modal open={creating} onOpenChange={setCreating} size="lg" title="New collection">
        <CollectionForm editing={false} pending={create.isPending} serverErrors={errs} formError={formError}
          onSubmit={(v) => { setErrs({}); setFormError(null); create.mutate(v, { onError: (e) => {
            setErrs(fieldErrors(e))
            const ref = e instanceof ApiError && e.correlationId ? ` (reference ${e.correlationId.slice(0, 8)})` : ''
            setFormError(`${e instanceof ApiError ? e.message : 'Something went wrong.'}${ref}`)
          } }) }} />
      </Modal>
    </>
  )
}

export function CollectionDetailPage() {
  const { id = '' } = useParams()
  const key = useTenantKey()
  const nav = useNavigate()
  const [sp, setSp] = useSearchParams()
  const q = useQuery({ queryKey: key('admin', 'collection', id), queryFn: () => adminApi.collection(id), retry: false })
  const stats = useQuery({ queryKey: key('admin', 'collection', id, 'stats'), queryFn: () => adminApi.collectionStats(id), enabled: (sp.get('tab') ?? 'settings') === 'stats' })
  const [del, setDel] = useState(false)
  const save = useWrite((v: Record<string, unknown>) => adminApi.updateCollection(id, v), { invalidate: [['admin', 'collection', id], ['admin', 'collections']], success: 'Collection saved.' })
  const access = useWrite((rules: Rule[]) => adminApi.setCollectionAccess(id, rules as unknown as Record<string, unknown>[]), { invalidate: [['admin', 'collection', id], ['search', 'facets']], success: 'Access rules saved.', silentError: true })
  return (
    <QueryState query={q}>
      {(c) => (
        <>
          <PageHeader title={s(c.name)} description={`Code ${s(c.code)}`} actions={<Button variant="danger" onClick={() => setDel(true)}>Delete</Button>} />
          <Tabs value={sp.get('tab') ?? 'settings'} onValueChange={(v) => setSp({ tab: v }, { replace: true })} tabs={[
            { value: 'settings', label: 'Settings', content: <Card><CardBody><CollectionForm initial={c} editing pending={save.isPending} onSubmit={(v) => save.mutate(v)} /></CardBody></Card> },
            { value: 'access', label: 'Access', content: <Card><CardBody><AccessRuleEditor withPermission initial={((c.access ?? []) as Rule[])} onSave={(rules) => access.mutateAsync(rules)} /></CardBody></Card> },
            { value: 'stats', label: 'Stats', content: <Card><QueryState query={stats}>{(d) => <CardBody><KeyValueList items={Object.entries(d).filter(([, v]) => typeof v !== 'object').map(([k, v]) => ({ label: humanize(k), value: s(v) }))} />
              {Object.values(d).some((v) => typeof v === 'object') && <div className="mt-3"><JsonViewer value={Object.fromEntries(Object.entries(d).filter(([, v]) => typeof v === 'object'))} /></div>}</CardBody>}</QueryState></Card> },
          ]} />
          <ConfirmDialog open={del} onOpenChange={setDel} title="Delete collection" confirmLabel="Delete collection" level="reason" minReason={5}
            description={<>Delete <strong>{s(c.name)}</strong>? <InlineAlert tone="warning" className="mt-2">Collections that still contain documents are usually refused by the server.</InlineAlert></>}
            onConfirm={async () => { await adminApi.deleteCollection(id); nav('/admin/collections') }} />
        </>
      )}
    </QueryState>
  )
}
