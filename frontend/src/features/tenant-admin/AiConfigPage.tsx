import { zodResolver } from '@hookform/resolvers/zod'
import { useQuery } from '@tanstack/react-query'
import { Lock } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { useSearchParams } from 'react-router-dom'
import { adminApi } from '@/services/api/adminApi'
import { ApiError, fieldErrors } from '@/services/api/errors'
import { aiSchema, ragSchema, type AiForm, type RagForm } from '@/schemas/admin'
import { usePermissions } from '@/hooks/usePermissions'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Checkbox, Field, Input, Select } from '@/components/ui/form'
import { Tabs } from '@/components/ui/tabs'
import { ConfirmDialog } from '@/components/dialogs/ConfirmDialog'
import { InlineAlert, QueryState } from '@/components/feedback/states'
import { JsonViewer, PageHeader } from '@/components/common/display'
import { formatDateTime, humanize } from '@/utils/format'
import { n, s, useTenantKey, useWrite, type Row } from './common'

type Cfg = { ai: Row; rag: Row; tenant_overridable_settings?: unknown; available_models: Row[] }

const locked = (over: unknown, field: string) => Array.isArray(over) ? !over.includes(field) : over && typeof over === 'object' ? (over as Record<string, unknown>)[field] === false : false

function Lock_({ show }: { show: boolean }) { return show ? <span title="Managed by the platform" className="ml-1 inline-flex items-center text-ink-muted"><Lock className="h-3 w-3" aria-label="Locked by the platform" /></span> : null }

