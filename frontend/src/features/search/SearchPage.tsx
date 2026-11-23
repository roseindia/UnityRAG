import { useQuery } from '@tanstack/react-query'
import { MessageSquare, Search as SearchIcon } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/contexts/AuthContext'
import { searchApi, type SearchMode } from '@/services/api/searchApi'
import { useUrlState } from '@/hooks/useUrlState'
import { Button } from '@/components/ui/button'
import { Card, CardBody, Badge } from '@/components/ui/card'
import { Checkbox, Field, Input, Select } from '@/components/ui/form'
import { EmptyState, ErrorState, LoadingBlock } from '@/components/feedback/states'
import { PageHeader, StatusBadge } from '@/components/common/display'
import { SafeHighlight } from '@/components/common/SafeHighlight'
import { DocumentPreviewDrawer, type PreviewTarget } from '@/components/rag/DocumentPreviewDrawer'
import { RatingButtons, ReportDialog } from '@/components/rag/FeedbackControls'
import { Can } from '@/app/guards'
import { formatDateOnly, humanize } from '@/utils/format'
import type { Facets, Filters, SearchResult } from '@/types/api'

// facet group -> FilterIn field. Groups without a request field cannot filter and are not offered as filters.
const FACET_FIELD: Record<string, keyof Filters> = {
  collection: 'collection_ids', collections: 'collection_ids', document_type: 'document_types', line_of_business: 'lines_of_business',
  lines_of_business: 'lines_of_business', product: 'products', jurisdiction: 'jurisdictions', jurisdictions: 'jurisdictions',
}
const FACET_LABEL: Record<string, string> = { collection: 'Collection', document_type: 'Document type', line_of_business: 'Line of business', product: 'Product', jurisdiction: 'Jurisdiction' }
const DEFAULTS = { q: '', mode: 'hybrid', collection_ids: '', document_types: '', lines_of_business: '', products: '', jurisdictions: '', as_of: '', superseded: '' }

const csv = (s: string) => s.split(',').filter(Boolean)

export function relevanceDots(score: number, max: number): number {
  if (!(max > 0)) return 0
  return Math.max(1, Math.min(5, Math.ceil((Math.max(0, score) / max) * 5)))
}

