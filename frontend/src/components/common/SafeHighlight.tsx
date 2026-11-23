import DOMPurify from 'dompurify'
import { useMemo } from 'react'

/** Search highlights contain <mark> tags from ts_headline. Only <mark> survives sanitising (Design Document 18). */
export function sanitizeHighlight(html: string): string {
  return DOMPurify.sanitize(html, { ALLOWED_TAGS: ['mark'], ALLOWED_ATTR: [] })
}

export function SafeHighlight({ html, fallback, className }: { html?: string | null; fallback: string; className?: string }) {
  const clean = useMemo(() => (html ? sanitizeHighlight(html) : ''), [html])
  if (!clean) return <p className={className}>{fallback.slice(0, 300)}{fallback.length > 300 ? '…' : ''}</p>
  return <p className={className} dangerouslySetInnerHTML={{ __html: clean }} />
}
