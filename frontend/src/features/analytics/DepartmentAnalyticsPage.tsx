import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useAuth } from '@/contexts/AuthContext'
import { adminApi } from '@/services/api/adminApi'
import { DateRangePicker, defaultRange } from '@/components/forms/DateRangePicker'
import { TrendChart } from '@/components/charts/charts'
import { QueryState } from '@/components/feedback/states'
import { KpiTile, PageHeader } from '@/components/common/display'
import { formatCompact, formatCost, formatNumber } from '@/utils/format'
import type { Row } from '@/types/api'

export default function DepartmentAnalyticsPage() {
  const { profile } = useAuth()
  const [range, setRange] = useState(defaultRange)
  const q = useQuery({ queryKey: [profile?.tenant_id, 'dept-analytics', range], queryFn: () => adminApi.departmentAnalytics(range) })
  return (
    <>
      <PageHeader title="Department analytics" description="Aggregates for your own department. Individual questions and answers are never shown." actions={<DateRangePicker value={range} onChange={setRange} />} />
      <QueryState query={q}>
        {(d) => {
          const t = (d.totals ?? {}) as Row
          const series = ((d.series ?? []) as Row[]).map((r) => ({ ...r, usage_date: String(r.usage_date) })) as Record<string, string | number | null>[]
          return (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
                <KpiTile label="Active users" value={formatNumber(d.active_users as number)} />
                <KpiTile label="Searches" value={formatNumber(t.searches as number)} />
                <KpiTile label="Chats" value={formatNumber(t.chats as number)} />
                <KpiTile label="AI tokens" value={formatCompact(t.tokens as number)} />
                <KpiTile label="Estimated cost" value={formatCost(t.estimated_cost as number)} sub={(d.cost_note as string) ?? 'Estimate'} />
              </div>
              <TrendChart title="Daily activity" data={series} xKey="usage_date" series={[{ key: 'searches', label: 'Searches' }, { key: 'chats', label: 'Chats' }, { key: 'active_users', label: 'Active users' }]} />
            </div>
          )
        }}
      </QueryState>
    </>
  )
}
