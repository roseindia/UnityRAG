import { flexRender, getCoreRowModel, useReactTable, type ColumnDef } from '@tanstack/react-table'
import { useMemo, type ReactNode } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Select } from '@/components/ui/form'
import { EmptyState, ErrorState, LoadingBlock } from '@/components/feedback/states'

interface Props<T> {
  columns: ColumnDef<T, unknown>[]
  rows: T[] | undefined
  caption: string
  total?: number
  limit?: number
  offset?: number
  onPage?: (offset: number, limit: number) => void
  loading?: boolean
  error?: unknown
  onRetry?: () => void
  empty?: ReactNode
  rowKey: (r: T) => string
  onRowClick?: (r: T) => void
}

/** Server-paged table (Design Document 6.4). Sorting happens on the server where the endpoint supports it. */
export function DataTable<T>({ columns, rows, caption, total, limit = 50, offset = 0, onPage, loading, error, onRetry, empty, rowKey, onRowClick }: Props<T>) {
  const data = useMemo(() => rows ?? [], [rows])
  const table = useReactTable({ data, columns, getCoreRowModel: getCoreRowModel(), getRowId: (r) => rowKey(r) })
  if (error) return <div className="table-wrap"><ErrorState error={error} onRetry={onRetry} /></div>
  if (loading && !rows) return <div className="table-wrap"><LoadingBlock rows={5} /></div>
  if (rows && rows.length === 0) return <div className="table-wrap">{empty ?? <EmptyState title="No results" description="Try changing the filters." />}</div>
  const t = total ?? data.length
  const from = t === 0 ? 0 : offset + 1
  const to = Math.min(offset + limit, t)
  return (
    <div>
      <div className="table-wrap" aria-busy={loading || undefined}>
        <table className="tbl">
          <caption className="sr-only">{caption}</caption>
          <thead>
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>{hg.headers.map((h) => <th key={h.id} scope="col">{flexRender(h.column.columnDef.header, h.getContext())}</th>)}</tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((r) => (
              <tr key={r.id} className={onRowClick ? 'cursor-pointer' : undefined} onClick={onRowClick ? () => onRowClick(r.original) : undefined}>
                {r.getVisibleCells().map((c) => <td key={c.id}>{flexRender(c.column.columnDef.cell, c.getContext())}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {onPage && (
        <nav className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs text-ink-muted" aria-label="Pagination">
          <span>{from}–{to} of {t}</span>
          <div className="flex items-center gap-2">
            <label className="flex items-center gap-1">Rows
              <Select className="w-20 py-1" value={limit} onChange={(e) => onPage(0, Number(e.target.value))} aria-label="Rows per page">
                {[25, 50, 100].map((n) => <option key={n} value={n}>{n}</option>)}
              </Select>
            </label>
            <Button variant="secondary" size="sm" disabled={offset === 0} onClick={() => onPage(Math.max(0, offset - limit), limit)} aria-label="Previous page"><ChevronLeft className="h-4 w-4" aria-hidden /></Button>
            <Button variant="secondary" size="sm" disabled={offset + limit >= t} onClick={() => onPage(offset + limit, limit)} aria-label="Next page"><ChevronRight className="h-4 w-4" aria-hidden /></Button>
          </div>
        </nav>
      )}
    </div>
  )
}
