import { screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { baseProfile, renderScreen } from '../utils'
import type { Profile } from '@/types/api'

const auth = { status: 'authenticated', profile: null as Profile | null, memberships: [], needsTenantChoice: false, notice: null, tenantSuspended: false, login: vi.fn(), loginWithOidc: vi.fn(), selectTenant: vi.fn(), confirmTenant: vi.fn(), logout: vi.fn(), reloadProfile: vi.fn() }
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => auth, AuthProvider: ({ children }: { children: React.ReactNode }) => children }))
const documentApi = vi.hoisted(() => ({ collections: vi.fn(), upload: vi.fn(), bulkUpload: vi.fn(), job: vi.fn() }))
const adminApi = vi.hoisted(() => ({ collections: vi.fn() }))
vi.mock('@/services/api/documentApi', () => ({ documentApi }))
vi.mock('@/services/api/adminApi', () => ({ adminApi }))
const { default: UploadPage } = await import('@/features/documents/UploadPage')

beforeEach(() => {
  vi.clearAllMocks()
  documentApi.collections.mockResolvedValue([])
  adminApi.collections.mockResolvedValue([{ collection_id: 'c1', code: 'c001', name: 'Motor Policy Wordings' }])
})

describe('upload collection list', () => {
  it('shows every tenant collection to an administrator, even one with no access rules yet', async () => {
    auth.profile = { ...baseProfile, permissions: ['documents.upload', 'admin.collections.manage', 'admin.documents.manage'] }
    renderScreen(<UploadPage />)
    expect(await screen.findByRole('option', { name: 'Motor Policy Wordings' })).toBeInTheDocument()
    expect(documentApi.collections).not.toHaveBeenCalled()
  })

  it('shows an ordinary user only the collections their rules allow, with a hint when there are none', async () => {
    auth.profile = { ...baseProfile, permissions: ['documents.upload', 'collections.read'] }
    renderScreen(<UploadPage />)
    expect(await screen.findByText(/No collection is available to you/)).toBeInTheDocument()
    expect(adminApi.collections).not.toHaveBeenCalled()
    expect(screen.queryByRole('option', { name: 'Motor Policy Wordings' })).not.toBeInTheDocument()
  })
})