function ResultCard({ r, max, searchId, explain, onOpen, onAsk }: { r: SearchResult; max: number; searchId: string; explain: boolean; onOpen: () => void; onAsk: () => void }) {
  const dots = relevanceDots(r.rerank_score ?? r.score, max)
  const pages = r.page_from ? (r.page_to && r.page_to !== r.page_from ? `pp. ${r.page_from}–${r.page_to}` : `p. ${r.page_from}`) : null
  const [report, setReport] = useState(false)
  return (
    <li className="rounded-card border border-line bg-surface p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h3 className="font-medium">{r.title}</h3>
        <div className="flex items-center gap-2">
          <StatusBadge value={r.lifecycle_state} />
          <span role="img" aria-label={`Relevance ${dots} of 5`} className="flex gap-0.5">{[1, 2, 3, 4, 5].map((i) => <span key={i} className={`h-2 w-2 rounded-full ${i <= dots ? 'bg-primary' : 'bg-line'}`} />)}</span>
        </div>
      </div>
      <p className="mt-0.5 text-xs text-ink-muted">
        {[r.version_label && `Version ${r.version_label}`, r.section_path, r.clause_ref && `Clause ${r.clause_ref}`, pages, `Effective ${formatDateOnly(r.effective_from)} – ${formatDateOnly(r.effective_to)}`].filter(Boolean).join(' · ')}
      </p>
      <SafeHighlight html={r.highlight} fallback={r.content} className="mt-2 text-sm" />
      {r.low_confidence && <p className="mt-1 text-xs text-warning">Text recognised from a scan; verify against the original.</p>}
      {explain && r.explanation && (
        <details className="mt-2 text-xs" open><summary className="cursor-pointer font-medium">Why this result?</summary>
          <p className="mt-1 text-ink-muted">Matched by: {r.explanation.matched_branches.map(humanize).join(', ') || '–'}. Branch ranks: {Object.entries(r.explanation.branch_ranks).map(([k, v]) => `${k} #${v}`).join(', ') || '–'}. RRF {r.explanation.rrf_score}{r.explanation.rerank_score !== null ? `, rerank ${r.explanation.rerank_score.toFixed?.(3) ?? r.explanation.rerank_score}` : ''}.</p></details>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button size="sm" variant="secondary" onClick={onOpen}>Open passage</Button>
        <Can permission="chat.use"><Button size="sm" variant="secondary" onClick={onAsk}><MessageSquare className="h-3.5 w-3.5" aria-hidden />Ask about this</Button></Can>
        <RatingButtons target={{ search_id: searchId }} />
      </div>
      <ReportDialog open={report} onOpenChange={setReport} target={{ search_id: searchId }} />
    </li>
  )
}

function FacetPanel({ facets, selected, toggle }: { facets: Facets; selected: Record<string, string[]>; toggle: (field: string, v: string) => void }) {
  const groups = Object.entries(facets).filter(([k, v]) => FACET_FIELD[k] && v.length)
  if (!groups.length) return <p className="text-xs text-ink-muted">No filters available for the documents you can see.</p>
  return (
    <div className="space-y-4">
      {groups.map(([k, values]) => {
        const field = FACET_FIELD[k]
        return (
          <fieldset key={k}><legend className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-muted">{FACET_LABEL[k] ?? humanize(k)}</legend>
            <div className="space-y-1">{values.map((v) => (
              <Checkbox key={v.value} label={<>{humanize(v.label)} <span className="text-ink-muted">({v.count})</span></>} checked={selected[field]?.includes(v.value) ?? false} onChange={() => toggle(field, v.value)} />
            ))}</div></fieldset>
        )
      })}
    </div>
  )
}

export default function SearchPage() {
  const { profile } = useAuth()
  const nav = useNavigate()
  const [s, set] = useUrlState(DEFAULTS)
  const [input, setInput] = useState(s.q)
  const [preview, setPreview] = useState<PreviewTarget | null>(null)
  const [explain, setExplain] = useState(() => { try { return localStorage.getItem('erag.search.explain') === '1' } catch { return false } })

  const filters: Filters = useMemo(() => ({
    collection_ids: csv(s.collection_ids), document_types: csv(s.document_types), lines_of_business: csv(s.lines_of_business),
    products: csv(s.products), jurisdictions: csv(s.jurisdictions), as_of: s.as_of || undefined, include_superseded: s.superseded === '1' || undefined,
  }), [s])
  const compact = useMemo(() => Object.fromEntries(Object.entries(filters).filter(([, v]) => (Array.isArray(v) ? v.length : v))) as Filters, [filters])
  const selected: Record<string, string[]> = { collection_ids: csv(s.collection_ids), document_types: csv(s.document_types), lines_of_business: csv(s.lines_of_business), products: csv(s.products), jurisdictions: csv(s.jurisdictions) }

  const facets = useQuery({ queryKey: [profile?.tenant_id, 'search', 'facets'], queryFn: ({ signal }) => searchApi.facets(signal), staleTime: 60_000 })
  const results = useQuery({
    queryKey: [profile?.tenant_id, 'search', s],
    queryFn: ({ signal }) => searchApi.search(s.q, s.mode as SearchMode, compact, 10, true, signal),
    enabled: s.q.trim().length > 0, staleTime: 0, gcTime: 0, retry: false, // results are never cached across navigations
  })
  const max = Math.max(0, ...(results.data?.results.map((r) => r.rerank_score ?? r.score) ?? []))

  const toggle = (field: string, v: string) => {
    const cur = new Set(csv((s as Record<string, string>)[field] ?? ''))
    if (cur.has(v)) cur.delete(v); else cur.add(v)
    set({ [field]: [...cur].join(',') } as Partial<Record<keyof typeof DEFAULTS, string>>)
  }

  return (
    <>
      <PageHeader title="Search" description="Find passages in approved documents. Results only include content you are authorised to see." />
      <form role="search" className="mb-4 flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); set({ q: input.trim() }) }}>
        <Field label="Search approved documents" className="min-w-[240px] flex-1">{(p) => <Input {...p} data-focus-target type="search" maxLength={2000} value={input} onChange={(e) => setInput(e.target.value)} placeholder="e.g. flood damage excess motor comprehensive" />}</Field>
        <Field label="Mode" className="w-36">{(p) => <Select {...p} value={s.mode} onChange={(e) => set({ mode: e.target.value })}><option value="hybrid">Hybrid</option><option value="vector">Semantic</option><option value="fulltext">Keyword</option></Select>}</Field>
        <Button type="submit"><SearchIcon className="h-4 w-4" aria-hidden />Search</Button>
      </form>
      <div className="grid gap-4 lg:grid-cols-[260px_1fr]">
        <aside aria-label="Filters"><Card><CardBody className="space-y-4">
          <h2>Filters</h2>
          {facets.isPending && <LoadingBlock rows={3} />}
          {facets.isError && <ErrorState error={facets.error} onRetry={() => void facets.refetch()} />}
          {facets.data && <FacetPanel facets={facets.data} selected={selected} toggle={toggle} />}
          <Field label="As-of date">{(p) => <Input {...p} type="date" value={s.as_of} onChange={(e) => set({ as_of: e.target.value })} />}</Field>
          <Checkbox label="Include superseded versions" checked={s.superseded === '1'} onChange={(e) => set({ superseded: e.target.checked ? '1' : '' })} />
          <Checkbox label="Show ranking details" checked={explain} onChange={(e) => { setExplain(e.target.checked); try { localStorage.setItem('erag.search.explain', e.target.checked ? '1' : '0') } catch { /* optional */ } }} />
        </CardBody></Card></aside>
        <section aria-live="polite" aria-label="Results">
          {!s.q.trim() && <Card><EmptyState title="Search approved documents" description="Enter a question or keywords above. Hybrid mode combines semantic and keyword matching." icon={<SearchIcon className="h-8 w-8" />} /></Card>}
          {results.isFetching && <Card><LoadingBlock rows={5} /></Card>}
          {results.isError && <Card><ErrorState error={results.error} onRetry={() => void results.refetch()} /></Card>}
          {results.data && !results.isFetching && (
            results.data.results.length === 0 ? (
              <Card><EmptyState title="No authorised passages found" description="Remove filters, check spelling, or report a missing source to the content team." /></Card>
            ) : (
              <>
                <p className="mb-2 text-sm text-ink-muted">{results.data.results.length} passages</p>
                <ul className="space-y-3">{results.data.results.map((r) => (
                  <ResultCard key={r.chunk_id} r={r} max={max} searchId={results.data!.search_id} explain={explain}
                    onOpen={() => setPreview({ documentId: r.document_id, chunkId: r.chunk_id, title: r.title, highlightText: r.content })}
                    onAsk={() => nav('/chat', { state: { ask: `Tell me about ${r.title}${r.section_path ? ` – ${r.section_path}` : ''}`, filters: { document_ids: [r.document_id] } } })} />
                ))}</ul>
                <p className="mt-3 flex items-center gap-2 text-xs text-ink-muted">{results.data.latency_ms} ms {results.data.cache_hit && <Badge>cached</Badge>} · mode {humanize(results.data.mode)}</p>
              </>
            )
          )}
        </section>
      </div>
      <DocumentPreviewDrawer target={preview} onClose={() => setPreview(null)} />
    </>
  )
}
