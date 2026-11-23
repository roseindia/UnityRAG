import { useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, Download } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode, type RefObject } from 'react'
import { toast } from 'sonner'
import { documentApi } from '@/services/api/documentApi'
import { ApiError } from '@/services/api/errors'
import { Modal } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { InlineAlert, LoadingBlock, ErrorState } from '@/components/feedback/states'
import { Can } from '@/app/guards'
import { findHighlightRange } from '@/utils/highlight'

export interface PreviewTarget { documentId: string; chunkId?: string; page?: number; title?: string; highlightText?: string }

/** Masked tokens such as [EMAIL REDACTED] are shown as styled badges; the cited passage is highlighted as text (never as HTML). */
function renderPageText(text: string, range: [number, number] | null, markRef: RefObject<HTMLElement>): ReactNode[] {
  const parts: ReactNode[] = []
  const segments: Array<{ text: string; marked: boolean }> = range
    ? [
        { text: text.slice(0, range[0]), marked: false },
        { text: text.slice(range[0], range[1]), marked: true },
        { text: text.slice(range[1]), marked: false },
      ]
    : [{ text, marked: false }]
  let firstMark = true
  segments.forEach((seg, si) => {
    seg.text.split(/(\[[A-Z ]+ REDACTED\])/g).forEach((piece, pi) => {
      const key = `${si}-${pi}`
      if (/^\[[A-Z ]+ REDACTED\]$/.test(piece)) {
        parts.push(<span key={key} className="rounded-control bg-canvas px-1 font-mono text-xs text-ink-muted">{piece}</span>)
      } else if (seg.marked && piece) {
        // Scroll to the first highlighted fragment once the drawer has rendered it.
        const ref = firstMark ? markRef : undefined
        firstMark = false
        parts.push(<mark key={key} ref={ref} className="rounded-control px-0.5">{piece}</mark>)
      } else {
        parts.push(<span key={key}>{piece}</span>)
      }
    })
  })
  return parts
}

/** Fetched at open time so access is re-checked (FR-018). A 404 means the source is no longer available to the user. */
export function DocumentPreviewDrawer({ target, onClose }: { target: PreviewTarget | null; onClose: () => void }) {
  const [page, setPage] = useState<number | undefined>(undefined)
  useEffect(() => { setPage(target?.page) }, [target])
  const q = useQuery({
    queryKey: ['preview', target?.documentId, target?.chunkId, page],
    queryFn: () => documentApi.preview(target!.documentId, page ? { page } : target!.chunkId ? { chunk_id: target!.chunkId } : {}),
    enabled: !!target, staleTime: 0, gcTime: 0, retry: false,
  })
  const d = q.data
  const markRef = useRef<HTMLElement>(null)
  // Bring the cited passage into view; the page can be long and the highlight is often mid-page.
  useEffect(() => {
    if (d && markRef.current) markRef.current.scrollIntoView({ block: 'center' })
  }, [d, target?.highlightText])
  const gone = q.error instanceof ApiError && q.error.status === 404
  return (
    <Modal open={!!target} onOpenChange={(o) => { if (!o) onClose() }} variant="drawer" title={d?.title ?? target?.title ?? 'Document preview'}
      description="Preview text is masked for personal data by the server."
      footer={target && (
        <Can permission="documents.download" fallback={<span className="mr-auto text-xs text-ink-muted">Download is not available for your role.</span>}>
          <span className="mr-auto text-xs text-ink-muted">Downloads are recorded.</span>
          <Button variant="secondary" onClick={() => { void documentApi.download(target.documentId, d?.version_id).catch((e: ApiError) => toast.error(e.message)) }}><Download className="h-4 w-4" aria-hidden />Download original</Button>
        </Can>
      )}>
      {q.isPending && <LoadingBlock rows={6} />}
      {gone && <InlineAlert tone="warning" title="This source is no longer available to you">Access may have changed since the answer was produced.</InlineAlert>}
      {q.isError && !gone && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}
      {d && (
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-2 text-xs text-ink-muted">
            <span>Page {d.page_number}{d.page_label ? ` (${d.page_label})` : ''} of {d.pages_total}</span>
            <span className="flex gap-1">
              <Button variant="secondary" size="sm" aria-label="Previous page" disabled={d.page_number <= 1} onClick={() => setPage(d.page_number - 1)}><ChevronLeft className="h-4 w-4" aria-hidden /></Button>
              <Button variant="secondary" size="sm" aria-label="Next page" disabled={d.page_number >= d.pages_total} onClick={() => setPage(d.page_number + 1)}><ChevronRight className="h-4 w-4" aria-hidden /></Button>
            </span>
          </div>
          {d.low_confidence && <InlineAlert tone="warning">Text recognised from a scan; verify against the original.</InlineAlert>}
          <article className="whitespace-pre-wrap break-words rounded-card border border-line bg-surface p-3 text-sm leading-relaxed" aria-label={`Page ${d.page_number} text`}>
            {renderPageText(d.text, d.highlight ? [d.highlight.start, d.highlight.end] : findHighlightRange(d.text, target?.highlightText), markRef)}
          </article>
        </div>
      )}
    </Modal>
  )
}
