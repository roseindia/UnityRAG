import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { baseProfile, renderScreen } from '../utils'
import { ApiError } from '@/services/api/errors'
import type { ChatAnswer, Profile } from '@/types/api'

const auth = { status: 'authenticated', profile: null as Profile | null, memberships: [], needsTenantChoice: false, notice: null, tenantSuspended: false, login: vi.fn(), loginWithOidc: vi.fn(), selectTenant: vi.fn(), confirmTenant: vi.fn(), logout: vi.fn(), reloadProfile: vi.fn() }
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => auth, AuthProvider: ({ children }: { children: React.ReactNode }) => children }))

const documentApi = vi.hoisted(() => ({ list: vi.fn(), collections: vi.fn(), upload: vi.fn(), bulkUpload: vi.fn(), job: vi.fn(), get: vi.fn(), preview: vi.fn(), download: vi.fn(), update: vi.fn(), remove: vi.fn(), newVersion: vi.fn() }))
const searchApi = vi.hoisted(() => ({ search: vi.fn(), facets: vi.fn(), history: vi.fn() }))
const chatApi = vi.hoisted(() => ({ stream: vi.fn(), ask: vi.fn(), feedback: vi.fn(), conversations: vi.fn(), conversation: vi.fn(), rename: vi.fn(), remove: vi.fn(), exportConversation: vi.fn(), createConversation: vi.fn(), sources: vi.fn() }))
vi.mock('@/services/api/documentApi', () => ({ documentApi }))
vi.mock('@/services/api/searchApi', () => ({ searchApi }))
vi.mock('@/services/api/chatApi', () => ({ chatApi }))

const { default: DocumentsPage } = await import('@/features/documents/DocumentsPage')
const { default: UploadPage } = await import('@/features/documents/UploadPage')
const { default: SearchPage } = await import('@/features/search/SearchPage')
const { default: ChatPage } = await import('@/features/chat/ChatPage')

const doc = (i: number, o = {}) => ({ document_id: `d${i}`, collection_id: 'c1', title: `Policy ${i}`, document_type: 'policy_wording', insurance_line: 'motor', classification: 'internal', lifecycle_state: 'published', size_bytes: 2048, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-02T00:00:00Z', ...o })

beforeEach(() => {
  vi.clearAllMocks()
  auth.profile = { ...baseProfile, permissions: [...baseProfile.permissions, 'documents.upload', 'documents.download'] }
  documentApi.collections.mockResolvedValue([{ collection_id: 'c1', code: 'motor', name: 'Motor policies', can_write: true }])
  chatApi.conversations.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 })
})

