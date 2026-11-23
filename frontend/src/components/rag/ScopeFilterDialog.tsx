import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { documentApi } from '@/services/api/documentApi'
import { Modal } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Checkbox, Field, Input } from '@/components/ui/form'
import { LINES_OF_BUSINESS, type Filters } from '@/types/api'
import { humanize } from '@/utils/format'

export function filterSummary(f: Filters): string[] {
  const out: string[] = []
  if (f.collection_ids?.length) out.push(`${f.collection_ids.length} collection${f.collection_ids.length > 1 ? 's' : ''}`)
  if (f.lines_of_business?.length) out.push(f.lines_of_business.map(humanize).join(', '))
  if (f.jurisdictions?.length) out.push(f.jurisdictions.join(', '))
  if (f.as_of) out.push(`as of ${f.as_of}`)
  if (f.include_superseded) out.push('incl. superseded')
  return out
}

const toggle = (list: string[] | undefined, v: string) => (list?.includes(v) ? list.filter((x) => x !== v) : [...(list ?? []), v])

/** Scope filters for chat: collections, line of business, jurisdiction, as-of date. Sent as `filters` (Design Document 10.4). */
export function ScopeFilterDialog({ open, onOpenChange, value, onChange }: { open: boolean; onOpenChange: (o: boolean) => void; value: Filters; onChange: (f: Filters) => void }) {
  const cols = useQuery({ queryKey: ['collections', 'usable'], queryFn: documentApi.collections, staleTime: 5 * 60_000, enabled: open })
  const [draft, setDraft] = useState<Filters>(value)
  const [juris, setJuris] = useState((value.jurisdictions ?? []).join(', '))
  return (
    <Modal open={open} onOpenChange={(o) => { if (o) { setDraft(value); setJuris((value.jurisdictions ?? []).join(', ')) } onOpenChange(o) }} title="Search scope" size="md"
      description="Narrow which approved documents the assistant may use."
      footer={<>
        <Button variant="ghost" onClick={() => { onChange({}); onOpenChange(false) }}>Clear all</Button>
        <Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button>
        <Button onClick={() => {
          const j = juris.split(',').map((s) => s.trim()).filter(Boolean)
          onChange({ ...draft, jurisdictions: j.length ? j : undefined, as_of: draft.as_of || undefined })
          onOpenChange(false)
        }}>Apply</Button>
      </>}>
      <div className="grid gap-4 sm:grid-cols-2">
        <fieldset><legend className="mb-1 text-sm font-medium">Collections</legend>
          {cols.isPending && <p className="text-xs text-ink-muted">Loading…</p>}
          <div className="max-h-40 space-y-1 overflow-y-auto">{cols.data?.map((c) => (
            <Checkbox key={c.collection_id} label={c.name} checked={draft.collection_ids?.includes(c.collection_id) ?? false} onChange={() => setDraft({ ...draft, collection_ids: toggle(draft.collection_ids, c.collection_id) })} />
          ))}</div></fieldset>
        <fieldset><legend className="mb-1 text-sm font-medium">Line of business</legend>
          <div className="grid max-h-40 grid-cols-2 gap-1 overflow-y-auto">{LINES_OF_BUSINESS.map((l) => (
            <Checkbox key={l} label={humanize(l)} checked={draft.lines_of_business?.includes(l) ?? false} onChange={() => setDraft({ ...draft, lines_of_business: toggle(draft.lines_of_business, l) })} />
          ))}</div></fieldset>
        <Field label="Jurisdictions" hint="Comma-separated codes, e.g. UK, IE">{(p) => <Input {...p} value={juris} onChange={(e) => setJuris(e.target.value)} />}</Field>
        <Field label="As-of date" hint="Use documents in force on this date.">{(p) => <Input {...p} type="date" value={draft.as_of ?? ''} onChange={(e) => setDraft({ ...draft, as_of: e.target.value })} />}</Field>
        <Checkbox label="Include superseded versions" checked={draft.include_superseded ?? false} onChange={(e) => setDraft({ ...draft, include_superseded: e.target.checked })} />
      </div>
    </Modal>
  )
}
