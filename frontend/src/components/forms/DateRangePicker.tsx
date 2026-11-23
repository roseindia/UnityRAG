import { endOfMonth, startOfMonth, subDays } from 'date-fns'
import { useMemo, useState } from 'react'
import { Select, Input } from '@/components/ui/form'
import { isoDate } from '@/utils/format'
import type { DateRange } from '@/types/api'

const PRESETS = ['7', '30', '90', 'month', 'custom'] as const
type Preset = (typeof PRESETS)[number]

export function rangeFor(preset: Exclude<Preset, 'custom'>, now = new Date()): DateRange {
  if (preset === 'month') return { start: isoDate(startOfMonth(now)), end: isoDate(now < endOfMonth(now) ? now : endOfMonth(now)) }
  return { start: isoDate(subDays(now, Number(preset) - 1)), end: isoDate(now) }
}

export function defaultRange(): DateRange { return rangeFor('30') }

const labels: Record<Preset, string> = { '7': 'Last 7 days', '30': 'Last 30 days', '90': 'Last 90 days', month: 'This month', custom: 'Custom' }

/** Presets: 7, 30, 90 days, this month, custom. Maximum span is 400 days (backend rule). */
export function DateRangePicker({ value, onChange }: { value: DateRange; onChange: (r: DateRange) => void }) {
  const [preset, setPreset] = useState<Preset>('30')
  const days = useMemo(() => Math.round((Date.parse(value.end) - Date.parse(value.start)) / 86_400_000), [value])
  const invalid = value.start > value.end || days > 400
  return (
    <div className="flex flex-wrap items-end gap-2">
      <label className="text-xs font-medium">Period
        <Select className="mt-1 w-40" value={preset} onChange={(e) => { const p = e.target.value as Preset; setPreset(p); if (p !== 'custom') onChange(rangeFor(p)) }}>
          {PRESETS.map((p) => <option key={p} value={p}>{labels[p]}</option>)}
        </Select>
      </label>
      {preset === 'custom' && (
        <>
          <label className="text-xs font-medium">From <Input type="date" className="mt-1" value={value.start} max={value.end} onChange={(e) => onChange({ ...value, start: e.target.value })} /></label>
          <label className="text-xs font-medium">To <Input type="date" className="mt-1" value={value.end} min={value.start} onChange={(e) => onChange({ ...value, end: e.target.value })} /></label>
        </>
      )}
      {invalid && <p role="alert" className="text-xs text-danger">Choose a start before the end, no more than 400 days apart.</p>}
    </div>
  )
}