describe('document listing', () => {
  it('shows backend documents with lifecycle status and sends filters to the API', async () => {
    documentApi.list.mockResolvedValue({ items: [doc(1), doc(2, { lifecycle_state: 'withdrawn', legal_hold: false })], total: 2, limit: 50, offset: 0 })
    renderScreen(<DocumentsPage />, { path: '/documents', entry: '/documents?document_type=policy_wording' })
    expect(await screen.findByRole('link', { name: 'Policy 1' })).toHaveAttribute('href', '/documents/d1')
    expect(screen.getByText('Withdrawn')).toBeInTheDocument()
    expect(documentApi.list.mock.calls[0][0]).toMatchObject({ document_type: 'policy_wording', limit: 50, offset: 0 })
  })

  it('shows an empty state and an error state with retry', async () => {
    documentApi.list.mockResolvedValueOnce({ items: [], total: 0, limit: 50, offset: 0 })
    const { unmount } = renderScreen(<DocumentsPage />)
    expect(await screen.findByText('No documents found')).toBeInTheDocument()
    unmount()
    documentApi.list.mockRejectedValue(new ApiError({ status: 500, code: 'internal_error', correlationId: 'ref12345abcdef' }))
    renderScreen(<DocumentsPage />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Something went wrong on our side')
    expect(screen.getByText(/ref12345/)).toBeInTheDocument()
    expect(screen.queryByText(/internal_error|500/)).not.toBeInTheDocument()
  })
})

describe('document upload and ingestion status', () => {
  const choose = async (files: File[]) => userEvent.upload(screen.getByLabelText('Choose files to upload'), files)

  it('uploads with metadata, then shows the real ingestion status rather than "done"', async () => {
    documentApi.upload.mockResolvedValue({ document_id: 'd9', version_id: 'v1', job_id: 'j1' })
    documentApi.job.mockResolvedValue({ job_id: 'j1', document_id: 'd9', version_id: 'v1', job_type: 'ingest', status: 'running', stage: 'embed', attempt: 1, max_attempts: 5 })
    renderScreen(<UploadPage />)
    await choose([new File(['%PDF-1.4'], 'wording.pdf', { type: 'application/pdf' })])
    await waitFor(() => expect(screen.getByRole('option', { name: 'Motor policies' })).toBeInTheDocument())
    await userEvent.selectOptions(screen.getByLabelText(/Collection/), 'c1')
    await userEvent.type(screen.getByLabelText('Jurisdictions'), 'UK, IE')
    await userEvent.click(screen.getByRole('button', { name: /Upload 1 file/ }))
    await waitFor(() => expect(documentApi.upload).toHaveBeenCalled())
    const [file, collection, meta] = documentApi.upload.mock.calls[0]
    expect(file.name).toBe('wording.pdf'); expect(collection).toBe('c1')
    expect(meta).toMatchObject({ document_type: 'policy_wording', classification: 'internal', jurisdictions: ['UK', 'IE'] })
    const list = await screen.findByLabelText('Ingestion stages')
    expect(within(list).getByText('Embedding')).toBeInTheDocument()
    expect(screen.getByText('Running')).toBeInTheDocument()
    expect(screen.queryByText(/complete|succeeded/i)).not.toBeInTheDocument()
  })

  it('rejects unsupported file types in the browser before any upload', async () => {
    renderScreen(<UploadPage />)
    await userEvent.upload(screen.getByLabelText('Choose files to upload'), new File(['MZ'], 'setup.exe'), { applyAccept: false })
    expect(await screen.findByRole('alert')).toHaveTextContent('".exe" files are not supported')
    expect(documentApi.upload).not.toHaveBeenCalled()
  })

  it('shows quarantined and duplicate outcomes from the backend', async () => {
    documentApi.upload.mockRejectedValue(new ApiError({ status: 409, code: 'duplicate_document' }))
    renderScreen(<UploadPage />)
    await choose([new File(['x'], 'a.pdf')])
    await waitFor(() => expect(screen.getByRole('option', { name: 'Motor policies' })).toBeInTheDocument())
    await userEvent.selectOptions(screen.getByLabelText(/Collection/), 'c1')
    await userEvent.click(screen.getByRole('button', { name: /Upload 1 file/ }))
    expect(await screen.findByText(/already exists.*Search the document library/)).toBeInTheDocument()
  })

  it('marks a quarantined job as blocked with no retry', async () => {
    documentApi.upload.mockResolvedValue({ document_id: 'd9', version_id: 'v1', job_id: 'j2' })
    documentApi.job.mockResolvedValue({ job_id: 'j2', document_id: 'd9', version_id: 'v1', job_type: 'ingest', status: 'quarantined', stage: 'malware_scan', attempt: 1, max_attempts: 5 })
    renderScreen(<UploadPage />)
    await choose([new File(['x'], 'a.pdf')])
    await waitFor(() => expect(screen.getByRole('option', { name: 'Motor policies' })).toBeInTheDocument())
    await userEvent.selectOptions(screen.getByLabelText(/Collection/), 'c1')
    await userEvent.click(screen.getByRole('button', { name: /Upload 1 file/ }))
    expect(await screen.findByText(/blocked by security scanning/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /retry/i })).not.toBeInTheDocument()
  })
})

describe('search', () => {
  const result = (o = {}) => ({ chunk_id: 'ch1', document_id: 'd1', version_id: 'v1', title: 'ABC Motor Policy', section_path: 'Section 2', clause_ref: '2.1', page_from: 3, page_to: 3, content: 'Flood is covered.', highlight: 'damage caused by <mark>flood</mark><script>alert(1)</script>', document_type: 'policy_wording', jurisdictions: ['UK'], effective_from: '2026-01-01', effective_to: '2026-12-31', lifecycle_state: 'published', version_label: '2026.1', score: 0.8, ...o })

  it('submits the query, renders backend results with highlights, and sanitises the markup', async () => {
    searchApi.facets.mockResolvedValue({ line_of_business: [{ value: 'motor', label: 'motor', count: 3 }] })
    searchApi.search.mockResolvedValue({ search_id: 's1', mode: 'hybrid', query: 'flood', results: [result()], latency_ms: 120, cache_hit: false })
    const { container } = renderScreen(<SearchPage />, { path: '/search', entry: '/search' })
    await userEvent.type(screen.getByLabelText('Search approved documents'), 'flood')
    await userEvent.click(screen.getByRole('button', { name: 'Search' }))
    expect(await screen.findByText('ABC Motor Policy')).toBeInTheDocument()
    expect(container.querySelector('mark')?.textContent).toBe('flood')
    expect(container.querySelector('script')).toBeNull()
    expect(screen.getByText(/Version 2026.1/)).toBeInTheDocument()
    expect(searchApi.search.mock.calls[0].slice(0, 3)).toEqual(['flood', 'hybrid', {}])
  })

  it('offers facets from the backend and applies a facet as a request filter', async () => {
    searchApi.facets.mockResolvedValue({ line_of_business: [{ value: 'motor', label: 'motor', count: 3 }, { value: 'home', label: 'home', count: 1 }] })
    searchApi.search.mockResolvedValue({ search_id: 's1', mode: 'hybrid', query: 'flood', results: [], latency_ms: 10, cache_hit: false })
    renderScreen(<SearchPage />, { path: '/search', entry: '/search?q=flood' })
    await userEvent.click(await screen.findByLabelText(/Motor/))
    await waitFor(() => expect(searchApi.search.mock.calls.at(-1)?.[2]).toMatchObject({ lines_of_business: ['motor'] }))
    expect(await screen.findByText('No authorised passages found')).toBeInTheDocument()
  })

  it('shows an error with a reference when the API fails', async () => {
    searchApi.facets.mockResolvedValue({})
    searchApi.search.mockRejectedValue(new ApiError({ status: 503, code: 'service_unavailable', correlationId: 'abcdef1234567890' }))
    renderScreen(<SearchPage />, { path: '/search', entry: '/search?q=flood' })
    expect(await screen.findByText(/Something went wrong on our side/)).toBeInTheDocument()
    expect(screen.getByText(/abcdef12/)).toBeInTheDocument()
  })
})

