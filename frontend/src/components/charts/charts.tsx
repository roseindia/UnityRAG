import { useState, type ReactNode } from 'react'
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Card, CardHeader } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/feedback/states'
import { formatNumber } from '@/utils/format'

const COLORS = ['#2B4C7E', '#C2571A', '#1D6B3A', '#7A3E9D', '#0E7490', '#9A6700']
const DASH = ['0', '6 3', '2 3', '10 3 2 3', '4 4', '1 4']

export interface Series { key: string; label: string }
type Datum = Record<string, string | number | null | undefined>

/** Chart + "View as table" toggle + text summary (WCAG 1.1.1, Design Document 14.4). */
function ChartFrame({ title, summary, data, xKey, series, children, unit }: {
  title: string; summary: string; data: Datum[]; xKey: string; series: Series[]; children: ReactNode; unit?: string
}) {
  const [table, setTable] = useState(false)
  return (
    <Card>
      <CardHeader title={title} description={summary}
        actions={<Button variant="secondary" size="sm" aria-pressed={table} onClick={() => setTable((t) => !t)}>{table ? 'View as chart' : 'View as table'}</Button>} />
      <div className="p-4">
        {data.length === 0 ? <EmptyState title="No data for this period" description="Values appear here as soon as the platform records activity." />
          : table ? (
            <div className="table-wrap max-h-72 overflow-y-auto">
              <table className="tbl"><caption className="sr-only">{title}{unit ? ` (${unit})` : ''}</caption>
                <thead><tr><th scope="col">{xKey.replace(/_/g, ' ')}</th>{series.map((s) => <th key={s.key} scope="col">{s.label}</th>)}</tr></thead>
                <tbody>{data.map((d, i) => <tr key={i}><td>{String(d[xKey])}</td>{series.map((s) => <td key={s.key}>{typeof d[s.key] === 'number' ? formatNumber(d[s.key] as number) : '–'}</td>)}</tr>)}</tbody>
              </table>
            </div>
          ) : <div className="h-64 w-full" role="img" aria-label={`${title}. ${summary}`}>{children}</div>}
      </div>
    </Card>
  )
}

export function TrendChart({ title, data, xKey, series, unit }: { title: string; data: Datum[]; xKey: string; series: Series[]; unit?: string }) {
  const nums = data.flatMap((d) => series.map((s) => d[s.key]).filter((v): v is number => typeof v === 'number'))
  const summary = data.length ? `${data.length} points from ${data[0][xKey]} to ${data[data.length - 1][xKey]}; peak ${formatNumber(Math.max(0, ...nums))}${unit ? ` ${unit}` : ''}.` : 'No data.'
  return (
    <ChartFrame title={title} summary={summary} data={data} xKey={xKey} series={series} unit={unit}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#D8DEE6" />
          <XAxis dataKey={xKey} tick={{ fontSize: 11 }} minTickGap={24} />
          <YAxis tick={{ fontSize: 11 }} width={48} tickFormatter={(v: number) => formatNumber(v)} />
          <Tooltip />
          <Legend />
          {series.map((s, i) => (
            <Line key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={COLORS[i % COLORS.length]} strokeDasharray={DASH[i % DASH.length]}
              strokeWidth={2} dot={{ r: 2.5 }} isAnimationActive={false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </ChartFrame>
  )
}

export function BarsChart({ title, data, xKey, series, unit, stacked }: { title: string; data: Datum[]; xKey: string; series: Series[]; unit?: string; stacked?: boolean }) {
  const top = data.length ? `${data.length} categories.` : 'No data.'
  return (
    <ChartFrame title={title} summary={top} data={data} xKey={xKey} series={series} unit={unit}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#D8DEE6" />
          <XAxis dataKey={xKey} tick={{ fontSize: 11 }} interval={0} />
          <YAxis tick={{ fontSize: 11 }} width={48} tickFormatter={(v: number) => formatNumber(v)} />
          <Tooltip />
          <Legend />
          {series.map((s, i) => <Bar key={s.key} dataKey={s.key} name={s.label} fill={COLORS[i % COLORS.length]} stackId={stacked ? 'a' : undefined} isAnimationActive={false} />)}
        </BarChart>
      </ResponsiveContainer>
    </ChartFrame>
  )
}
