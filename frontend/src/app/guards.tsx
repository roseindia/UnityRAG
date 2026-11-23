import { Navigate, Outlet, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useAuth } from '@/contexts/AuthContext'
import { usePermissions } from '@/hooks/usePermissions'
import { Button } from '@/components/ui/button'
import { Link } from 'react-router-dom'
import { ShieldOff } from 'lucide-react'

export function NotAvailable({ title = 'Not available to you', body = "You don't have access to this page, or it is no longer available. If you think this is a mistake, contact your administrator." }: { title?: string; body?: string }) {
  return (
    <div role="alert" className="mx-auto mt-16 max-w-md text-center">
      <ShieldOff className="mx-auto h-10 w-10 text-ink-muted" aria-hidden />
      <h1 className="mt-3">{title}</h1>
      <p className="mt-1 text-ink-muted">{body}</p>
      <Button asChild className="mt-4"><Link to="/">Back to home</Link></Button>
    </div>
  )
}

export function SuspendedTenant() {
  const { logout } = useAuth()
  return (
    <div role="alert" className="mx-auto mt-24 max-w-md text-center">
      <ShieldOff className="mx-auto h-10 w-10 text-danger" aria-hidden />
      <h1 className="mt-3">Your organisation's access is suspended</h1>
      <p className="mt-1 text-ink-muted">Please contact your administrator. You can sign out and try again later.</p>
      <Button className="mt-4" onClick={() => { void logout() }}>Sign out</Button>
    </div>
  )
}

/** A session must exist; otherwise redirect to /login?returnTo=… (validated on the login page). */
export function RequireAuth() {
  const { status, needsTenantChoice, tenantSuspended } = useAuth()
  const loc = useLocation()
  if (status !== 'authenticated') {
    return <Navigate to={`/login?returnTo=${encodeURIComponent(loc.pathname + loc.search)}`} replace />
  }
  if (tenantSuspended) return <SuspendedTenant />
  if (needsTenantChoice && loc.pathname !== '/select-tenant') return <Navigate to="/select-tenant" replace state={{ from: loc.pathname + loc.search }} />
  return <Outlet />
}

export function RequireConsole({ kind }: { kind: 'admin' | 'platform' }) {
  const p = usePermissions()
  const ok = kind === 'admin' ? p.hasAdminAccess : p.hasPlatformAccess
  return ok ? <Outlet /> : <NotAvailable />
}

/** Visibility is a convenience; the backend authorises every request again. */
export function RequirePermission({ permission, anyOf, platform, children }: { permission?: string; anyOf?: string[]; platform?: string[]; children: ReactNode }) {
  const p = usePermissions()
  const list = anyOf ?? (permission ? [permission] : [])
  const ok = platform ? p.platformCanAny(platform) : list.length === 0 || p.canAny(list)
  return ok ? <>{children}</> : <NotAvailable />
}

/** Conditional UI: <Can permission="…">…</Can> */
export function Can({ permission, anyOf, platform, children, fallback = null }: { permission?: string; anyOf?: string[]; platform?: string; children: ReactNode; fallback?: ReactNode }) {
  const p = usePermissions()
  const ok = platform ? p.platformCan(platform) : anyOf ? p.canAny(anyOf) : permission ? p.can(permission) : true
  return ok ? <>{children}</> : <>{fallback}</>
}
