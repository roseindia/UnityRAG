import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { baseProfile, renderScreen } from '../utils'

const auth = { status: 'authenticated', profile: { ...baseProfile }, memberships: [], needsTenantChoice: false, notice: null, tenantSuspended: false, login: vi.fn(), loginWithOidc: vi.fn(), selectTenant: vi.fn(), confirmTenant: vi.fn(), logout: vi.fn(), reloadProfile: vi.fn() }
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => auth, AuthProvider: ({ children }: { children: React.ReactNode }) => children }))
const platformApi = vi.hoisted(() => ({ plans: vi.fn(), createTenant: vi.fn() }))
vi.mock('@/services/api/platformApi', () => ({ platformApi }))
const { TenantNewPage } = await import('@/features/platform-admin/TenantsPage')

beforeEach(() => {
  vi.clearAllMocks()
  platformApi.plans.mockResolvedValue([{ code: 'professional', name: 'Professional' }])
})

describe('create tenant wizard', () => {
  it('moves through all four steps and creates the tenant', async () => {
    platformApi.createTenant.mockResolvedValue({ tenant: { tenant_id: 't1' } })
    renderScreen(<TenantNewPage />, { path: '/platform/tenants/new', entry: '/platform/tenants/new' })
    await userEvent.type(screen.getByLabelText(/Tenant code/), 'rose-india')
    await userEvent.type(screen.getByLabelText(/^Name/), 'Rose India')
    await userEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(await screen.findByText(/Step 2 of 4: Plan/)).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText(/^Plan/), 'professional')
    await userEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(await screen.findByText(/Step 3 of 4/)).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/Administrator email/), 'a@b.co')
    await userEvent.type(screen.getByLabelText(/Administrator name/), 'Admin')
    await userEvent.type(screen.getByLabelText(/Initial password/), 'Str0ng#Passw0rd')
    await userEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(await screen.findByText(/Step 4 of 4: Review/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Create tenant' }))
    await waitFor(() => expect(platformApi.createTenant).toHaveBeenCalled())
  })
})
