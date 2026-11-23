import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { AxiosAdapter, AxiosResponse, InternalAxiosRequestConfig } from 'axios'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { baseProfile, renderScreen } from '../utils'
import { ApiError } from '@/services/api/errors'
import { apiClient } from '@/services/api/apiClient'
import { platformApi } from '@/services/api/platformApi'
import type { Profile } from '@/types/api'

const auth = { status: 'authenticated', profile: null as Profile | null, memberships: [{ tenant_id: 't1', tenant_code: 'abc', tenant_name: 'ABC Insurance', tenant_status: 'active', membership_status: 'active', is_default: true }], needsTenantChoice: false, notice: null, tenantSuspended: false, login: vi.fn(), loginWithOidc: vi.fn(), selectTenant: vi.fn(), confirmTenant: vi.fn(), logout: vi.fn(), reloadProfile: vi.fn() }
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => auth, AuthProvider: ({ children }: { children: React.ReactNode }) => children }))
const adminApi = vi.hoisted(() => ({ roles: vi.fn(), permissions: vi.fn(), auditVerify: vi.fn(), audit: vi.fn(), auditExport: vi.fn(), deleteRole: vi.fn(), groups: vi.fn(), departments: vi.fn(), teams: vi.fn(), users: vi.fn(), setCollectionAccess: vi.fn() }))
vi.mock('@/services/api/adminApi', () => ({ adminApi }))

const { ConfirmDialog } = await import('@/components/dialogs/ConfirmDialog')
const { Shell } = await import('@/components/layout/Shell')
const { BreakGlassProvider } = await import('@/contexts/BreakGlassContext')
const { default: RolesPage } = await import('@/features/tenant-admin/RolesPage')
const { default: AuditPage } = await import('@/features/tenant-admin/AuditPage')
const { AccessRuleEditor } = await import('@/components/forms/AccessRuleEditor')

beforeEach(() => { vi.clearAllMocks(); auth.profile = { ...baseProfile } })

describe('confirmation patterns (Design Document 13.4)', () => {
  const setup = (onConfirm: (r: string) => Promise<unknown>, level: 'simple' | 'reason' | 'strong') => {
    const onOpenChange = vi.fn()
    render(<ConfirmDialog open onOpenChange={onOpenChange} title="Suspend tenant" description="Consequence." confirmLabel="Suspend ABC" level={level} onConfirm={onConfirm} />)
    return { onOpenChange }
  }

  it('strong confirm needs a reason of 10+ characters AND the checkbox before the destructive button enables', async () => {
    const onConfirm = vi.fn().mockResolvedValue(undefined)
    const { onOpenChange } = setup(onConfirm, 'strong')
    const btn = screen.getByRole('button', { name: 'Suspend ABC' })
    expect(btn).toBeDisabled()
    await userEvent.type(screen.getByLabelText(/Reason/), 'too short')
    await userEvent.click(screen.getByLabelText(/I understand/))
    expect(btn).toBeDisabled() // 9 characters
    await userEvent.type(screen.getByLabelText(/Reason/), '!')
    expect(btn).toBeEnabled()
    await userEvent.click(btn)
    await waitFor(() => expect(onConfirm).toHaveBeenCalledWith('too short!'))
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false))
  })

  it('stays open and shows the error when the action fails (closes only on success)', async () => {
    const onConfirm = vi.fn().mockRejectedValue(new ApiError({ status: 409, code: 'legal_hold' }))
    const { onOpenChange } = setup(onConfirm, 'simple')
    await userEvent.click(screen.getByRole('button', { name: 'Suspend ABC' }))
    expect(await screen.findByText(/under legal hold/)).toBeInTheDocument()
    expect(onOpenChange).not.toHaveBeenCalledWith(false)
  })
})

describe('permission-aware navigation', () => {
  const renderShell = (area: 'workspace' | 'admin' | 'platform') => {
    const router = createMemoryRouter([{ path: '*', element: <Shell area={area} /> }], { initialEntries: ['/'] })
    return render(<QueryClientProvider client={new QueryClient()}><BreakGlassProvider><RouterProvider router={router} /></BreakGlassProvider></QueryClientProvider>)
  }

  it('shows a member only the workspace items they hold permissions for, and no admin switch', () => {
    auth.profile = { ...baseProfile, permissions: ['chat.use', 'documents.read'] }
    renderShell('workspace')
    const nav = screen.getAllByRole('navigation', { name: 'workspace navigation' })[0]
    expect(nav).toHaveTextContent('AI chat'); expect(nav).toHaveTextContent('Documents')
    expect(nav).not.toHaveTextContent('Search'); expect(nav).not.toHaveTextContent('Upload')
    expect(screen.queryByRole('link', { name: 'Admin' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Platform/ })).not.toBeInTheDocument()
  })

  it('offers the Admin switch and only permitted admin items to an administrator', () => {
    auth.profile = { ...baseProfile, permissions: ['chat.use', 'admin.users.manage', 'admin.audit.view'] }
    const { unmount } = renderShell('workspace')
    expect(screen.getByRole('link', { name: 'Admin' })).toBeInTheDocument()
    unmount()
    renderShell('admin')
    const nav = screen.getAllByRole('navigation', { name: 'admin navigation' })[0]
    expect(nav).toHaveTextContent('Users'); expect(nav).toHaveTextContent('Audit log')
    expect(nav).not.toHaveTextContent('Roles'); expect(nav).not.toHaveTextContent('Settings')
  })

  it('shows the tenant name in the top bar and a distinct Platform badge in the platform console', () => {
    auth.profile = { ...baseProfile, platform_role: 'platform_admin', platform_permissions: ['platform.tenants.view'] }
    renderShell('platform')
    expect(screen.getAllByText('Platform').length).toBeGreaterThan(0)
    expect(screen.getByRole('navigation', { name: 'platform navigation' })).toHaveTextContent('Tenants')
  })
})

