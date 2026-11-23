// Platform Admin Console endpoints (/platform/*).
import { get, post, put, clean } from './apiClient'
import type { Dict, DateRange, Page, Row } from '@/types/api'

type Q = Record<string, string | number | boolean | undefined>
const list = <T = Row>(url: string, q?: Q) => get<Page<T>>(url, clean(q ?? {}))
const arr = <T = Row>(url: string, q?: Q) => get<T[]>(url, clean(q ?? {}))

export type TenantAction = 'activate' | 'suspend' | 'deactivate' | 'archive'

export const platformApi = {
  dashboard: (r?: DateRange & { tenant_id?: string }) => get<Row>('/platform/dashboard', clean(r ?? {})),
  analytics: (r?: DateRange) => get<Row>('/platform/analytics', r),
  tenants: (q: Q) => list('/platform/tenants', q),
  createTenant: (b: Dict) => post<Row>('/platform/tenants', b),
  tenant: (id: string) => get<Row>(`/platform/tenants/${id}`),
  updateTenant: (id: string, b: Dict) => put<Row>(`/platform/tenants/${id}`, b),
  /** Strong-confirm lifecycle action: reason (>=10 chars) and confirm:true are required by the backend. */
  tenantAction: (id: string, action: TenantAction, reason: string) => post<Row>(`/platform/tenants/${id}/${action}`, { reason, confirm: true }),
  tenantUsage: (id: string, r?: DateRange) => get<Row>(`/platform/tenants/${id}/usage`, r),
  tenantAudit: (id: string, q: Q) => list(`/platform/tenants/${id}/audit`, q),
  setQuotas: (id: string, b: Dict) => put<Row>(`/platform/tenants/${id}/quotas`, b),
  setFeature: (id: string, flag: string, enabled: boolean) => put<Row>(`/platform/tenants/${id}/features`, { flag, enabled }),
  changePlan: (id: string, plan_code: string, apply_quotas = false) => put<Row>(`/platform/tenants/${id}/subscription`, { plan_code, apply_quotas }),
  tenantAdmins: (id: string) => arr(`/platform/tenants/${id}/admins`),
  addTenantAdmin: (id: string, b: Dict) => post<Row>(`/platform/tenants/${id}/admins`, b),
  plans: () => arr('/platform/plans'),
  upsertPlan: (code: string, b: Dict) => put<Row>(`/platform/plans/${code}`, b),
  providers: () => arr('/platform/ai-providers'),
  createProvider: (b: Dict) => post<Row>('/platform/ai-providers', b),
  updateProvider: (id: string, b: Dict) => put<Row>(`/platform/ai-providers/${id}`, b),
  healthCheck: (id: string) => post<Row>(`/platform/ai-providers/${id}/health-check`),
  models: (purpose?: string) => arr('/platform/models', { purpose }),
  createModel: (b: Dict) => post<Row>('/platform/models', b),
  updateModel: (id: string, b: Dict) => put<Row>(`/platform/models/${id}`, b),
  users: () => arr('/platform/users'),
  setUser: (b: Dict) => put<Row>('/platform/users', b),
  monitoring: () => get<Row>('/platform/monitoring'),
  jobs: () => get<Row>('/platform/jobs'),
  securityEvents: (q: Q) => list('/platform/security-events', q),
  audit: (q: Q) => list('/platform/audit', q),
  settings: () => get<Row>('/platform/settings'),
  putSetting: (key: string, value: unknown) => put<Row>(`/platform/settings/${key}`, { value }),
  openBreakGlass: (b: Dict) => post<Row>('/platform/break-glass', b),
  closeBreakGlass: (grant: string) => post<Row>(`/platform/break-glass/${grant}/close`),
  breakGlassRead: (grant: string, resource: 'documents' | 'document' | 'conversation', resource_id?: string) =>
    get<Row>(`/platform/break-glass/${grant}/${resource}`, clean({ resource_id })),
}
