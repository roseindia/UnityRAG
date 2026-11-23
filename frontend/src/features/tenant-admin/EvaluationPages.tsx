import { useQuery } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { adminApi } from '@/services/api/adminApi'
import { ApiError } from '@/services/api/errors'
import { useAuth } from '@/contexts/AuthContext'
import { usePermissions } from '@/hooks/usePermissions'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader, Badge } from '@/components/ui/card'
import { Checkbox, Field, Input, Select, Textarea } from '@/components/ui/form'
import { Modal } from '@/components/ui/dialog'
import { EmptyState, InlineAlert, QueryState } from '@/components/feedback/states'
import { PageHeader, StatusBadge } from '@/components/common/display'
import { formatDateTime, humanize } from '@/utils/format'
import { n, s, useTenantKey, useWrite, type Row } from './common'

const DEFAULT_GATES: Record<string, number> = { recall_at_k: 0.9, mrr: 0.6, ndcg_at_k: 0.8, citation_coverage: 0.9, abstention_accuracy: 0.9, faithfulness: 0.95 }
const GATE_LABEL: Record<string, string> = { recall_at_k: 'Recall@k', mrr: 'MRR', ndcg_at_k: 'nDCG@k', citation_coverage: 'Citation coverage', abstention_accuracy: 'Abstention accuracy', faithfulness: 'Faithfulness' }

/** Minimal CSV parser (quoted fields, embedded commas). Parsed on the client and posted in batches. */
export function parseCsv(text: string): string[][] {
  const out: string[][] = []; let row: string[] = []; let cur = ''; let q = false
  for (let i = 0; i < text.length; i++) {
    const c = text[i]
    if (q) { if (c === '"' && text[i + 1] === '"') { cur += '"'; i++ } else if (c === '"') q = false; else cur += c }
    else if (c === '"') q = true
    else if (c === ',') { row.push(cur); cur = '' }
    else if (c === '\n' || c === '\r') { if (c === '\r' && text[i + 1] === '\n') i++; row.push(cur); cur = ''; if (row.some((x) => x.trim())) out.push(row); row = [] }
    else cur += c
  }
  row.push(cur); if (row.some((x) => x.trim())) out.push(row)
  return out
}

export function EvaluationPage() {
  const key = useTenantKey()
  const p = usePermissions()
  const nav = useNavigate()
  const ds = useQuery({ queryKey: key('admin', 'eval', 'datasets'), queryFn: adminApi.datasets, enabled: p.can('evaluation.manage') })
  const runs = useQuery({ queryKey: key('admin', 'eval', 'runs'), queryFn: () => adminApi.runs(), enabled: p.can('evaluation.run') })
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [purpose, setPurpose] = useState('retrieval')
  const [desc, setDesc] = useState('')
  const create = useWrite(() => adminApi.createDataset({ name: name.trim(), purpose, description: desc || undefined }), { invalidate: [['admin', 'eval']], success: 'Dataset created.', onSuccess: (r) => { setCreating(false); setName(''); if (r.dataset_id) nav(`/admin/evaluation/datasets/${s(r.dataset_id)}`) } })
  return (
    <>
      <PageHeader title="RAG evaluation" description="Datasets of questions with expected sources, and runs measured against quality gates." actions={p.can('evaluation.manage') && <Button onClick={() => setCreating(true)}>New dataset</Button>} />
      <div className="grid gap-4 lg:grid-cols-2">
        {p.can('evaluation.manage') && <Card><CardHeader title="Datasets" /><QueryState query={ds} isEmpty={(d) => d.length === 0} empty={<EmptyState title="No datasets yet" description="Create one, add questions and have a different person approve it." />}>
          {(rows) => <ul>{rows.map((d) => <li key={s(d.dataset_id)} className="flex items-center justify-between gap-2 border-b border-line px-4 py-2 last:border-0"><span><Link className="font-medium text-primary hover:underline" to={`/admin/evaluation/datasets/${s(d.dataset_id)}`}>{s(d.name)}</Link><span className="block text-xs text-ink-muted">v{s(d.version)} · {humanize(s(d.purpose, ''))} · {s(d.question_count ?? d.questions, '0')} questions</span></span><StatusBadge value={s(d.status, '')} /></li>)}</ul>}</QueryState></Card>}
        {p.can('evaluation.run') && <Card><CardHeader title="Recent runs" /><QueryState query={runs} isEmpty={(d) => d.length === 0} empty={<EmptyState title="No runs yet" description="Start a run from an approved dataset." />}>
          {(rows) => <ul>{rows.map((r) => <li key={s(r.run_id)} className="flex items-center justify-between gap-2 border-b border-line px-4 py-2 last:border-0"><span><Link className="font-medium text-primary hover:underline" to={`/admin/evaluation/runs/${s(r.run_id)}`}>{formatDateTime(r.started_at as string)}</Link><span className="block text-xs text-ink-muted">{humanize(s(r.mode, ''))} · k={s(r.k)}</span></span>
            {r.gate_passed === null || r.gate_passed === undefined ? <StatusBadge value={s(r.status, '')} /> : <Badge tone={r.gate_passed ? 'success' : 'danger'}>{r.gate_passed ? 'Gates passed' : 'Gates failed'}</Badge>}</li>)}</ul>}</QueryState></Card>}
      </div>
      <Modal open={creating} onOpenChange={setCreating} size="sm" title="New dataset" footer={<><Button variant="secondary" onClick={() => setCreating(false)}>Cancel</Button><Button loading={create.isPending} disabled={!name.trim()} onClick={() => create.mutate(undefined)}>Create</Button></>}>
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (name.trim()) create.mutate(undefined) }}>
          <Field label="Name" required>{(pp) => <Input {...pp} value={name} onChange={(e) => setName(e.target.value)} />}</Field>
          <Field label="Purpose">{(pp) => <Select {...pp} value={purpose} onChange={(e) => setPurpose(e.target.value)}>{['retrieval', 'generation', 'safety', 'access', 'regression'].map((x) => <option key={x} value={x}>{humanize(x)}</option>)}</Select>}</Field>
          <Field label="Description">{(pp) => <Textarea {...pp} value={desc} onChange={(e) => setDesc(e.target.value)} />}</Field>
        </form>
      </Modal>
    </>
  )
}

