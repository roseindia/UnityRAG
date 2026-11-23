import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { baseProfile, renderScreen } from '../utils'
import { contrastOnWhite, accentAllowed } from '@/utils/contrast'

const auth = { status: 'authenticated', profile: { ...baseProfile }, memberships: [], needsTenantChoice: false, notice: null, tenantSuspended: false, login: vi.fn(), loginWithOidc: vi.fn(), selectTenant: vi.fn(), confirmTenant: vi.fn(), logout: vi.fn(), reloadProfile: vi.fn() }
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => auth, AuthProvider: ({ children }: { children: React.ReactNode }) => children }))
const adminApi = vi.hoisted(() => ({ departments: vi.fn(), teams: vi.fn(), users: vi.fn(), updateDepartment: vi.fn(), addTeamMember: vi.fn(), createDepartment: vi.fn(), createTeam: vi.fn(), departmentUsage: vi.fn() }))
const platformApi = vi.hoisted(() => ({ tenant: vi.fn(), tenantUsage: vi.fn(), updateTenant: vi.fn(), tenantAudit: vi.fn(), plans: vi.fn(), analytics: vi.fn(), dashboard: vi.fn() }))
const chatApi = vi.hoisted(() => ({ conversation: vi.fn(), sources: vi.fn(), conversations: vi.fn(), stream: vi.fn(), feedback: vi.fn() }))
vi.mock('@/services/api/adminApi', () => ({ adminApi }))
vi.mock('@/services/api/platformApi', () => ({ platformApi }))
vi.mock('@/services/api/chatApi', () => ({ chatApi }))

const { OrganisationPage } = await import('@/features/tenant-admin/OrganisationPage')
const { default: TenantDetailPage } = await import('@/features/platform-admin/TenantDetailPage')
const { default: PlatformDashboardPage } = await import('@/features/platform-admin/PlatformDashboardPage')
const { default: ChatPage } = await import('@/features/chat/ChatPage')

beforeEach(() => {
  vi.clearAllMocks()
  auth.profile = { ...baseProfile, platform_role: 'platform_admin', platform_permissions: ['platform.tenants.view', 'platform.tenants.manage', 'platform.audit.view'], permissions: ['admin.departments.manage', 'chat.use'] }
})

describe('contrast rule for tenant accent colours', () => {
  it('computes WCAG contrast on white', () => {
    expect(contrastOnWhite('#000000')).toBeCloseTo(21, 0)
    expect(contrastOnWhite('#2B4C7E')).toBeGreaterThan(8)
    expect(contrastOnWhite('nope')).toBeNull()
  })
  it('rejects low-contrast accents', () => { expect(accentAllowed('#2B4C7E')).toBe(true); expect(accentAllowed('#FFD54F')).toBe(false) })
})

