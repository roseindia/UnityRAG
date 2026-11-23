import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, Eye } from 'lucide-react'
import { useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { useAuth } from '@/contexts/AuthContext'
import { documentApi, type DocMetadata } from '@/services/api/documentApi'
import { ApiError } from '@/services/api/errors'
import { usePermissions } from '@/hooks/usePermissions'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Field, Input, Select } from '@/components/ui/form'
import { Modal } from '@/components/ui/dialog'
import { ConfirmDialog } from '@/components/dialogs/ConfirmDialog'
import { InlineAlert, QueryState } from '@/components/feedback/states'
import { KeyValueList, Mono, PageHeader, StatusBadge } from '@/components/common/display'
import { DocumentPreviewDrawer } from '@/components/rag/DocumentPreviewDrawer'
import { JobTracker } from '@/features/ingestion/JobTracker'
import { CLASSIFICATIONS, DOCUMENT_TYPES, LINES_OF_BUSINESS, type DocumentRow } from '@/types/api'
import { formatBytes, formatDateOnly, formatDateTime, humanize } from '@/utils/format'

function EditMetadata({ doc, open, onOpenChange }: { doc: DocumentRow; open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient()
  const [v, setV] = useState<DocMetadata>({ title: doc.title, document_type: doc.document_type, insurance_line: doc.insurance_line ?? '', product: doc.product ?? '', classification: doc.classification, effective_from: doc.effective_from ?? '', effective_to: doc.effective_to ?? '' })
  const bad = !!v.effective_from && !!v.effective_to && v.effective_to < v.effective_from
  const m = useMutation({
    mutationFn: () => documentApi.update(doc.document_id, Object.fromEntries(Object.entries(v).filter(([, x]) => x !== '' && x !== undefined))),
    onSuccess: () => { toast.success('Document updated.'); onOpenChange(false); void qc.invalidateQueries({ queryKey: ['document', doc.document_id] }) },
  })
  return (
    <Modal open={open} onOpenChange={onOpenChange} title="Edit metadata" description="Metadata describes the document; it is not part of any AI answer."
      footer={<><Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button><Button loading={m.isPending} disabled={bad || !v.title} onClick={() => m.mutate()}>Save</Button></>}>
      <form className="grid gap-3 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); if (!bad) m.mutate() }}>
        <Field label="Title" required className="sm:col-span-2">{(p) => <Input {...p} value={v.title ?? ''} onChange={(e) => setV({ ...v, title: e.target.value })} />}</Field>
        <Field label="Document type">{(p) => <Select {...p} value={v.document_type} onChange={(e) => setV({ ...v, document_type: e.target.value })}>{DOCUMENT_TYPES.map((t) => <option key={t} value={t}>{humanize(t)}</option>)}</Select>}</Field>
        <Field label="Line of business">{(p) => <Select {...p} value={v.insurance_line} onChange={(e) => setV({ ...v, insurance_line: e.target.value })}><option value="">Not specified</option>{LINES_OF_BUSINESS.map((t) => <option key={t} value={t}>{humanize(t)}</option>)}</Select>}</Field>
        <Field label="Product">{(p) => <Input {...p} value={v.product ?? ''} onChange={(e) => setV({ ...v, product: e.target.value })} />}</Field>
        <Field label="Classification">{(p) => <Select {...p} value={v.classification} onChange={(e) => setV({ ...v, classification: e.target.value })}>{CLASSIFICATIONS.map((t) => <option key={t} value={t}>{humanize(t)}</option>)}</Select>}</Field>
        <Field label="Effective from">{(p) => <Input {...p} type="date" value={v.effective_from ?? ''} onChange={(e) => setV({ ...v, effective_from: e.target.value })} />}</Field>
        <Field label="Effective to" error={bad ? 'The end date must be on or after the start date.' : undefined}>{(p) => <Input {...p} type="date" value={v.effective_to ?? ''} onChange={(e) => setV({ ...v, effective_to: e.target.value })} />}</Field>
        {m.isError && <InlineAlert tone="danger" className="sm:col-span-2">{(m.error as ApiError).message}</InlineAlert>}
      </form>
    </Modal>
  )
}

function NewVersion({ id, open, onOpenChange }: { id: string; open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient()
  const [file, setFile] = useState<File | null>(null)
  const [pct, setPct] = useState(0)
  const [jobId, setJobId] = useState<string | null>(null)
  const ref = useRef<HTMLInputElement>(null)
  const m = useMutation({
    mutationFn: () => documentApi.newVersion(id, file!, {}, setPct),
    onSuccess: (r) => { setJobId(r.job_id); void qc.invalidateQueries({ queryKey: ['document', id] }) },
  })
  const dup = m.error instanceof ApiError && (m.error.code === 'duplicate_version' || m.error.code === 'duplicate_document')
  return (
    <Modal open={open} onOpenChange={(o) => { onOpenChange(o); if (!o) { setFile(null); setJobId(null); m.reset(); setPct(0) } }} title="Upload a new version" description="The previous version is superseded once the new one is published."
      footer={!jobId && <><Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button><Button loading={m.isPending} disabled={!file} onClick={() => m.mutate()}>Upload version</Button></>}>
      <div className="space-y-3">
        <input ref={ref} type="file" className="sr-only" aria-label="Choose the new version file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        <Button variant="secondary" onClick={() => ref.current?.click()}>{file ? file.name : 'Choose file…'}</Button>
        {m.isPending && <div className="h-1.5 overflow-hidden rounded-pill bg-line" role="progressbar" aria-label="Upload progress" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}><div className="h-full bg-primary" style={{ width: `${pct}%` }} /></div>}
        {m.isError && <InlineAlert tone="danger">{dup ? 'This exact file is already uploaded as a version of this document.' : (m.error as ApiError).message}</InlineAlert>}
        {jobId && <JobTracker jobId={jobId} />}
      </div>
    </Modal>
  )
}

export default function DocumentDetailPage() {
  const { id = '' } = useParams()
  const { profile } = useAuth()
  const p = usePermissions()
  const nav = useNavigate()
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['document', id], queryFn: () => documentApi.get(id), retry: false })
  const [preview, setPreview] = useState(false)
  const [edit, setEdit] = useState(false)
  const [version, setVersion] = useState(false)
  const [del, setDel] = useState(false)
  const canDelete = p.canAny(['documents.delete', 'admin.documents.manage'])

  return (
    <QueryState query={q}>
      {(d) => (
        <>
          <PageHeader title={d.title} description={`${humanize(d.document_type)} · ${humanize(d.insurance_line)}`} actions={<>
            <Button variant="secondary" onClick={() => setPreview(true)}><Eye className="h-4 w-4" aria-hidden />Preview</Button>
            {p.can('documents.download') && <Button variant="secondary" title="Downloads are recorded" onClick={() => { void documentApi.download(d.document_id).catch((e: ApiError) => toast.error(e.message)) }}><Download className="h-4 w-4" aria-hidden />Download</Button>}
            {p.canAny(['documents.manage', 'admin.documents.manage']) && <Button variant="secondary" onClick={() => setEdit(true)}>Edit metadata</Button>}
            {p.can('documents.upload') && <Button variant="secondary" onClick={() => setVersion(true)}>New version</Button>}
            {canDelete && <Button variant="danger" disabled={d.legal_hold} title={d.legal_hold ? 'Under legal hold' : undefined} onClick={() => setDel(true)}>Withdraw</Button>}
          </>} />
          {d.legal_hold && <InlineAlert tone="warning" className="mb-3" title="Under legal hold">This document cannot be withdrawn or deleted while the hold is in place.</InlineAlert>}
          <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
            <Card><CardHeader title="Versions" /><div className="table-wrap border-0"><table className="tbl"><caption className="sr-only">Versions</caption>
              <thead><tr><th scope="col">#</th><th scope="col">Label</th><th scope="col">File</th><th scope="col">State</th><th scope="col">Pages</th><th scope="col">Size</th><th scope="col">Created</th></tr></thead>
              <tbody>{(d.versions ?? []).map((v) => <tr key={v.version_id}><td>{v.version_seq}{v.version_id === d.current_version_id && <span className="ml-1 text-xs text-success">current</span>}</td><td>{v.version_label ?? '–'}</td><td>{v.original_filename}</td><td><StatusBadge value={v.state} /></td><td>{v.page_count ?? '–'}</td><td>{formatBytes(v.size_bytes)}</td><td>{formatDateTime(v.created_at)}</td></tr>)}</tbody></table></div></Card>
            <Card><CardHeader title="Metadata" description="Document metadata, not AI output." /><CardBody>
              <KeyValueList items={[
                { label: 'Lifecycle', value: <StatusBadge value={d.lifecycle_state} /> }, { label: 'Classification', value: humanize(d.classification) },
                { label: 'Product', value: d.product ?? '–' }, { label: 'Jurisdictions', value: d.jurisdictions?.join(', ') || '–' },
                { label: 'Effective', value: `${formatDateOnly(d.effective_from)} – ${formatDateOnly(d.effective_to)}` }, { label: 'Review due', value: formatDateOnly(d.review_due_at) },
                { label: 'Language', value: d.language ?? '–' }, { label: 'Document id', value: <Mono>{d.document_id}</Mono> },
              ]} /></CardBody></Card>
          </div>
          <DocumentPreviewDrawer target={preview ? { documentId: d.document_id, title: d.title } : null} onClose={() => setPreview(false)} />
          {edit && <EditMetadata doc={d} open={edit} onOpenChange={setEdit} />}
          <NewVersion id={d.document_id} open={version} onOpenChange={setVersion} />
          <ConfirmDialog open={del} onOpenChange={setDel} level="reason" title="Withdraw document" confirmLabel="Withdraw document"
            description={<>Withdraw <strong>{d.title}</strong>? It is removed from search and answers immediately, and derived data is purged in the background.</>}
            onConfirm={async (reason) => { await documentApi.remove(d.document_id, reason); toast.success('Document withdrawn.'); void qc.invalidateQueries({ queryKey: [profile?.tenant_id, 'documents'] }); nav('/documents') }} />
        </>
      )}
    </QueryState>
  )
}