function ModelsTab({ cfg }: { cfg: Cfg }) {
  const [err, setErr] = useState<string | null>(null)
  const [pending, setPending] = useState<AiForm | null>(null)
  const a = cfg.ai
  const { register, handleSubmit, watch, setError, formState: { errors } } = useForm<AiForm>({
    resolver: zodResolver(aiSchema),
    defaultValues: { llm_provider: s(a.llm_provider, ''), chat_model: s(a.chat_model, ''), embedding_provider: s(a.embedding_provider, ''), embedding_model: s(a.embedding_model, ''), embedding_dimensions: n(a.embedding_dimensions) ?? 1536,
      reranker_provider: s(a.reranker_provider, ''), reranker_model: s(a.reranker_model, ''), rewrite_model: s(a.rewrite_model, ''), temperature: n(a.temperature) ?? 0, max_output_tokens: n(a.max_output_tokens) ?? 1024,
      distance_metric: (s(a.distance_metric, 'cosine') as 'cosine'), reason: '' },
  })
  const embeddingChanged = watch('embedding_model') !== s(a.embedding_model, '') || watch('embedding_provider') !== s(a.embedding_provider, '')
  const models = (p: string, purpose: string) => cfg.available_models.filter((m) => m.purpose === purpose && (!p || m.provider === p))
  const providersOf = (purpose: string) => [...new Set(cfg.available_models.filter((m) => m.purpose === purpose).map((m) => s(m.provider)))]
  const save = useWrite((v: AiForm) => adminApi.putAi({ ...v, temperature: Number(v.temperature), max_output_tokens: Number(v.max_output_tokens), embedding_dimensions: Number(v.embedding_dimensions), reranker_provider: v.reranker_provider || undefined, reranker_model: v.reranker_model || undefined, rewrite_model: v.rewrite_model || undefined }),
    { invalidate: [['admin', 'config']], success: 'AI configuration saved as a new version.', silentError: true })
  // The backend lets tenant administrators choose any approved model whatever the overridable list says
  // (see _MODEL_FIELDS in config_service.py), so these fields are never locked here.
  const MODEL_FIELDS = ['llm_provider', 'chat_model', 'embedding_provider', 'embedding_model', 'embedding_dimensions', 'reranker_provider', 'reranker_model', 'rewrite_model', 'distance_metric']
  const lockedF = (f: string) => !MODEL_FIELDS.includes(f) && locked(cfg.tenant_overridable_settings, f)
  const doSave = (v: AiForm) => { setErr(null); save.mutate(v, { onError: (e) => { Object.entries(fieldErrors(e)).forEach(([k, m]) => { if (k in v) setError(k as keyof AiForm, { message: m }) }); setErr(e instanceof ApiError ? e.message : 'Something went wrong.') } }) }
  const sel = (name: keyof AiForm, label: string, purpose: string, providerField: keyof AiForm) => {
    const prov = watch(providerField) as string
    return <Field label={<>{label}<Lock_ show={lockedF(name)} /></> as unknown as string} error={errors[name]?.message as string | undefined}>{(p) => <Select {...p} disabled={lockedF(name)} {...register(name)}><option value="">–</option>{models(prov, purpose).map((m) => <option key={`${s(m.provider)}-${s(m.model_name)}`} value={s(m.model_name)}>{s(m.model_name)}</option>)}</Select>}</Field>
  }
  return (
    <form noValidate className="space-y-4" onSubmit={handleSubmit((v) => { if (embeddingChanged) setPending(v); else doSave(v) })}>
      {err && <InlineAlert tone="danger">{err}</InlineAlert>}
      <Card><CardHeader title="Models" description="Choose from the models the platform has approved." /><CardBody className="grid gap-3 sm:grid-cols-2">
        <Field label="Chat provider">{(p) => <Select {...p} disabled={lockedF('llm_provider')} {...register('llm_provider')}>{providersOf('chat').map((x) => <option key={x}>{x}</option>)}</Select>}</Field>
        {sel('chat_model', 'Chat model', 'chat', 'llm_provider')}
        <Field label="Embedding provider">{(p) => <Select {...p} disabled={lockedF('embedding_provider')} {...register('embedding_provider')}>{providersOf('embedding').map((x) => <option key={x}>{x}</option>)}</Select>}</Field>
        {sel('embedding_model', 'Embedding model', 'embedding', 'embedding_provider')}
        <Field label="Embedding dimensions" error={errors.embedding_dimensions?.message} hint="Must match the embedding model.">{(p) => <Input {...p} type="number" disabled={lockedF('embedding_dimensions')} {...register('embedding_dimensions')} />}</Field>
        <Field label="Distance metric">{(p) => <Select {...p} {...register('distance_metric')}><option value="cosine">Cosine</option><option value="inner_product">Inner product</option><option value="l2">L2</option></Select>}</Field>
        <Field label="Reranker provider">{(p) => <Select {...p} {...register('reranker_provider')}><option value="">None</option>{providersOf('rerank').map((x) => <option key={x}>{x}</option>)}</Select>}</Field>
        {sel('reranker_model', 'Reranker model', 'rerank', 'reranker_provider')}
        {sel('rewrite_model', 'Query rewrite model', 'rewrite', 'llm_provider')}
        <Field label="Temperature" error={errors.temperature?.message} hint="0 to 2">{(p) => <Input {...p} type="number" step="0.1" disabled={lockedF('temperature')} {...register('temperature')} />}</Field>
        <Field label="Maximum output tokens" error={errors.max_output_tokens?.message}>{(p) => <Input {...p} type="number" disabled={lockedF('max_output_tokens')} {...register('max_output_tokens')} />}</Field>
      </CardBody></Card>
      {embeddingChanged && <InlineAlert tone="warning" title="Re-indexing required">Changing the embedding model requires re-indexing all documents, and the dimension must match the model.</InlineAlert>}
      <Card><CardBody className="flex flex-wrap items-end gap-3">
        <Field label="Reason for change" required error={errors.reason?.message} className="min-w-[280px] flex-1">{(p) => <Input {...p} {...register('reason')} />}</Field>
        <Button type="submit" loading={save.isPending}>Save new version</Button>
      </CardBody></Card>
      <ConfirmDialog open={!!pending} onOpenChange={(o) => !o && setPending(null)} destructive title="Change embedding model?" confirmLabel="Save and require re-index"
        description="Existing embeddings were created with the current model. Search quality is affected until every document is re-indexed."
        onConfirm={async () => { if (pending) doSave(pending); setPending(null) }} level="simple" />
    </form>
  )
}