function QuestionForm({ id, onDone }: { id: string; onDone: () => void }) {
  const [q, setQ] = useState(''), [exp, setExp] = useState(''), [docs, setDocs] = useState(''), [answerable, setAnswerable] = useState(true), [cat, setCat] = useState('')
  const add = useWrite(() => adminApi.addQuestions(id, [{ question: q.trim(), expected_answer: exp || undefined, expected_document_ids: docs.split(',').map((x) => x.trim()).filter(Boolean), answerable, category: cat || undefined }]), { success: 'Question added.', onSuccess: () => { setQ(''); setExp(''); setDocs(''); onDone() } })
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (q.trim()) add.mutate(undefined) }}>
      <Field label="Question" required>{(p) => <Textarea {...p} value={q} onChange={(e) => setQ(e.target.value)} />}</Field>
      <Field label="Expected answer (optional)">{(p) => <Textarea {...p} value={exp} onChange={(e) => setExp(e.target.value)} />}</Field>
      <Field label="Expected document ids" hint="Comma-separated">{(p) => <Input {...p} value={docs} onChange={(e) => setDocs(e.target.value)} />}</Field>
      <Field label="Category">{(p) => <Input {...p} value={cat} onChange={(e) => setCat(e.target.value)} />}</Field>
      <Checkbox label="Answerable from approved documents" checked={answerable} onChange={(e) => setAnswerable(e.target.checked)} />
      <Button type="submit" loading={add.isPending} disabled={!q.trim()}>Add question</Button>
    </form>
  )
}

