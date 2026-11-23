import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { baseProfile, renderRoutes, renderScreen } from '../utils'
import { ApiError } from '@/services/api/errors'
import type { Profile } from '@/types/api'

const auth = {
  status: 'anonymous' as 'anonymous' | 'authenticated', profile: null as Profile | null, memberships: [], needsTenantChoice: false, notice: null as string | null, tenantSuspended: false,
  login: vi.fn(), loginWithOidc: vi.fn(), selectTenant: vi.fn(), confirmTenant: vi.fn(), logout: vi.fn(), reloadProfile: vi.fn(),
}
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => auth, AuthProvider: ({ children }: { children: React.ReactNode }) => children }))

const { default: LoginPage } = await import('@/features/authentication/LoginPage')
const { RequireAuth, RequireConsole, RequirePermission } = await import('@/app/guards')

beforeEach(() => {
  Object.assign(auth, { status: 'anonymous', profile: null, notice: null, needsTenantChoice: false, tenantSuspended: false })
  auth.login.mockReset()
})

describe('login workflow', () => {
  it('validates fields before calling the API', async () => {
    renderScreen(<LoginPage />)
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Enter your email address.')).toBeInTheDocument()
    expect(screen.getByText('Enter your password.')).toBeInTheDocument()
    expect(auth.login).not.toHaveBeenCalled()
  })

  it('submits credentials and navigates away on success', async () => {
    auth.login.mockResolvedValue(undefined)
    const { router } = renderRoutes([{ path: '/login', element: <LoginPage /> }, { path: '/', element: <p>home</p> }], '/login')
    await userEvent.type(screen.getByLabelText(/Email/), 'a@b.co')
    await userEvent.type(screen.getByLabelText(/Password/), 'secret-pass')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    await waitFor(() => expect(auth.login).toHaveBeenCalledWith({ email: 'a@b.co', password: 'secret-pass' }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/'))
  })

  it('reveals the 6-digit code field on mfa_required and resubmits with the code', async () => {
    auth.login.mockRejectedValueOnce(new ApiError({ status: 401, code: 'mfa_required' })).mockResolvedValueOnce(undefined)
    renderRoutes([{ path: '/login', element: <LoginPage /> }, { path: '/', element: <p>home</p> }], '/login')
    await userEvent.type(screen.getByLabelText(/Email/), 'a@b.co')
    await userEvent.type(screen.getByLabelText(/Password/), 'pw')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    const code = await screen.findByLabelText(/6-digit code/)
    expect(code).toHaveAttribute('autocomplete', 'one-time-code')
    await userEvent.type(code, '123456')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    await waitFor(() => expect(auth.login).toHaveBeenLastCalledWith({ email: 'a@b.co', password: 'pw', mfa_code: '123456' }))
  })

  it('shows a neutral message for bad credentials and keeps the form', async () => {
    auth.login.mockRejectedValue(new ApiError({ status: 401, code: 'invalid_credentials' }))
    renderScreen(<LoginPage />)
    await userEvent.type(screen.getByLabelText(/Email/), 'a@b.co')
    await userEvent.type(screen.getByLabelText(/Password/), 'wrong')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('The email or password is incorrect.')).toBeInTheDocument()
    expect(screen.getByLabelText(/Email/)).toHaveValue('a@b.co')
  })

  it('shows the lock-out message', async () => {
    auth.login.mockRejectedValue(new ApiError({ status: 401, code: 'account_locked' }))
    renderScreen(<LoginPage />)
    await userEvent.type(screen.getByLabelText(/Email/), 'a@b.co')
    await userEvent.type(screen.getByLabelText(/Password/), 'x')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText(/temporarily locked/)).toBeInTheDocument()
  })

  it('does not follow an unsafe returnTo after sign-in', async () => {
    Object.assign(auth, { status: 'authenticated', profile: baseProfile })
    const { router } = renderRoutes([{ path: '/login', element: <LoginPage /> }, { path: '/', element: <p>home</p> }], '/login?returnTo=%2F%2Fevil.com')
    await waitFor(() => expect(router.state.location.pathname).toBe('/'))
  })
})

describe('protected routes', () => {
  const routes = [
    { path: '/login', element: <p>login page</p> },
    { element: <RequireAuth />, children: [
      { path: '/documents', element: <p>documents page</p> },
      { path: '/search', element: <RequirePermission permission="search.use"><p>search page</p></RequirePermission> },
      { path: '/admin', element: <RequireConsole kind="admin" />, children: [{ index: true, element: <p>admin home</p> }] },
      { path: '/platform', element: <RequireConsole kind="platform" />, children: [{ index: true, element: <p>platform home</p> }] },
    ] },
  ]

  it('redirects anonymous users to /login with the requested page as returnTo', async () => {
    const { router } = renderRoutes(routes, '/documents?x=1')
    expect(await screen.findByText('login page')).toBeInTheDocument()
    expect(router.state.location.search).toBe('?returnTo=%2Fdocuments%3Fx%3D1')
  })

  it('lets an authorised user in', async () => {
    Object.assign(auth, { status: 'authenticated', profile: baseProfile })
    renderRoutes(routes, '/search')
    expect(await screen.findByText('search page')).toBeInTheDocument()
  })

  it('shows "not available" when the permission is missing (direct URL navigation)', async () => {
    Object.assign(auth, { status: 'authenticated', profile: { ...baseProfile, permissions: ['documents.read'] } })
    renderRoutes(routes, '/search')
    expect(await screen.findByText('Not available to you')).toBeInTheDocument()
    expect(screen.queryByText('search page')).not.toBeInTheDocument()
  })

  it('blocks the admin console for a member even when the role code says tenant_admin', async () => {
    Object.assign(auth, { status: 'authenticated', profile: { ...baseProfile, roles: ['tenant_admin'] } })
    renderRoutes(routes, '/admin')
    expect(await screen.findByText('Not available to you')).toBeInTheDocument()
  })

  it('opens the admin console for a user holding an admin permission, but not the platform console', async () => {
    Object.assign(auth, { status: 'authenticated', profile: { ...baseProfile, permissions: ['admin.users.manage'] } })
    const { unmount } = renderRoutes(routes, '/admin')
    expect(await screen.findByText('admin home')).toBeInTheDocument()
    unmount()
    renderRoutes(routes, '/platform')
    expect(await screen.findByText('Not available to you')).toBeInTheDocument()
  })

  it('shows the suspended-organisation page after a tenant_unavailable response', async () => {
    Object.assign(auth, { status: 'authenticated', profile: baseProfile, tenantSuspended: true })
    renderRoutes(routes, '/documents')
    expect(await screen.findByText(/access is suspended/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument()
  })
})
