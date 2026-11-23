// Tenant Admin Console endpoints (/admin/*). Every call is authorised by the backend again.
import { del, downloadBlob, get, post, put, clean } from './apiClient'
import type { Dict, DocumentRow, IngestionJob, Message, Page, Row, DateRange } from '@/types/api'

type Q = Record<string, string | number | boolean | undefined>
const list = <T = Row>(url: string, q?: Q, signal?: AbortSignal) => get<Page<T>>(url, clean(q ?? {}), { signal })
const arr = <T = Row>(url: string, q?: Q) => get<T[]>(url, clean(q ?? {}))

export const adminApi = {
  dashboard: (r?: DateRange) => get<Dict>('/admin/dashboard', r),
  // users
  users: (q: Q, signal?: AbortSignal) => list('/admin/users', q, signal),
  user: (id: string) => get<Row>(`/admin/users/${id}`),
  createUser: (b: Dict) => post<Row>('/admin/users', b),
  updateUser: (id: string, b: Dict) => put<Row>(`/admin/users/${id}`, b),
  activateUser: (id: string) => post<Row>(`/admin/users/${id}/activate`),
  deactivateUser: (id: string) => post<Row>(`/admin/users/${id}/deactivate`),
  revokeSessions: (id: string) => post<Message>(`/admin/users/${id}/revoke-sessions`),
  passwordReset: (id: string) => post<Row>(`/admin/users/${id}/password-reset`),
  assignRole: (id: string, role_id: string) => post<Message>(`/admin/users/${id}/roles`, { role_id }),
  unassignRole: (id: string, role_id: string) => del<Message>(`/admin/users/${id}/roles/${role_id}`),
  userActivity: (id: string) => get<Row>(`/admin/users/${id}/activity`),
  userLogins: (id: string) => arr(`/admin/users/${id}/logins`),
  effectivePermissions: (id: string) => get<Row>(`/admin/permissions/effective/${id}`),
  // roles
  roles: () => arr('/admin/roles'),
  permissions: () => arr('/admin/permissions'),
  createRole: (b: Dict) => post<Row>('/admin/roles', b),
  updateRole: (id: string, b: Dict) => put<Row>(`/admin/roles/${id}`, b),
  deleteRole: (id: string) => del<Message>(`/admin/roles/${id}`),
  // org
  departments: () => arr('/admin/departments'),
  createDepartment: (b: Dict) => post<Row>('/admin/departments', b),
  updateDepartment: (id: string, b: Dict) => put<Row>(`/admin/departments/${id}`, b),
  departmentUsage: (id: string, r?: DateRange) => get<Row>(`/admin/departments/${id}/usage`, r),
  teams: (department_id?: string) => arr('/admin/teams', { department_id }),
  createTeam: (b: Dict) => post<Row>('/admin/teams', b),
  addTeamMember: (id: string, user_id: string) => post<Message>(`/admin/teams/${id}/members`, { user_id }),
  groups: () => arr('/admin/groups'),
  createGroup: (b: Dict) => post<Row>('/admin/groups', b),
  groupMembers: (id: string) => arr(`/admin/groups/${id}/members`),
  addGroupMember: (id: string, user_id: string) => post<Message>(`/admin/groups/${id}/members`, { user_id }),
  removeGroupMember: (id: string, user_id: string) => del<Message>(`/admin/groups/${id}/members/${user_id}`),
  // collections
  collections: () => arr('/admin/collections'),
  collection: (id: string) => get<Row>(`/admin/collections/${id}`),
  createCollection: (b: Dict) => post<Row>('/admin/collections', b),
  updateCollection: (id: string, b: Dict) => put<Row>(`/admin/collections/${id}`, b),
  deleteCollection: (id: string) => del<Message>(`/admin/collections/${id}`),
  setCollectionAccess: (id: string, rules: Dict[]) => put<Row>(`/admin/collections/${id}/access`, rules),
  collectionStats: (id: string) => get<Row>(`/admin/collections/${id}/stats`),
  // documents
  documents: (q: Q, signal?: AbortSignal) => list<DocumentRow>('/admin/documents', q, signal),
  document: (id: string) => get<Row>(`/admin/documents/${id}`),
  setDocumentAccess: (id: string, rules: Dict[]) => put<Row>(`/admin/documents/${id}/access`, rules),
  legalHold: (id: string, hold: boolean, reason: string) => post<Message>(`/admin/documents/${id}/legal-hold`, { hold, reason }),
  lifecycle: (id: string, state: string, reason?: string) => post<Row>(`/admin/documents/${id}/lifecycle`, { state, reason }),
  reprocess: (id: string) => post<Row>(`/admin/documents/${id}/reprocess`),
  reindex: (id: string) => post<Row>(`/admin/documents/${id}/reindex`),
  // ingestion
  ingestionSummary: () => get<Row>('/admin/ingestion/summary'),
  ingestionJobs: (q: Q, signal?: AbortSignal) => list<IngestionJob>('/admin/ingestion/jobs', q, signal),
  retryJob: (id: string) => post<Row>(`/admin/ingestion/jobs/${id}/retry`),
  cancelJob: (id: string) => post<Row>(`/admin/ingestion/jobs/${id}/cancel`),
  // config + settings
  config: () => get<Row>('/admin/config'),
  putConfig: (b: { ai?: Dict; rag?: Dict }) => put<Row>('/admin/config', b),
  putAi: (b: Dict) => put<Row>('/admin/config/ai', b),
  putRag: (b: Dict) => put<Row>('/admin/config/rag', b),
  configHistory: (kind: 'ai' | 'rag') => arr(`/admin/config/history/${kind}`),
  rollback: (kind: 'ai' | 'rag', version: number) => post<Row>(`/admin/config/rollback/${kind}/${version}`),
  settings: () => get<Row>('/admin/settings'),
  putSettings: (b: Dict) => put<Row>('/admin/settings', b),
  // feedback
  feedback: (q: Q) => list('/admin/feedback', q),
  updateFeedback: (id: string, b: Dict) => put<Row>(`/admin/feedback/${id}`, b),
  // analytics
  analytics: (r?: DateRange) => get<Row>('/admin/analytics', r),
  searchAnalytics: (r?: DateRange) => get<Row>('/admin/analytics/search', r),
  chatAnalytics: (r?: DateRange) => get<Row>('/admin/analytics/chat', r),
  usage: (r?: DateRange) => get<Row>('/admin/usage', r),
  departmentAnalytics: (r?: DateRange) => get<Row>('/analytics/department', r),
  report: (name: string, r?: DateRange) => downloadBlob(`/admin/reports/${name}.csv`, r, `${name}.csv`),
  // audit
  audit: (q: Q, signal?: AbortSignal) => list('/admin/audit', q, signal),
  auditExport: (q: Q) => downloadBlob('/admin/audit/export.csv', clean(q), 'audit.csv'),
  auditVerify: () => get<Row>('/admin/audit/verify'),
  // evaluation
  datasets: () => arr('/admin/evaluation/datasets'),
  dataset: (id: string) => get<Row>(`/admin/evaluation/datasets/${id}`),
  createDataset: (b: Dict) => post<Row>('/admin/evaluation/datasets', b),
  addQuestions: (id: string, qs: Dict[]) => post<Row>(`/admin/evaluation/datasets/${id}/questions`, qs),
  approveDataset: (id: string) => post<Row>(`/admin/evaluation/datasets/${id}/approve`),
  runEvaluation: (id: string, b: Dict) => post<Row>(`/admin/evaluation/datasets/${id}/runs`, b, { timeout: 600_000 }),
  runs: (dataset_id?: string) => arr('/admin/evaluation/runs', { dataset_id }),
  run: (id: string) => get<Row>(`/admin/evaluation/runs/${id}`),
}