export function DatasetDetailPage() {
  const { id = '' } = useParams()
  const key = useTenantKey()
  const { profile } = useAuth()
  const p = usePermissions()
  const nav = useNavigate()
  const q = useQuery({ queryKey: key('admin', 'eval', 'dataset', id), queryFn: () => adminApi.dataset(id), retry: false })
  const file = useRef<HTMLInputElement>(null)
  const [adding, setAdding] = useState(false)
  const [running, setRunning] = useState(false)
  const [mode, setMode] = useState('retrieval'), [k, setK] = useState('10'), [gates, setGates] = useState<Record<string, string>>(Object.fromEntries(Object.entries(DEFAULT_GATES).map(([a, b]) => [a, String(b)])))
  const [importMsg, setImportMsg] = useState<string | null>(null)
  const [approveErr, setApproveErr] = useState<string | null>(null)
  const inv = [['admin', 'eval']]
  const approve = useWrite(() => adminApi.approveDataset(id), { invalidate: inv, success: 'Dataset approved.', silentError: true })
  const run = useWrite(() => adminApi.runEvaluation(id, { mode, k: Number(k), gates: Object.fromEntries(Object.entries(gates).map(([a, b]) => [a, Number(b)])) }), { invalidate: inv, success: 'Evaluation finished.', onSuccess: (r) => { setRunning(false); if (r.run_id) nav(`/admin/evaluation/runs/${s(r.run_id)}`) } })

  const importCsv = async (f: File) => {
    const rows = parseCsv(await f.text())
    const [head, ...body] = rows
    const col = (nm: string) => head.findIndex((h) => h.trim().toLowerCase() === nm)
    if (col('question') < 0) { setImportMsg('The CSV needs a "question" column.'); return }
    const qs = body.map((r) => ({ question: r[col('question')], expected_answer: col('expected_answer') >= 0 ? r[col('expected_answer')] || undefined : undefined,
      expected_document_ids: col('expected_document_ids') >= 0 ? (r[col('expected_document_ids')] || '').split(';').map((x) => x.trim()).filter(Boolean) : undefined,
      answerable: col('answerable') >= 0 ? !/^(false|no|0)$/i.test(r[col('answerable')] ?? '') : true, category: col('category') >= 0 ? r[col('category')] || undefined : undefined })).filter((x) => x.question?.trim())
    let done = 0
    try { for (let i = 0; i < qs.length; i += 50) { await adminApi.addQuestions(id, qs.slice(i, i + 50)); done += Math.min(50, qs.length - i) } setImportMsg(`Imported ${done} questions.`) }
    catch (e) { setImportMsg(`Imported ${done} of ${qs.length} questions, then stopped: ${e instanceof ApiError ? e.message : 'error'}`) }
    void q.refetch()
  }

  return (
    <QueryState query={q}>{(d) => {
      const approved = s(d.status) === 'approved'
      const author = d.created_by === profile?.user_id
      const questions = (d.questions ?? []) as Row[]
      return (<>
        <PageHeader title={s(d.name)} description={`Version ${s(d.version)} · ${humanize(s(d.purpose, ''))}`} actions={<>
          <StatusBadge value={s(d.status, '')} />
          {!approved && !author && <Button onClick={() => { setApproveErr(null); approve.mutate(undefined, { onError: (e) => setApproveErr(e instanceof ApiError ? (e.serverMessage ?? e.message) : 'Could not approve.') }) }} loading={approve.isPending}>Approve</Button>}
          {p.can('evaluation.run') && <Button variant="secondary" onClick={() => setRunning(true)}>Run evaluation</Button>}
        </>} />
        {!approved && <InlineAlert tone="warning" className="mb-3" title="Not approved">Gating runs need an approved dataset. {author ? 'You created this dataset, so another person must approve it.' : ''}</InlineAlert>}
        {approveErr && <InlineAlert tone="danger" className="mb-3">{approveErr}</InlineAlert>}
        <Card><CardHeader title={`Questions (${questions.length})`} actions={<><input ref={file} type="file" accept=".csv" className="sr-only" aria-label="Import questions from CSV" onChange={(e) => { const f = e.target.files?.[0]; if (f) void importCsv(f); e.target.value = '' }} /><Button size="sm" variant="secondary" onClick={() => file.current?.click()}>Import CSV</Button><Button size="sm" onClick={() => setAdding(true)}>Add question</Button></>} />
          {importMsg && <p className="px-4 pt-2 text-sm" role="status">{importMsg}</p>}
          <p className="px-4 pt-2 text-xs text-ink-muted">CSV columns: question, expected_answer, expected_document_ids (semicolon-separated), answerable, category.</p>
          {questions.length === 0 ? <EmptyState title="No questions yet" /> : <div className="table-wrap border-0"><table className="tbl"><caption className="sr-only">Questions</caption><thead><tr><th scope="col">Question</th><th scope="col">Category</th><th scope="col">Answerable</th><th scope="col">Expected documents</th></tr></thead>
            <tbody>{questions.map((x) => <tr key={s(x.question_id)}><td>{s(x.question)}</td><td>{s(x.category)}</td><td>{x.answerable === false ? 'No' : 'Yes'}</td><td>{Array.isArray(x.expected_document_ids) ? x.expected_document_ids.length : 0}</td></tr>)}</tbody></table></div>}
        </Card>
        <Modal open={adding} onOpenChange={setAdding} title="Add question" size="md"><QuestionForm id={id} onDone={() => { setAdding(false); void q.refetch() }} /></Modal>
        <Modal open={running} onOpenChange={setRunning} title="Run evaluation" description="Runs under your own permissions and returns metrics with a pass/fail per gate." footer={<><Button variant="secondary" onClick={() => setRunning(false)}>Cancel</Button><Button loading={run.isPending} onClick={() => run.mutate(undefined)}>Start run</Button></>}>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Mode">{(pp) => <Select {...pp} value={mode} onChange={(e) => setMode(e.target.value)}><option value="retrieval">Retrieval only</option><option value="end_to_end">End to end</option></Select>}</Field>
            <Field label="k">{(pp) => <Input {...pp} type="number" min={1} max={100} value={k} onChange={(e) => setK(e.target.value)} />}</Field>
            {Object.keys(DEFAULT_GATES).map((g) => <Field key={g} label={`Gate: ${GATE_LABEL[g]}`}>{(pp) => <Input {...pp} type="number" step="0.01" min={0} max={1} value={gates[g]} onChange={(e) => setGates({ ...gates, [g]: e.target.value })} />}</Field>)}
          </div>
          {!approved && <InlineAlert tone="warning" className="mt-3">This dataset is not approved yet; the server may reject a gating run.</InlineAlert>}
        </Modal>
      </>)
    }}</QueryState>
  )
}

