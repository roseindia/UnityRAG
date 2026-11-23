import { Bot, ExternalLink, ShieldAlert } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import { Badge, type Tone } from '@/components/ui/card'
import { Tip } from '@/components/ui/tooltip'
import { StatusBadge } from '@/components/common/display'
import { formatDateOnly } from '@/utils/format'
import { cn } from '@/utils/cn'
import type { Citation, EvidenceStrength } from '@/types/api'

const EVIDENCE: Record<string, { tone: Tone; label: string; tip: string }> = {
  high: { tone: 'success', label: 'Evidence: High', tip: 'The retrieved sources strongly support this answer.' },
  medium: { tone: 'warning', label: 'Evidence: Medium', tip: 'The sources partly support this answer. Check them before relying on it.' },
  low: { tone: 'neutral', label: 'Evidence: Low', tip: 'Verify carefully. The sources only weakly support this answer.' },
  none: { tone: 'neutral', label: 'Evidence: None', tip: 'No sufficient approved evidence was found.' },
}

/** Evidence strength is a labelled badge, never colour alone (FR-126). */
export function EvidenceBadge({ strength }: { strength?: EvidenceStrength | null }) {
  const e = EVIDENCE[strength ?? 'none'] ?? EVIDENCE.none
  return <Tip text={e.tip}><button type="button" className="rounded-pill"><Badge tone={e.tone}>{e.label}</Badge></button></Tip>
}

export function AiLabel() {
  return <Badge tone="info"><Bot className="h-3 w-3" aria-hidden />AI-generated</Badge>
}

/** The disclaimer is visible without interaction and cannot be dismissed (NFR-096). */
export function DisclaimerNote({ text }: { text?: string }) {
  return <p className="mt-2 border-t border-line pt-2 text-xs text-ink-muted">{text ?? 'AI-generated guidance based on approved documents. It is not a decision. Verify against the cited sources.'}</p>
}

export function citationLabel(c: Citation, n: number): string {
  return `Source ${n}: ${c.title}${c.page_from ? `, page ${c.page_from}` : ''}`
}

export function CitationChip({ marker, label, onClick, verified = true }: { marker: string; label: string; onClick: () => void; verified?: boolean }) {
  return (
    <button type="button" onClick={onClick} aria-label={label} title={label}
      className={cn('mx-0.5 inline-flex min-h-[24px] min-w-[24px] items-center justify-center rounded-control bg-info-bg px-1.5 align-baseline text-xs font-semibold text-primary hover:bg-primary hover:text-white', !verified && 'border border-warning')}>
      {marker}{!verified && <span className="sr-only"> (could not verify)</span>}
    </button>
  )
}

/** Version, date and status are visible without a click; "Open in context" is one click (NFR-095). */
export function SourceCard({ c, index, selected, onOpen, id }: { c: Citation; index: number; selected?: boolean; onOpen: (c: Citation) => void; id?: string }) {
  const pages = c.page_from ? (c.page_to && c.page_to !== c.page_from ? `pp. ${c.page_from}–${c.page_to}` : `p. ${c.page_from}`) : null
  return (
    <li id={id} tabIndex={-1} className={cn('rounded-card border bg-surface p-3 text-sm', selected ? 'border-primary ring-2 ring-primary/30' : 'border-line')}>
      <div className="flex items-start justify-between gap-2">
        <p className="font-medium"><span className="mr-1 rounded-control bg-info-bg px-1.5 py-0.5 text-xs text-primary">{c.marker ?? `S${index + 1}`}</span>{c.title}</p>
        {c.lifecycle_state && <StatusBadge value={c.lifecycle_state === 'published' ? 'published' : c.lifecycle_state} />}
      </div>
      <dl className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs text-ink-muted">
        {c.version_label && <><dt>Version</dt><dd className="text-ink">{c.version_label}</dd></>}
        {c.section_path && <><dt>Section</dt><dd className="break-words text-ink">{c.section_path}</dd></>}
        {c.clause_ref && <><dt>Clause</dt><dd className="text-ink">{c.clause_ref}</dd></>}
        {pages && <><dt>Pages</dt><dd className="text-ink">{pages}</dd></>}
        {(c.effective_from || c.effective_to) && <><dt>Effective</dt><dd className="text-ink">{formatDateOnly(c.effective_from)} – {formatDateOnly(c.effective_to)}</dd></>}
      </dl>
      {c.verified === false && <p className="mt-1 flex items-center gap-1 text-xs text-warning"><ShieldAlert className="h-3 w-3" aria-hidden />Could not verify this source against the document.</p>}
      <button type="button" onClick={() => onOpen(c)} className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline">
        <ExternalLink className="h-3 w-3" aria-hidden />Open in context
      </button>
    </li>
  )
}

/** Markdown answer with [S1] markers turned into citation chips. Raw HTML is never rendered; other links are shown as text. */
export function AnswerText({ text, citations, onCite }: { text: string; citations: Citation[]; onCite: (index: number) => void }) {
  const known = new Map(citations.map((c, i) => [c.marker ?? `S${i + 1}`, i]))
  const prepared = text.replace(/\[(S\d+)\]/g, (m, mk: string) => (known.has(mk) ? `[${mk}](#cite-${mk})` : m))
  return (
    <div className="prose-sm max-w-none space-y-2 break-words [&_ol]:list-decimal [&_ol]:pl-5 [&_ul]:list-disc [&_ul]:pl-5 [&_table]:w-full [&_td]:border [&_td]:px-2 [&_th]:border [&_th]:px-2">
      <ReactMarkdown
        components={{
          a: ({ href, children }) => {
            if (href?.startsWith('#cite-')) {
              const mk = href.slice(6)
              const i = known.get(mk)
              if (i === undefined) return <span>[{mk}]</span>
              return <CitationChip marker={mk} label={citationLabel(citations[i], i + 1)} verified={citations[i].verified !== false} onClick={() => onCite(i)} />
            }
            return <span>{children as string}</span> // links are neutralised
          },
          img: () => null,
        }}
      >{prepared}</ReactMarkdown>
    </div>
  )
}