describe('departments and teams', () => {
  beforeEach(() => {
    adminApi.departments.mockResolvedValue([{ department_id: 'd1', code: 'CLM', name: 'Claims', status: 'active', user_count: 3, team_count: 1 }])
    adminApi.teams.mockResolvedValue([{ team_id: 'tm1', department_id: 'd1', name: 'Motor claims', members: 2 }])
    adminApi.users.mockResolvedValue({ items: [{ user_id: 'u9', display_name: 'Ana Ruiz', email: 'ana@example.test' }], total: 1, limit: 8, offset: 0 })
  })

  it('edits a department (name and status) through the API', async () => {
    adminApi.updateDepartment.mockResolvedValue({})
    renderScreen(<OrganisationPage />)
    await userEvent.click(await screen.findByRole('button', { name: 'Edit' }))
    const name = screen.getByLabelText(/Name/)
    await userEvent.clear(name); await userEvent.type(name, 'Claims & Recovery')
    await userEvent.selectOptions(screen.getByLabelText('Status'), 'inactive')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(adminApi.updateDepartment).toHaveBeenCalledWith('d1', { name: 'Claims & Recovery', description: '', status: 'inactive' }))
  })

  it('blocks saving a department with an empty name', async () => {
    renderScreen(<OrganisationPage />)
    await userEvent.click(await screen.findByRole('button', { name: 'Edit' }))
    await userEvent.clear(screen.getByLabelText(/Name/))
    expect(screen.getByText('Enter a name.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  })

  it('finds a user and adds them to a team', async () => {
    adminApi.addTeamMember.mockResolvedValue({ message: 'ok' })
    renderScreen(<OrganisationPage />)
    await userEvent.click(await screen.findByRole('button', { name: 'Add member' }))
    await userEvent.type(screen.getByLabelText(/Find a user/), 'ana')
    const row = (await screen.findByText('Ana Ruiz')).closest('li') as HTMLElement
    await userEvent.click(within(row).getByRole('button', { name: 'Add' }))
    await waitFor(() => expect(adminApi.addTeamMember).toHaveBeenCalledWith('tm1', 'u9'))
  })
})

describe('platform tenant profile and usage', () => {
  const tenant = { tenant_id: 't9', code: 'abc', name: 'ABC Insurance', status: 'active', legal_entity: 'ABC Ltd', home_region: 'eu-west', branding: { accent_color: '#2B4C7E' }, quotas: [], features: {}, subscriptions: [] }
  beforeEach(() => { platformApi.tenant.mockResolvedValue(tenant); platformApi.tenantUsage.mockResolvedValue({ series: [{ usage_date: '2026-11-01', searches: 5, chats: 2, active_users: 1 }], quotas: [{ metric: 'users', used: 5, limit: 10, pct: 50 }], cost_note: 'Estimate' }) })

  it('saves profile changes, keeping existing branding keys', async () => {
    platformApi.updateTenant.mockResolvedValue(tenant)
    renderScreen(<TenantDetailPage />, { path: '/platform/tenants/:id', entry: '/platform/tenants/t9' })
    await userEvent.click(await screen.findByRole('button', { name: 'Edit profile' }))
    const name = screen.getByLabelText(/^Name/)
    await userEvent.clear(name); await userEvent.type(name, 'ABC Group')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(platformApi.updateTenant).toHaveBeenCalledWith('t9', { name: 'ABC Group', legal_entity: 'ABC Ltd', home_region: 'eu-west', branding: { accent_color: '#2B4C7E' } }))
  })

  it('refuses a low-contrast accent colour and an http logo', async () => {
    renderScreen(<TenantDetailPage />, { path: '/platform/tenants/:id', entry: '/platform/tenants/t9' })
    await userEvent.click(await screen.findByRole('button', { name: 'Edit profile' }))
    const accent = screen.getByLabelText(/Accent colour/)
    await userEvent.clear(accent); await userEvent.type(accent, '#FFD54F')
    expect(await screen.findByText(/Contrast is/)).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/Logo URL/), 'http://x.test/logo.png')
    expect(screen.getByText('Must start with https://')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  })

  it('loads the usage tab from the usage endpoint with the chosen range', async () => {
    renderScreen(<TenantDetailPage />, { path: '/platform/tenants/:id', entry: '/platform/tenants/t9?tab=usage' })
    expect(await screen.findByText('Quota utilisation')).toBeInTheDocument()
    expect(platformApi.tenantUsage.mock.calls[0][0]).toBe('t9')
    expect(platformApi.tenantUsage.mock.calls[0][1]).toMatchObject({ start: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/), end: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/) })
  })
})

describe('platform dashboard tenant comparison', () => {
  it('shows per-tenant aggregates from the analytics endpoint', async () => {
    platformApi.dashboard.mockResolvedValue({ tenants: {}, users: {}, content: {}, usage: {}, series: [], top_tenants: [], recent_events: [], health: {}, alerts: [] })
    platformApi.analytics.mockResolvedValue({ tenants: [{ tenant_id: 't1', code: 'abc', name: 'ABC Motor', status: 'active', searches: 120, chats: 40, tokens: 2_500_000, peak_active_users: 9, avg_search_latency_ms: 150, estimated_cost: 12.5 }] })
    renderScreen(<PlatformDashboardPage />)
    expect(await screen.findByRole('link', { name: /ABC Motor/ })).toHaveAttribute('href', '/platform/tenants/t1')
    expect(screen.getByText('2.5M')).toBeInTheDocument()
    expect(screen.getByText('150 ms')).toBeInTheDocument()
  })
})

describe('stored conversations re-verify their sources', () => {
  it('fetches the latest answer\'s sources and shows the re-verified details', async () => {
    chatApi.conversations.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 })
    chatApi.conversation.mockResolvedValue({ conversation_id: 'cv1', title: 't', message_count: 2, created_at: '', updated_at: '', messages: [
      { message_id: 'm1', seq: 1, role: 'user', content: 'q', created_at: '' },
      { message_id: 'm2', seq: 2, role: 'assistant', content: 'Covered [S1]', answer_status: 'answered', evidence_strength: 'high', created_at: '', citations: [{ ordinal: 1, document_id: 'd1', title: 'Old title', verified: true }] },
    ] })
    chatApi.sources.mockResolvedValue([{ marker: 'S1', document_id: 'd1', title: 'Policy (re-verified)', version_label: '2026.2', verified: false }])
    renderScreen(<ChatPage />, { path: '/chat/:conversationId?', entry: '/chat/cv1' })
    await waitFor(() => expect(chatApi.sources).toHaveBeenCalledWith('cv1', 'm2'))
    await userEvent.click(await screen.findByText(/Sources \(1\)/))
    expect(await screen.findByText(/Policy \(re-verified\)/)).toBeInTheDocument()
    expect(screen.getByText(/Could not verify this source/)).toBeInTheDocument()
  })
})
