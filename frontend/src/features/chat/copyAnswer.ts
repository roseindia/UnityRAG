import type { Citation } from '@/types/api'

/** Copy text carries the citations as footnotes and the disclaimer (NFR-096). */
export function copyWithFootnotes(text: string, citations: Citation[], disclaimer?: string): string {
  const notes = citations.map((c, i) => {
    const mk = c.marker ?? `S${i + 1}`
    const where = [c.version_label && `v${c.version_label}`, c.section_path, c.page_from && `p. ${c.page_from}`].filter(Boolean).join(', ')
    return `[${mk}] ${c.title}${where ? ` (${where})` : ''}`
  })
  return [text, notes.length ? `\nSources:\n${notes.join('\n')}` : '', `\n${disclaimer ?? 'AI-generated guidance based on approved documents. Verify against the sources.'}`].join('\n').trim()
}