const RAG_FIELDS: { name: keyof RagForm; label: string; type?: 'number' | 'bool' | 'select'; step?: string; hint?: string }[] = [
  { name: 'chunking_strategy', label: 'Chunking strategy', type: 'select' }, { name: 'chunk_size', label: 'Chunk size', type: 'number', hint: '64 to 4,000' },
  { name: 'chunk_overlap', label: 'Chunk overlap', type: 'number', hint: 'Smaller than the chunk size' },
  { name: 'vector_top_k', label: 'Vector top-k', type: 'number' }, { name: 'fts_top_k', label: 'Full-text top-k', type: 'number' }, { name: 'exact_top_k', label: 'Exact top-k', type: 'number' },
  { name: 'vector_weight', label: 'Vector weight', type: 'number', step: '0.1' }, { name: 'fts_weight', label: 'Full-text weight', type: 'number', step: '0.1' }, { name: 'exact_weight', label: 'Exact weight', type: 'number', step: '0.1' },
  { name: 'rrf_k', label: 'RRF k', type: 'number', hint: '1 to 1,000' }, { name: 'rerank_top_n', label: 'Rerank top-n', type: 'number' }, { name: 'final_top_k', label: 'Final top-k', type: 'number' },
  { name: 'max_context_tokens', label: 'Maximum context tokens', type: 'number' }, { name: 'min_relevance', label: 'Minimum relevance', type: 'number', step: '0.01', hint: '0 to 1' },
  { name: 'hnsw_ef_search', label: 'HNSW ef_search', type: 'number', hint: '10 to 1,000' },
]

function RetrievalTab({ cfg }: { cfg: Cfg }) {
  const r = cfg.rag
  const [err, setErr] = useState<string | null>(null)
  const { register, handleSubmit, setError, formState: { errors } } = useForm<RagForm>({
    resolver: zodResolver(ragSchema),
    defaultValues: Object.fromEntries([...RAG_FIELDS.map((f) => [f.name, r[f.name] ?? '']), ['rerank_enabled', Boolean(r.rerank_enabled)], ['citation_required', Boolean(r.citation_required)], ['query_rewriting', Boolean(r.query_rewriting)], ['reason', '']]) as unknown as RagForm,
  })
  const save = useWrite((v: RagForm) => adminApi.putRag(v as unknown as Record<string, unknown>), { invalidate: [['admin', 'config']], success: 'Retrieval configuration saved as a new version.', silentError: true })
  const lockedF = (f: string) => locked(cfg.tenant_overridable_settings, f)
  return (
    <form noValidate className="space-y-4" onSubmit={handleSubmit((v) => { setErr(null); save.mutate(v, { onError: (e) => { Object.entries(fieldErrors(e)).forEach(([k, m]) => { if (k in v) setError(k as keyof RagForm, { message: m }) }); setErr(e instanceof ApiError ? e.message : 'Something went wrong.') } }) })}>
      {err && <InlineAlert tone="danger">{err}</InlineAlert>}
      <Card><CardHeader title="Retrieval settings" description="The backend owns retrieval; these values tune it. Ranges are enforced by the server." /><CardBody className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {RAG_FIELDS.map((f) => (
          <Field key={f.name} label={<>{f.label}<Lock_ show={lockedF(f.name)} /></> as unknown as string} error={errors[f.name]?.message as string | undefined} hint={f.hint}>
            {(p) => f.type === 'select'
              ? <Select {...p} disabled={lockedF(f.name)} {...register(f.name)}><option value="fixed">Fixed</option><option value="recursive">Recursive</option><option value="structure_aware">Structure aware</option></Select>
              : <Input {...p} type="number" step={f.step} disabled={lockedF(f.name)} {...register(f.name)} />}
          </Field>))}
        <div className="flex flex-col gap-2 sm:col-span-2 lg:col-span-3">
          <Checkbox label="Rerank results" {...register('rerank_enabled')} /><Checkbox label="Citations required in answers" {...register('citation_required')} /><Checkbox label="Rewrite short follow-up questions" {...register('query_rewriting')} />
        </div>
      </CardBody></Card>
      <Card><CardBody className="flex flex-wrap items-end gap-3">
        <Field label="Reason for change" required error={errors.reason?.message} className="min-w-[280px] flex-1">{(p) => <Input {...p} {...register('reason')} />}</Field>
        <Button type="submit" loading={save.isPending}>Save new version</Button>
      </CardBody></Card>
    </form>
  )
}

function GuardrailsTab({ cfg }: { cfg: Cfg }) {
  const g = (cfg.rag.guardrails ?? {}) as Row
  return (
    <Card><CardHeader title="Guardrails" description="Prompt-injection handling, PII masking and regulated-decision handling." /><CardBody className="space-y-3">
      <InlineAlert>Guardrail settings live inside the retrieval configuration and are applied by the backend. They are shown here as currently active.</InlineAlert>
      <JsonViewer value={g} />
    </CardBody></Card>
  )
}

