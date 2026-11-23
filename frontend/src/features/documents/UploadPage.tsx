import { zodResolver } from '@hookform/resolvers/zod'
import { useQuery } from '@tanstack/react-query'
import { UploadCloud, X } from 'lucide-react'
import { useCallback, useRef, useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { documentApi } from '@/services/api/documentApi'
import { adminApi } from '@/services/api/adminApi'
import { usePermissions } from '@/hooks/usePermissions'
import { ApiError, fieldErrors } from '@/services/api/errors'
import { ACCEPT, metadataSchema, toMetadata, validateFile, type MetadataForm } from '@/schemas/documents'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Field, Input, Select } from '@/components/ui/form'
import { InlineAlert } from '@/components/feedback/states'
import { PageHeader } from '@/components/common/display'
import { JobTracker } from '@/features/ingestion/JobTracker'
import { CLASSIFICATIONS, DOCUMENT_TYPES, LINES_OF_BUSINESS, type Collection } from '@/types/api'
import { formatBytes, humanize } from '@/utils/format'

interface Item {
  id: string; file: File; error?: string; progress: number
  state: 'ready' | 'uploading' | 'accepted' | 'rejected'
  jobId?: string; documentId?: string; reject?: { code: string; message: string }
}
let n = 0

export default function UploadPage() {
  const [items, setItems] = useState<Item[]>([])
  const [busy, setBusy] = useState(false)
  const [summary, setSummary] = useState<string | null>(null)
  const ctl = useRef<AbortController | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  // Administrators may upload to any collection of the tenant (the backend allows it), so they see all of them;
  // other users see only the collections their access rules let them write to.
  const perms = usePermissions()
  const seesAll = perms.canAny(['admin.collections.manage', 'admin.documents.manage'])
  const cols = useQuery({
    queryKey: ['collections', 'writable', seesAll ? 'admin' : 'user'],
    queryFn: () => (seesAll ? adminApi.collections() : documentApi.collections()) as Promise<Collection[]>,
    staleTime: 60_000,
  })
  const { register, handleSubmit, setError, formState: { errors } } = useForm<MetadataForm>({
    resolver: zodResolver(metadataSchema), defaultValues: { collection_id: '', document_type: 'policy_wording', classification: 'internal', insurance_line: '', product: '', jurisdictions: '', effective_from: '', effective_to: '' },
  })

  const add = useCallback((files: FileList | File[]) => {
    // Copy eagerly: a FileList is live and is emptied when the input value is reset (before React runs the updater).
    const picked = Array.from(files).map((file): Item => ({ id: `f${++n}`, file, error: validateFile(file) ?? undefined, progress: 0, state: 'ready' }))
    setItems((cur) => [...cur, ...picked])
  }, [])
  const patch = (id: string, p: Partial<Item>) => setItems((cur) => cur.map((i) => (i.id === id ? { ...i, ...p } : i)))

  const send = handleSubmit(async (v) => {
    const todo = items.filter((i) => !i.error && (i.state === 'ready' || i.state === 'rejected'))
    if (!todo.length) { toast.error('Add at least one valid file.'); return }
    setBusy(true); setSummary(null)
    ctl.current = new AbortController()
    const meta = toMetadata(v)
    try {
      if (todo.length > 1) {
        todo.forEach((i) => patch(i.id, { state: 'uploading', progress: 0, reject: undefined }))
        const res = await documentApi.bulkUpload(todo.map((i) => i.file), v.collection_id, meta, (p) => todo.forEach((i) => patch(i.id, { progress: p })), ctl.current.signal)
        const rows = ((res.results ?? res.items ?? []) as Record<string, unknown>[])
        todo.forEach((i) => {
          const r = rows.find((x) => x.filename === i.file.name)
          if (r?.status === 'accepted') patch(i.id, { state: 'accepted', progress: 100, jobId: r.job_id as string, documentId: r.document_id as string })
          else patch(i.id, { state: 'rejected', reject: { code: (r?.error as { code?: string })?.code ?? 'error', message: (r?.error as { message?: string })?.message ?? 'Rejected' } })
        })
        setSummary(`${res.accepted ?? 0} accepted, ${res.rejected ?? 0} rejected.`)
      } else {
        const i = todo[0]
        patch(i.id, { state: 'uploading', progress: 0, reject: undefined })
        try {
          const r = await documentApi.upload(i.file, v.collection_id, meta, (p) => patch(i.id, { progress: p }), ctl.current.signal)
          patch(i.id, { state: 'accepted', progress: 100, jobId: r.job_id, documentId: r.document_id })
          setSummary('1 accepted. Processing continues in the background.')
        } catch (e) {
          if (e instanceof ApiError && e.code === 'aborted') { patch(i.id, { state: 'ready', progress: 0 }); return }
          if (e instanceof ApiError && e.code === 'validation_failed') {
            const fe = fieldErrors(e)
            for (const k of ['collection_id', 'document_type', 'effective_to', 'effective_from', 'jurisdictions'] as const) if (fe[k]) setError(k, { message: fe[k] })
          }
          patch(i.id, { state: 'rejected', reject: { code: e instanceof ApiError ? e.code : 'error', message: e instanceof ApiError ? e.message : 'Upload failed.' } })
        }
      }
    } catch (e) {
      if (!(e instanceof ApiError && e.code === 'aborted')) toast.error(e instanceof ApiError ? e.message : 'Upload failed.')
      todo.forEach((i) => patch(i.id, { state: 'ready', progress: 0 }))
    } finally { setBusy(false) }
  })

  return (
    <>
      <PageHeader title="Upload documents" description="Files are scanned, parsed and indexed in the background. Uploaded does not mean searchable until processing succeeds." />
      <form onSubmit={send} noValidate className="grid gap-4 lg:grid-cols-[1fr_1fr]">
        <div className="space-y-4">
          <Card><CardHeader title="Files" /><CardBody className="space-y-3">
            <div onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); add(e.dataTransfer.files) }}
              className="flex flex-col items-center gap-2 rounded-card border-2 border-dashed border-line px-4 py-8 text-center">
              <UploadCloud className="h-8 w-8 text-ink-muted" aria-hidden />
              <p>Drag files here, or</p>
              <Button type="button" variant="secondary" onClick={() => inputRef.current?.click()}>Choose files</Button>
              <input ref={inputRef} type="file" multiple accept={ACCEPT} className="sr-only" aria-label="Choose files to upload" onChange={(e) => { if (e.target.files) add(e.target.files); e.target.value = '' }} />
              <p className="text-xs text-ink-muted">PDF, DOCX, DOC, TXT, CSV, XLSX, HTML and scanned images. Up to 100 files per upload.</p>
            </div>
            {items.length > 0 && (
              <ul className="space-y-2">{items.map((i) => (
                <li key={i.id} className="rounded-card border border-line p-2 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <span className="min-w-0 truncate font-medium">{i.file.name} <span className="font-normal text-ink-muted">({formatBytes(i.file.size)})</span></span>
                    {i.state !== 'uploading' && i.state !== 'accepted' && <Button type="button" variant="ghost" size="icon" aria-label={`Remove ${i.file.name}`} onClick={() => setItems((c) => c.filter((x) => x.id !== i.id))}><X className="h-4 w-4" aria-hidden /></Button>}
                  </div>
                  {i.error && <p role="alert" className="text-xs text-danger">{i.error}</p>}
                  {i.state === 'uploading' && <div className="mt-1 h-1.5 overflow-hidden rounded-pill bg-line" role="progressbar" aria-label={`Uploading ${i.file.name}`} aria-valuenow={i.progress} aria-valuemin={0} aria-valuemax={100}><div className="h-full bg-primary" style={{ width: `${i.progress}%` }} /></div>}
                  {i.state === 'rejected' && i.reject && (
                    <p role="alert" className="mt-1 text-xs text-danger">{i.reject.message}{(i.reject.code === 'duplicate_document' || i.reject.code === 'duplicate_version') && ' Search the document library for the existing item.'}</p>
                  )}
                  {i.state === 'accepted' && i.jobId && <div className="mt-1"><JobTracker jobId={i.jobId} />{i.documentId && <Link className="mt-1 inline-block text-xs text-primary underline" to={`/documents/${i.documentId}`}>Open document</Link>}</div>}
                </li>
              ))}</ul>
            )}
          </CardBody></Card>
        </div>
        <Card><CardHeader title="Document details" description="Applied to every file in this upload." /><CardBody className="grid gap-3 sm:grid-cols-2">
          <Field label="Collection" error={errors.collection_id?.message} required hint={cols.isError ? 'Could not load collections.' : cols.data && cols.data.filter((c) => c.can_write !== false).length === 0 ? 'No collection is available to you. An administrator must create one (Admin → Collections) and grant you write access.' : undefined} className="sm:col-span-2">
            {(p) => <Select {...p} {...register('collection_id')}><option value="">Select a collection…</option>{cols.data?.filter((c) => c.can_write !== false).map((c) => <option key={c.collection_id} value={c.collection_id}>{c.name}</option>)}</Select>}
          </Field>
          <Field label="Document type" error={errors.document_type?.message} required>{(p) => <Select {...p} {...register('document_type')}>{DOCUMENT_TYPES.map((t) => <option key={t} value={t}>{humanize(t)}</option>)}</Select>}</Field>
          <Field label="Line of business" error={errors.insurance_line?.message}>{(p) => <Select {...p} {...register('insurance_line')}><option value="">Not specified</option>{LINES_OF_BUSINESS.map((t) => <option key={t} value={t}>{humanize(t)}</option>)}</Select>}</Field>
          <Field label="Product" error={errors.product?.message}>{(p) => <Input {...p} maxLength={200} {...register('product')} />}</Field>
          <Field label="Jurisdictions" error={errors.jurisdictions?.message} hint="Comma-separated, e.g. UK, IE">{(p) => <Input {...p} {...register('jurisdictions')} />}</Field>
          <Field label="Effective from" error={errors.effective_from?.message}>{(p) => <Input {...p} type="date" {...register('effective_from')} />}</Field>
          <Field label="Effective to" error={errors.effective_to?.message}>{(p) => <Input {...p} type="date" {...register('effective_to')} />}</Field>
          <Field label="Classification" error={errors.classification?.message} required>{(p) => <Select {...p} {...register('classification')}>{CLASSIFICATIONS.map((t) => <option key={t} value={t}>{humanize(t)}</option>)}</Select>}</Field>
          <div className="flex items-end gap-2 sm:col-span-2">
            <Button type="submit" loading={busy} disabled={items.filter((i) => !i.error && i.state !== 'accepted').length === 0}>Upload {items.filter((i) => !i.error && i.state !== 'accepted').length || ''} file(s)</Button>
            {busy && <Button type="button" variant="secondary" onClick={() => ctl.current?.abort()}>Cancel</Button>}
          </div>
          {summary && <InlineAlert tone="success" className="sm:col-span-2">{summary}</InlineAlert>}
        </CardBody></Card>
      </form>
    </>
  )
}