export function RunDetailPage() {
  const { id = '' } = useParams()
  const key = useTenantKey()
  const q = useQuery({ queryKey: key('admin', 'eval', 'run', id), queryFn: () => adminApi.run(id), retry: false })
  const all = useQuery({ queryKey: key('admin', 'eval', 'runs', 'compare'), queryFn: () => adminApi.runs() })
  return (
    <QueryState query={q}>{(r) => {
      const sum = (r.summary ?? {}) as Row
      const gates = (sum.gates ?? {}) as { thresholds?: Record<string, number>; results?: Record<string, boolean> }
      const prev = all.data ? all.data.filter((x) => x.dataset_id === r.dataset_id && x.run_id !== r.run_id && String(x.started_at) < String(r.started_at))[0] : undefined
      const ps = (prev?.summary ?? {}) as Row
      const results = (r.results ?? []) as Row[]
      return (<>
        <PageHeader title="Evaluation run" description={`${humanize(s(r.mode, ''))}, k=${s(r.k)} · ${formatDateTime(r.started_at as string)}`} actions={r.gate_passed === null || r.gate_passed === undefined ? <StatusBadge value={s(r.status, '')} /> : <Badge tone={r.gate_passed ? 'success' : 'danger'}>{r.gate_passed ? 'All gates passed' : 'Gates failed'}</Badge>} />
        <Card className="mb-4"><CardHeader title="Scorecard" description={prev ? 'Compared with the previous run of this dataset.' : 'No previous run to compare with.'} />
          <div className="table-wrap border-0"><table className="tbl"><caption className="sr-only">Metrics and gates</caption><thead><tr><th scope="col">Metric</th><th scope="col">Value</th><th scope="col">Threshold</th><th scope="col">Result</th><th scope="col">Previous</th></tr></thead>
            <tbody>{Object.keys(DEFAULT_GATES).filter((g) => g in sum || gates.thresholds?.[g] !== undefined).map((g) => {
              const pass = gates.results?.[g]
              return <tr key={g}><td>{GATE_LABEL[g]}</td><td className="font-mono">{n(sum[g])?.toFixed(3) ?? '–'}</td><td className="font-mono">{gates.thresholds?.[g]?.toFixed(2) ?? '–'}</td><td>{pass === undefined ? '–' : <Badge tone={pass ? 'success' : 'danger'}>{pass ? 'Pass' : 'Fail'}</Badge>}</td><td className="font-mono">{n(ps[g])?.toFixed(3) ?? '–'}</td></tr>
            })}</tbody></table></div></Card>
        <Card><CardHeader title={`Per-question results (${results.length})`} />
          {results.length === 0 ? <EmptyState title="No per-question results" /> : <div className="table-wrap border-0"><table className="tbl"><caption className="sr-only">Per-question results</caption><thead><tr><th scope="col">Question</th><th scope="col">Passed</th><th scope="col">Answer status</th><th scope="col">Latency</th><th scope="col">Metrics</th></tr></thead>
            <tbody>{results.map((x) => <tr key={s(x.question_id)}><td className="font-mono text-xs">{s(x.question_id).slice(0, 8)}…</td><td><Badge tone={x.passed ? 'success' : 'danger'}>{x.passed ? 'Pass' : 'Fail'}</Badge></td><td>{humanize(s(x.answer_status, ''))}</td><td>{s(x.latency_ms)} ms</td><td className="font-mono text-xs">{Object.entries((x.metrics ?? {}) as Record<string, unknown>).map(([a, b]) => `${a}=${typeof b === 'number' ? b.toFixed(2) : String(b)}`).join(' ')}</td></tr>)}</tbody></table></div>}
        </Card>
        <CardBody />
      </>)
    }}</QueryState>
  )
}