describe('chat with streaming answer and citations', () => {
  const final: ChatAnswer = {
    conversation_id: 'cv1', message_id: 'm1', status: 'answered', evidence_strength: 'high', warnings: ['S1 is a superseded version.'], ai_generated: true,
    answer: 'Flood damage is covered. [S1] See the schedule.', disclaimer: 'AI-generated knowledge assistance based on approved documents.',
    citations: [{ marker: 'S1', document_id: 'd1', chunk_id: 'ch1', title: 'ABC Motor Policy', version_label: '2026.1', section_path: 'Section 2', clause_ref: '2.1', page_from: 3, page_to: 3, effective_from: '2026-01-01', effective_to: '2026-12-31', lifecycle_state: 'published', verified: true }],
  }

  it('streams tokens, then replaces them with the authoritative final answer, citations, evidence and disclaimer', async () => {
    chatApi.stream.mockImplementation(async (_m, _c, _f, _s, h) => {
      h.onMeta({ conversation_id: 'cv1', correlation_id: 'x', disclaimer: final.disclaimer })
      h.onToken('Flood damage is cov')
      h.onFinal(final)
    })
    renderScreen(<ChatPage />, { path: '/chat/:conversationId?', entry: '/chat' })
    await userEvent.type(screen.getByLabelText('Your question'), 'Is flood covered?{Enter}')
    await waitFor(() => expect(chatApi.stream).toHaveBeenCalled())
    expect(chatApi.stream.mock.calls[0][0]).toBe('Is flood covered?')
    expect(await screen.findByText('AI-generated')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Evidence: High' })).toBeInTheDocument()
    expect(screen.getByText(/AI-generated knowledge assistance/)).toBeInTheDocument()
    expect(screen.getByText('S1 is a superseded version.')).toBeInTheDocument()
    const chip = screen.getByRole('button', { name: 'Source 1: ABC Motor Policy, page 3' })
    expect(chip).toHaveTextContent('S1')
    expect(screen.queryByText(/Flood damage is cov$/)).not.toBeInTheDocument()
  })

  it('shows source details (version, section, dates, status) without a click, and opens in context', async () => {
    chatApi.stream.mockImplementation(async (_m, _c, _f, _s, h) => { h.onFinal(final) })
    renderScreen(<ChatPage />, { path: '/chat/:conversationId?', entry: '/chat' })
    await userEvent.type(screen.getByLabelText('Your question'), 'q{Enter}')
    await userEvent.click(await screen.findByText(/Sources \(1\)/))
    expect(screen.getByText('2026.1')).toBeInTheDocument()
    expect(screen.getByText('Section 2')).toBeInTheDocument()
    expect(screen.getByText(/01 Jan 2026 – 31 Dec 2026/)).toBeInTheDocument()
    documentApi.preview.mockResolvedValue({ document_id: 'd1', title: 'ABC Motor Policy', version_id: 'v1', page_number: 3, pages_total: 9, text: 'Flood is covered. Contact [EMAIL REDACTED]' })
    await userEvent.click(screen.getByRole('button', { name: /Open in context/ }))
    expect(await screen.findByText('[EMAIL REDACTED]')).toBeInTheDocument()
    expect(documentApi.preview).toHaveBeenCalledWith('d1', { chunk_id: 'ch1' })
  })

  it('does not invent citations: unknown markers stay as plain text', async () => {
    chatApi.stream.mockImplementation(async (_m, _c, _f, _s, h) => { h.onFinal({ ...final, answer: 'Covered [S1] and maybe [S7].' }) })
    renderScreen(<ChatPage />, { path: '/chat/:conversationId?', entry: '/chat' })
    await userEvent.type(screen.getByLabelText('Your question'), 'q{Enter}')
    await screen.findByText(/Covered/)
    expect(screen.getAllByRole('button', { name: /^Source \d/ })).toHaveLength(1)
    expect(screen.getByText(/\[S7\]/)).toBeInTheDocument()
  })

  it('renders an abstained answer as a neutral card with actions, not as an answer', async () => {
    chatApi.stream.mockImplementation(async (_m, _c, _f, _s, h) => { h.onFinal({ ...final, status: 'abstained', evidence_strength: 'none', answer: 'No approved document covers this. Searched: motor policies.', citations: [], warnings: [] }) })
    renderScreen(<ChatPage />, { path: '/chat/:conversationId?', entry: '/chat' })
    await userEvent.type(screen.getByLabelText('Your question'), 'q{Enter}')
    expect(await screen.findByText('No sufficient approved evidence')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Rephrase' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Report missing source' })).toBeInTheDocument()
  })

  it('flags needs_review answers and keeps blocked answers free of detail', async () => {
    chatApi.stream.mockImplementation(async (_m, _c, _f, _s, h) => { h.onFinal({ ...final, status: 'needs_review' }) })
    const { unmount } = renderScreen(<ChatPage />, { path: '/chat/:conversationId?', entry: '/chat' })
    await userEvent.type(screen.getByLabelText('Your question'), 'q{Enter}')
    expect(await screen.findByText('Requires expert review before use')).toBeInTheDocument()
    unmount()
    chatApi.stream.mockImplementation(async (_m, _c, _f, _s, h) => { h.onFinal({ ...final, status: 'blocked', answer: 'This request cannot be answered under the usage policy.', citations: [], warnings: [] }) })
    renderScreen(<ChatPage />, { path: '/chat/:conversationId?', entry: '/chat' })
    await userEvent.type(screen.getByLabelText('Your question'), 'q{Enter}')
    expect(await screen.findByText(/cannot be answered under the usage policy/)).toBeInTheDocument()
  })

  it('keeps streamed text but marks it incomplete when the connection fails mid-stream, and offers retry', async () => {
    chatApi.stream.mockImplementation(async (_m, _c, _f, _s, h) => {
      h.onToken('Partial answer')
      throw new ApiError({ status: 0, code: 'network_error' })
    })
    renderScreen(<ChatPage />, { path: '/chat/:conversationId?', entry: '/chat' })
    await userEvent.type(screen.getByLabelText('Your question'), 'q{Enter}')
    expect(await screen.findByText('Partial answer')).toBeInTheDocument()
    expect(screen.getByText('Incomplete')).toBeInTheDocument()
    expect(screen.getByText(/Connection lost/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })

  it('shows rate-limit errors from before the stream starts', async () => {
    chatApi.stream.mockRejectedValue(new ApiError({ status: 429, code: 'rate_limited', retryAfter: 60 }))
    renderScreen(<ChatPage />, { path: '/chat/:conversationId?', entry: '/chat' })
    await userEvent.type(screen.getByLabelText('Your question'), 'q{Enter}')
    expect(await screen.findByText('Too many requests. Please wait a moment.')).toBeInTheDocument()
  })

  it('stops generation with the Stop button and marks the answer as stopped', async () => {
    chatApi.stream.mockImplementation((_m, _c, _f, signal: AbortSignal) => new Promise((_res, rej) => { signal.addEventListener('abort', () => rej(new ApiError({ status: 0, code: 'aborted' }))) }))
    renderScreen(<ChatPage />, { path: '/chat/:conversationId?', entry: '/chat' })
    await userEvent.type(screen.getByLabelText('Your question'), 'q{Enter}')
    await userEvent.click(await screen.findByRole('button', { name: 'Stop generating' }))
    expect(await screen.findByText('Stopped')).toBeInTheDocument()
    expect(screen.getByLabelText('Send')).toBeInTheDocument()
  })

  it('sends a thumbs-up rating for the answer and prevents a double submission', async () => {
    chatApi.stream.mockImplementation(async (_m, _c, _f, _s, h) => { h.onFinal(final) })
    chatApi.feedback.mockResolvedValue({})
    renderScreen(<ChatPage />, { path: '/chat/:conversationId?', entry: '/chat' })
    await userEvent.type(screen.getByLabelText('Your question'), 'q{Enter}')
    const up = await screen.findByRole('button', { name: 'Helpful' })
    await userEvent.click(up)
    await userEvent.click(up)
    await waitFor(() => expect(chatApi.feedback).toHaveBeenCalledTimes(1))
    expect(chatApi.feedback).toHaveBeenCalledWith({ message_id: 'm1', rating: 1, category: 'rating' })
  })
})
