import { z } from 'zod'
import { CLASSIFICATIONS, DOCUMENT_TYPES, LINES_OF_BUSINESS } from '@/types/api'

// Controlled vocabularies are validated by the backend but not served by an API yet (gap F-17): kept in constants.
const ALLOWED_EXT = ['pdf', 'docx', 'doc', 'txt', 'csv', 'xlsx', 'html', 'htm', 'png', 'jpg', 'jpeg', 'tif', 'tiff']
export const ACCEPT = ALLOWED_EXT.map((e) => `.${e}`).join(',')

export function validateFile(f: File): string | null {
  const ext = f.name.split('.').pop()?.toLowerCase() ?? ''
  if (!ALLOWED_EXT.includes(ext)) return `".${ext}" files are not supported. Use PDF, DOCX, DOC, TXT, CSV, XLSX, HTML or a scanned image.`
  if (f.size === 0) return 'The file is empty.'
  return null
}

export const metadataSchema = z.object({
  collection_id: z.string().min(1, 'Choose a collection.'),
  document_type: z.enum(DOCUMENT_TYPES, { errorMap: () => ({ message: 'Choose a document type.' }) }),
  insurance_line: z.enum(LINES_OF_BUSINESS).optional().or(z.literal('')),
  product: z.string().max(200).optional(),
  jurisdictions: z.string().optional().refine(
    (v) => !v || v.split(',').map((s) => s.trim()).filter(Boolean).every((c) => c.length >= 2 && c.length <= 10),
    'Jurisdiction codes are 2 to 10 characters, separated by commas.'),
  effective_from: z.string().optional(),
  effective_to: z.string().optional(),
  classification: z.enum(CLASSIFICATIONS),
}).refine((v) => !v.effective_from || !v.effective_to || v.effective_to >= v.effective_from, { path: ['effective_to'], message: 'The end date must be on or after the start date.' })

export type MetadataForm = z.infer<typeof metadataSchema>

export function toMetadata(v: MetadataForm) {
  const j = (v.jurisdictions ?? '').split(',').map((s) => s.trim()).filter(Boolean)
  return {
    document_type: v.document_type, classification: v.classification,
    ...(v.insurance_line ? { insurance_line: v.insurance_line } : {}),
    ...(v.product ? { product: v.product } : {}),
    ...(j.length ? { jurisdictions: j } : {}),
    ...(v.effective_from ? { effective_from: v.effective_from } : {}),
    ...(v.effective_to ? { effective_to: v.effective_to } : {}),
  }
}