function HistoryTab({ perms }: { perms: boolean }) {
  const key = useTenantKey()
  const [kind, setKind] = useState<'ai' | 'rag'>('rag')
  const [rb, setRb] = useState<number | null>(null)
  const q = useQuery({ queryKey: key('admin', 'config', 'history', kind), queryFn: () => adminApi.configHistory(kind) })
  const [cmp, setCmp] = useState<[Row, Row] | null>(null)
  const [sel, setSel] = useState<number[]>([])
  return (
    <Card><CardHeader title="Version history" actions={<Select aria-label="Configuration type" value={kind} onChange={(e) => { setKind(e.target.value as 'ai' | 'rag'); setSel([]) }} className="w-40"><option value="rag">Retrieval</option><option value="ai">Models</option></Select>} />
      <QueryState query={q} isEmpty={(d) => d.length === 0}>{(rows) => (
        <div className="p-2"><div className="table-wrap"><table className="tbl"><caption className="sr-only">Configuration versions</caption>
          <thead><tr><th scope="col">Compare</th><th scope="col">Version</th><th scope="col">Created</th><th scope="col">Reason</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead>
          <tbody>{rows.map((v, i) => <tr key={s(v.version)}><td><input type="checkbox" aria-label={`Compare version ${s(v.version)}`} checked={sel.includes(i)} onChange={(e) => setSel(e.target.checked ? [...sel, i].slice(-2) : sel.filter((x) => x !== i))} /></td>
            <td>v{s(v.version)}{i === 0 && <span className="ml-1 text-xs text-success">active</span>}</td><td>{formatDateTime(v.created_at as string)}</td><td>{s(v.change_reason ?? v.reason)}</td>
            <td>{perms && i > 0 && <Button size="sm" variant="secondary" onClick={() => setRb(Number(v.version))}>Roll back</Button>}</td></tr>)}</tbody></table></div>
          <Button className="mt-2" variant="secondary" disabled={sel.length !== 2} onClick={() => setCmp([rows[sel[0]], rows[sel[1]]])}>Compare selected</Button></div>)}</QueryState>
      <ConfirmDialog open={rb !== null} onOpenChange={(o) => !o && setRb(null)} level="reason" minReason={5} destructive={false} title="Roll back configuration" confirmLabel={`Roll back to v${rb}`}
        description="Creates a new version with the values of the selected one."
        onConfirm={async () => { await adminApi.rollback(kind, rb!); void q.refetch() }} />
      {cmp && (
        <div className="border-t border-line p-4"><h3 className="mb-2 font-medium">v{s(cmp[0].version)} ↔ v{s(cmp[1].version)}</h3>
          <div className="table-wrap"><table className="tbl"><caption className="sr-only">Differences</caption><thead><tr><th scope="col">Setting</th><th scope="col">v{s(cmp[0].version)}</th><th scope="col">v{s(cmp[1].version)}</th></tr></thead>
            <tbody>{Object.keys(cmp[0]).filter((k) => JSON.stringify(cmp[0][k]) !== JSON.stringify(cmp[1][k]) && !['created_at', 'version', 'config_id'].includes(k)).map((k) => <tr key={k}><td>{humanize(k)}</td><td>{JSON.stringify(cmp[0][k])}</td><td>{JSON.stringify(cmp[1][k])}</td></tr>)}</tbody></table></div></div>)}
    </Card>
  )
}

export default function AiConfigPage() {
  const key = useTenantKey()
  const p = usePermissions()
  const [sp, setSp] = useSearchParams()
  const q = useQuery({ queryKey: key('admin', 'config'), queryFn: () => adminApi.config() as Promise<Cfg> })
  return (
    <>
      <PageHeader title="AI and RAG configuration" description="Every save creates a new version and needs a reason." />
      <QueryState query={q}>{(cfg) => (
        <Tabs value={sp.get('tab') ?? 'models'} onValueChange={(v) => setSp({ tab: v }, { replace: true })} tabs={[
          { value: 'models', label: 'Models', content: <ModelsTab cfg={cfg} /> },
          { value: 'retrieval', label: 'Retrieval', hidden: !p.can('admin.rag_config.manage'), content: <RetrievalTab cfg={cfg} /> },
          { value: 'guardrails', label: 'Guardrails', content: <GuardrailsTab cfg={cfg} /> },
          { value: 'history', label: 'History', content: <HistoryTab perms={p.can('admin.ai_config.manage')} /> },
        ]} />)}</QueryState>
    </>
  )
}
