import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { queryClient } from '@/app/queryClient'
import { authApi } from '@/services/api/authApi'
import { onSessionEvent, refreshSession } from '@/services/api/apiClient'
import { tokenStore } from '@/services/authentication/tokenStore'
import type { LoginRequest, Membership, Profile, TokenResponse } from '@/types/api'

export type AuthStatus = 'anonymous' | 'authenticated'

interface AuthState {
  status: AuthStatus
  profile: Profile | null
  memberships: Membership[]
  /** More than one active membership and the user has not yet confirmed a tenant. */
  needsTenantChoice: boolean
  /** Reason shown on the login page after a forced sign-out. */
  notice: string | null
  tenantSuspended: boolean
}

interface AuthApi extends AuthState {
  login: (r: LoginRequest) => Promise<void>
  loginWithOidc: (idToken: string) => Promise<void>
  selectTenant: (tenantId: string) => Promise<void>
  confirmTenant: () => void
  logout: (notice?: string) => Promise<void>
  reloadProfile: () => Promise<void>
}

const initial: AuthState = { status: 'anonymous', profile: null, memberships: [], needsTenantChoice: false, notice: null, tenantSuspended: false }
const Ctx = createContext<AuthApi | null>(null)

const activeCount = (m: Membership[]) => m.filter((x) => x.membership_status === 'active' && x.tenant_status === 'active').length

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>(initial)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  const wipe = useCallback((notice: string | null) => {
    clearTimeout(timer.current)
    tokenStore.clear()
    queryClient.cancelQueries()
    queryClient.clear() // tenant data must never survive logout / switch
    setState({ ...initial, notice })
  }, [])

  const scheduleRefresh = useCallback(() => {
    clearTimeout(timer.current)
    const exp = tokenStore.expiresAt
    if (!exp) return
    const wait = Math.max(5_000, exp - Date.now() - 60_000)
    timer.current = setTimeout(async () => {
      if (await refreshSession()) scheduleRefresh()
    }, wait)
  }, [])

  const loadProfile = useCallback(async (tr: TokenResponse, choose: boolean) => {
    tokenStore.set(tr.access_token, tr.refresh_token, tr.expires_at)
    const profile = await authApi.me()
    scheduleRefresh()
    setState({
      status: 'authenticated', profile, memberships: tr.memberships ?? [],
      needsTenantChoice: choose && activeCount(tr.memberships ?? []) > 1, notice: null, tenantSuspended: false,
    })
  }, [scheduleRefresh])

  const login = useCallback(async (r: LoginRequest) => {
    const tr = await authApi.login(r)
    queryClient.clear()
    await loadProfile(tr, true)
  }, [loadProfile])

  const loginWithOidc = useCallback(async (idToken: string) => {
    const tr = await authApi.oidcExchange(idToken)
    queryClient.clear()
    await loadProfile(tr, true)
  }, [loadProfile])

  const selectTenant = useCallback(async (tenantId: string) => {
    const tr = await authApi.selectTenant(tenantId)
    await queryClient.cancelQueries()
    queryClient.clear()
    try { sessionStorage.clear() } catch { /* storage may be unavailable */ }
    await loadProfile(tr, false)
  }, [loadProfile])

  const confirmTenant = useCallback(() => setState((s) => ({ ...s, needsTenantChoice: false })), [])

  const logout = useCallback(async (notice?: string) => {
    try { if (tokenStore.access) await authApi.logout() } catch { /* the session is cleared locally regardless */ }
    try { sessionStorage.clear() } catch { /* ignore */ }
    wipe(notice ?? 'You have signed out.')
  }, [wipe])

  const reloadProfile = useCallback(async () => {
    const profile = await authApi.me()
    setState((s) => ({ ...s, profile }))
  }, [])

  useEffect(() => onSessionEvent((e, reason) => {
    if (e === 'expired') wipe(reason ?? 'Your session has expired. Please sign in again.')
    if (e === 'tenant_unavailable') setState((s) => ({ ...s, tenantSuspended: true }))
  }), [wipe])

  // Share logout between tabs of the same origin.
  useEffect(() => {
    if (typeof BroadcastChannel === 'undefined') return
    const ch = new BroadcastChannel('erag-auth')
    ch.onmessage = (m) => { if (m.data === 'logout') wipe('You have signed out.') }
    return () => ch.close()
  }, [wipe])

  const value = useMemo<AuthApi>(() => ({
    ...state, login, loginWithOidc, selectTenant, confirmTenant, logout, reloadProfile,
  }), [state, login, loginWithOidc, selectTenant, confirmTenant, logout, reloadProfile])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useAuth(): AuthApi {
  const v = useContext(Ctx)
  if (!v) throw new Error('useAuth must be used inside <AuthProvider>')
  return v
}
