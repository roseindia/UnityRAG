import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { baseProfile, renderScreen } from '../utils'
import { ApiError } from '@/services/api/errors'

const auth = { status: 'authenticated', profile: { ...baseProfile }, memberships: [], needsTenantChoice: false, notice: null, tenantSuspended: false, login: vi.fn(), loginWithOidc: vi.fn(), selectTenant: vi.fn(), confirmTenant: vi.fn(), logout: vi.fn(), reloadProfile: vi.fn() }
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => auth, AuthProvider: ({ children }: { children: React.ReactNode }) => children }))
const adminApi = vi.hoisted(() => ({ collections: vi.fn(), createCollection: vi.fn() }))
vi.mock('@/services/api/adminApi', () => ({ adminApi }))
const { CollectionsPage } = await import('@/features/tenant-admin/CollectionsPage')

beforeEach(() => { vi.clearAllMocks(); adminApi.collections.mockResolvedValue([]) })

const fill = async () => {
  await userEvent.click(await screen.findByRole('button', { name: 'New collection' }))
  await userEvent.type(screen.getByLabelText(/^Code/), 'C001')
  await userEvent.type(screen.getByLabelText(/^Name/), 'Motor Policy Wordings')
  await userEvent.type(screen.getByLabelText(/^Description/), 'Motor Policy Wordings')
  await userEvent.selectOptions(screen.getByLabelText(/Line of business/), 'motor')
}

describe('create collection', () => {
  it('sends the form to the API and shows the new collection', async () => {
    adminApi.createCollection.mockResolvedValue({ collection_id: 'c-1', code: 'C001', name: 'Motor Policy Wordings' })
    renderScreen(<CollectionsPage />, { path: '/admin/collections', entry: '/admin/collections' })
    await fill()
    await userEvent.click(screen.getByRole('button', { name: 'Create collection' }))
    await waitFor(() => expect(adminApi.createCollection).toHaveBeenCalled())
    expect(adminApi.createCollection.mock.calls[0][0]).toMatchObject({ code: 'C001', name: 'Motor Policy Wordings', line_of_business: 'motor', classification: 'internal', auto_publish: true })
  })

  it('shows the server error instead of failing silently', async () => {
    adminApi.createCollection.mockRejectedValue(new ApiError({ status: 429, code: 'quota_exceeded' }))
    renderScreen(<CollectionsPage />, { path: '/admin/collections', entry: '/admin/collections' })
    await fill()
    await userEvent.click(screen.getByRole('button', { name: 'Create collection' }))
    expect(await screen.findByText('The collection was not saved')).toBeInTheDocument()
    expect(screen.getByText(/reached its limit/)).toBeInTheDocument()
  })
})