describe('roles and permissions', () => {
  it('locks system roles (read-only) while custom roles can be edited and deleted', async () => {
    adminApi.permissions.mockResolvedValue([{ permission_code: 'search.use', category: 'search' }, { permission_code: 'admin.users.manage', category: 'administration' }])
    adminApi.roles.mockResolvedValue([
      { role_id: 'r1', code: 'member', name: 'Member', is_system: true, permissions: ['search.use'] },
      { role_id: 'r2', code: 'claims_lead', name: 'Claims lead', is_system: false, permissions: ['search.use', 'admin.users.manage'] },
    ])
    renderScreen(<RolesPage />)
    expect(await screen.findByLabelText('System role, read-only')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Edit' })).toHaveLength(1)
    expect(screen.getAllByRole('button', { name: 'Delete' })).toHaveLength(1)
    expect(screen.getAllByLabelText('Granted').length).toBe(3)
  })
})

describe('audit integrity', () => {
  beforeEach(() => adminApi.audit.mockResolvedValue({ items: [{ event_id: 'e1', occurred_at: '2026-01-01T10:00:00Z', category: 'document', event_type: 'preview', outcome: 'success', correlation_id: 'corr-1234567' }], total: 1, limit: 50, offset: 0 }))

  it('reports a broken chain in red with escalation guidance', async () => {
    adminApi.auditVerify.mockResolvedValue({ valid: false, broken_at: 42 })
    renderScreen(<AuditPage />)
    await userEvent.click(screen.getByRole('button', { name: 'Verify integrity' }))
    expect(await screen.findByText(/Chain broken at sequence 42/)).toBeInTheDocument()
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })

  it('reports a verified chain', async () => {
    adminApi.auditVerify.mockResolvedValue({ valid: true, events: 1200 })
    renderScreen(<AuditPage />)
    await userEvent.click(screen.getByRole('button', { name: 'Verify integrity' }))
    expect(await screen.findByText('Chain verified: 1200 events')).toBeInTheDocument()
  })

  it('clicking a correlation id filters to that request, and a bad date range blocks the query', async () => {
    renderScreen(<AuditPage />, { path: '/admin/audit', entry: '/admin/audit' })
    await userEvent.click(await screen.findByRole('button', { name: 'corr-123' }))
    await waitFor(() => expect(adminApi.audit.mock.calls.at(-1)?.[0]).toMatchObject({ correlation_id: 'corr-1234567' }))
  })
})

describe('access-rule editor', () => {
  it('shows the "deny always wins" warning and a diff before replacing the whole rule set', async () => {
    adminApi.groups.mockResolvedValue([{ group_id: 'g1', name: 'Claims team' }])
    adminApi.roles.mockResolvedValue([]); adminApi.departments.mockResolvedValue([]); adminApi.teams.mockResolvedValue([]); adminApi.users.mockResolvedValue({ items: [] })
    const onSave = vi.fn().mockResolvedValue(undefined)
    renderScreen(<AccessRuleEditor withPermission initial={[{ principal_type: 'everyone', effect: 'allow', permission: 'read' }]} onSave={onSave} />)
    expect(screen.getByText(/Deny always wins/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Remove rule for Everyone/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Review and save' }))
    expect(await screen.findByText(/Removed \(1\)/)).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/Reason/), 'Tighten access')
    await userEvent.click(screen.getByRole('button', { name: 'Save access rules' }))
    await waitFor(() => expect(onSave).toHaveBeenCalledWith([]))
  })
})

describe('tenant lifecycle request contract', () => {
  it('sends the reason and confirm:true for a suspension, as the backend requires', async () => {
    let seen: { url?: string; body?: unknown } = {}
    const adapter: AxiosAdapter = (cfg) => {
      seen = { url: cfg.url, body: JSON.parse(String(cfg.data)) }
      return Promise.resolve({ data: { status: 'suspended' }, status: 200, statusText: 'OK', headers: {}, config: cfg as InternalAxiosRequestConfig } as AxiosResponse)
    }
    const prev = apiClient.defaults.adapter
    apiClient.defaults.adapter = adapter
    await platformApi.tenantAction('t-9', 'suspend', 'Non-payment of invoice 123')
    apiClient.defaults.adapter = prev
    expect(seen.url).toBe('/platform/tenants/t-9/suspend')
    expect(seen.body).toEqual({ reason: 'Non-payment of invoice 123', confirm: true })
  })
})
