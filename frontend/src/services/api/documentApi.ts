import { apiClient, del, downloadBlob, get, put, clean } from './apiClient'
import type { Collection, DocumentPreview, DocumentRow, IngestionJob, Message, Page, Row, UploadResult } from '@/types/api'

export interface DocQuery { q?: string; collection_id?: string; document_type?: string; insurance_line?: string; sort?: string; limit?: number; offset?: number }
export interface DocMetadata {
  title?: string; document_type?: string; insurance_line?: string; product?: string; jurisdictions?: string[]
  classification?: string; effective_from?: string; effective_to?: string; language?: string
}

/** Multipart upload with progress and cancellation (axios uses XHR in the browser). */
function multipart<T>(url: string, form: FormData, onProgress?: (pct: number) => void, signal?: AbortSignal) {
  return apiClient.post<T>(url, form, {
    timeout: 600_000, signal,
    onUploadProgress: (e) => { if (e.total && onProgress) onProgress(Math.round((e.loaded / e.total) * 100)) },
  }).then((r) => r.data)
}

export const documentApi = {
  list: (q: DocQuery, signal?: AbortSignal) => get<Page<DocumentRow>>('/documents', clean(q), { signal }),
  get: (id: string) => get<DocumentRow>(`/documents/${id}`),
  update: (id: string, b: DocMetadata) => put<DocumentRow>(`/documents/${id}`, b),
  remove: (id: string, reason?: string) => del<Row>(`/documents/${id}`, clean({ reason })),
  preview: (id: string, p: { page?: number; chunk_id?: string }) => get<DocumentPreview>(`/documents/${id}/preview`, clean(p)),
  download: (id: string, version_id?: string) => downloadBlob(`/documents/${id}/download`, clean({ version_id }), 'document'),
  upload: (file: File, collection_id: string, metadata: DocMetadata, onProgress?: (p: number) => void, signal?: AbortSignal) => {
    const f = new FormData()
    f.append('file', file); f.append('collection_id', collection_id); f.append('metadata', JSON.stringify(metadata))
    return multipart<UploadResult>('/documents', f, onProgress, signal)
  },
  bulkUpload: (files: File[], collection_id: string, metadata: DocMetadata, onProgress?: (p: number) => void, signal?: AbortSignal) => {
    const f = new FormData()
    files.forEach((x) => f.append('files', x)); f.append('collection_id', collection_id); f.append('metadata', JSON.stringify(metadata))
    return multipart<{ results?: Row[]; items?: Row[] } & Row>('/documents/bulk', f, onProgress, signal)
  },
  newVersion: (id: string, file: File, metadata: DocMetadata, onProgress?: (p: number) => void) => {
    const f = new FormData()
    f.append('file', file); f.append('metadata', JSON.stringify(metadata))
    return multipart<UploadResult>(`/documents/${id}/versions`, f, onProgress)
  },
  job: (jobId: string, signal?: AbortSignal) => get<IngestionJob>(`/ingestion/jobs/${jobId}`, undefined, { signal }),
  collections: () => get<Collection[]>('/collections'),
}
export type { Message }
