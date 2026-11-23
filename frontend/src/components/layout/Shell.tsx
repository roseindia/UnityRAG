import { ChevronRight, LogOut, Menu as MenuIcon, PanelLeftClose, PanelLeftOpen, User, WifiOff, X, HelpCircle, Shield } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { ADMIN_NAV, CRUMB_LABELS, PLATFORM_NAV, WORKSPACE_NAV, type NavGroup } from '@/constants/navigation'
import { useAuth } from '@/contexts/AuthContext'
import { useBreakGlass } from '@/contexts/BreakGlassContext'
import { usePermissions } from '@/hooks/usePermissions'
import { useOnline } from '@/hooks/useMisc'
import { Button } from '@/components/ui/button'
import { Menu } from '@/components/ui/menu'
import { Modal } from '@/components/ui/dialog'
import { Banner } from '@/components/feedback/states'
import { IdleWatcher } from '@/components/layout/IdleWatcher'
import { env } from '@/config/env'
import { cn } from '@/utils/cn'
import { homeFor } from '@/utils/returnTo'
import { platformApi } from '@/services/api/platformApi'
import { toast } from 'sonner'

type Area = 'workspace' | 'admin' | 'platform'
const NAVS: Record<Area, NavGroup[]> = { workspace: WORKSPACE_NAV, admin: ADMIN_NAV, platform: PLATFORM_NAV }

function Crumbs({ area }: { area: Area }) {
  const { pathname } = useLocation()
  if (area === 'workspace') return null
  const parts = pathname.split('/').filter(Boolean)
  let acc = ''
  return (
    <nav aria-label="Breadcrumb" className="mb-3 flex flex-wrap items-center gap-1 text-xs text-ink-muted">
      {parts.map((p, i) => {
        acc += `/${p}`
        const label = CRUMB_LABELS[p] ?? (p.length > 12 ? `${p.slice(0, 8)}…` : p)
        const last = i === parts.length - 1
        return (
          <span key={acc} className="flex items-center gap-1">
            {i > 0 && <ChevronRight className="h-3 w-3" aria-hidden />}
            {last ? <span aria-current="page" className="font-medium text-ink">{label}</span> : <Link to={acc} className="hover:underline">{label}</Link>}
          </span>
        )
      })}
    </nav>
  )
}

const SHORTCUTS = [
  ['/', 'Focus the search box or chat composer'], ['Enter / Shift+Enter', 'Send / new line in chat'], ['Esc', 'Stop streaming, close a drawer or dialog'],
  ['Alt+1…9', 'Jump to citation S1…S9 in the latest answer'], ['g then h / c / s / a', 'Go to Home, Chat, Search, Admin'], ['?', 'Show this help'],
]

export function Shell({ area }: { area: Area }) {
  const { profile, memberships, logout, selectTenant } = useAuth()
  const perms = usePermissions()
  const nav = useNavigate()
  const online = useOnline()
  const { grant, end } = useBreakGlass()
  const [collapsed, setCollapsed] = useState(() => { try { return localStorage.getItem('erag.nav.collapsed') === '1' } catch { return false } })
  const [drawer, setDrawer] = useState(false)
  const [help, setHelp] = useState(false)
  const [shortcutsOn] = useState(() => { try { return localStorage.getItem('erag.shortcuts') !== 'off' } catch { return true } })
  const { pathname } = useLocation()
  const isPlatform = area === 'platform'

  useEffect(() => { setDrawer(false) }, [pathname])
  useEffect(() => { try { localStorage.setItem('erag.nav.collapsed', collapsed ? '1' : '0') } catch { /* non-sensitive preference */ } }, [collapsed])

  // Keyboard shortcuts (Design Document 15.1). Disabled while typing.
  useEffect(() => {
    if (!shortcutsOn) return
    let pending = false
    const h = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement
      if (el.closest('input, textarea, select, [contenteditable=true]') || e.ctrlKey || e.metaKey) return
      if (e.key === '/') { const t = document.querySelector<HTMLElement>('[data-focus-target]'); if (t) { e.preventDefault(); t.focus() } return }
      if (e.key === '?') { setHelp(true); return }
      if (pending) {
        pending = false
        const m: Record<string, string> = { h: '/', c: '/chat', s: '/search', a: '/admin' }
        if (m[e.key]) nav(m[e.key])
        return
      }
      if (e.key === 'g') { pending = true; setTimeout(() => { pending = false }, 1200) }
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [nav, shortcutsOn])

  const groups = useMemo(() => NAVS[area].map((g) => ({
    ...g,
    items: g.items.filter((i) => (i.platformAnyOf ? perms.platformCanAny(i.platformAnyOf) : !i.anyOf || perms.canAny(i.anyOf))),
  })).filter((g) => g.items.length), [area, perms])

  const activeTenant = memberships.find((m) => m.tenant_id === profile?.tenant_id)
  const canSwitchArea = {
    workspace: perms.can('chat.use') || perms.can('search.use'),
    admin: perms.hasAdminAccess,
    platform: perms.hasPlatformAccess,
  }

  const sidebar = (
    <div className={cn('on-dark flex h-full flex-col text-nav-text', isPlatform ? 'bg-nav-platform' : 'bg-nav')}>
      <div className="flex h-14 items-center gap-2 px-4">
        <img src="/logo/logo.svg" alt="" className="h-7 w-7" />
        {!collapsed && <span className="truncate text-sm font-semibold text-white">{env.appName}</span>}
      </div>
      {isPlatform && !collapsed && <span className="mx-4 mb-2 w-fit rounded-pill bg-white/15 px-2 py-0.5 text-xs font-semibold text-white">Platform</span>}
      <nav aria-label={`${area} navigation`} className="flex-1 overflow-y-auto px-2 pb-4">
        {groups.map((g, gi) => (
          <div key={gi} className="mt-3">
            {g.title && !collapsed && <p className="px-2 pb-1 text-[11px] font-semibold uppercase tracking-wider text-nav-text/60">{g.title}</p>}
            <ul>
              {g.items.map((i) => (
                <li key={i.to}>
                  <NavLink to={i.to} end={i.end} title={collapsed ? i.label : undefined}
                    className={({ isActive }) => cn('flex min-h-[36px] items-center gap-3 rounded-control px-2 py-1.5 text-sm hover:bg-white/10', isActive && 'bg-white/15 font-medium text-white')}>
                    <i.icon className="h-4 w-4 shrink-0" aria-hidden />
                    {!collapsed && <span className="truncate">{i.label}</span>}
                    {collapsed && <span className="sr-only">{i.label}</span>}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>
    </div>
  )

  return (
    <div className="flex min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-50 focus:rounded-control focus:bg-surface focus:px-3 focus:py-2">Skip to content</a>
      <aside className={cn('sticky top-0 hidden h-screen shrink-0 lg:block', collapsed ? 'w-16' : 'w-64')}>{sidebar}</aside>
      {drawer && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <button className="absolute inset-0 bg-nav/60" aria-label="Close navigation" onClick={() => setDrawer(false)} />
          <div className="relative h-full w-72 max-w-[85vw]">
            {sidebar}
            <Button variant="ghost" size="icon" className="absolute right-2 top-3 text-white hover:bg-white/10" aria-label="Close navigation" onClick={() => setDrawer(false)}><X className="h-4 w-4" aria-hidden /></Button>
          </div>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        {grant && (
          <Banner tone="danger" action={<Button size="sm" variant="secondary" onClick={async () => {
            try { await platformApi.closeBreakGlass(grant.grantId) } catch { toast.error('Could not close the grant. It will expire on its own.') }
            end(); nav('/platform/break-glass')
          }}>Close access</Button>}>
            Break-glass access to {grant.tenantName ?? 'a tenant'} is active until {new Date(grant.expiresAt).toLocaleTimeString()}. All access is recorded.
          </Banner>
        )}
        {!online && <Banner tone="warning"><WifiOff className="mr-1 inline h-4 w-4" aria-hidden />You are offline. Sending is disabled until the connection returns.</Banner>}
        <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b border-line bg-surface px-3 sm:px-4">
          <Button variant="ghost" size="icon" className="lg:hidden" aria-label="Open navigation" onClick={() => setDrawer(true)}><MenuIcon className="h-5 w-5" aria-hidden /></Button>
          <Button variant="ghost" size="icon" className="hidden lg:inline-flex" aria-label={collapsed ? 'Expand navigation' : 'Collapse navigation'} onClick={() => setCollapsed((c) => !c)}>
            {collapsed ? <PanelLeftOpen className="h-5 w-5" aria-hidden /> : <PanelLeftClose className="h-5 w-5" aria-hidden />}
          </Button>
          <div className="min-w-0 flex-1">
            {isPlatform ? <span className="font-medium">Platform administration</span> : (
              <Menu label="Switch organisation" align="start" items={memberships.filter((m) => m.membership_status === 'active' && m.tenant_status === 'active' && m.tenant_id !== profile?.tenant_id).map((m) => ({
                label: m.tenant_name, onSelect: () => { void selectTenant(m.tenant_id).then(() => nav('/')).catch(() => toast.error('Could not switch organisation.')) },
              }))}
                trigger={<button className="max-w-full truncate rounded-control px-2 py-1 text-left font-medium hover:bg-canvas" aria-label={`Organisation: ${activeTenant?.tenant_name ?? 'current'}`}>{activeTenant?.tenant_name ?? 'Organisation'}</button>} />
            )}
          </div>
          <nav aria-label="Console switch" className="hidden items-center gap-1 sm:flex">
            {canSwitchArea.workspace && area !== 'workspace' && <Button asChild variant="ghost" size="sm"><Link to="/">Workspace</Link></Button>}
            {canSwitchArea.admin && area !== 'admin' && <Button asChild variant="ghost" size="sm"><Link to="/admin">Admin</Link></Button>}
            {canSwitchArea.platform && area !== 'platform' && <Button asChild variant="ghost" size="sm"><Link to="/platform"><Shield className="h-4 w-4" aria-hidden />Platform</Link></Button>}
          </nav>
          <Button variant="ghost" size="icon" aria-label="Keyboard shortcuts and help" onClick={() => setHelp(true)}><HelpCircle className="h-5 w-5" aria-hidden /></Button>
          <Menu label="User menu" items={[
            { label: 'Profile', icon: <User className="h-4 w-4" />, onSelect: () => nav('/profile') },
            { label: 'Security', onSelect: () => nav('/profile/security') },
            { label: 'Help', onSelect: () => { if (env.supportUrl) window.open(env.supportUrl, '_blank', 'noopener,noreferrer'); else setHelp(true) } },
            { label: 'Sign out', icon: <LogOut className="h-4 w-4" />, danger: true, onSelect: () => { void logout().then(() => nav('/login', { replace: true })) } },
          ]} trigger={<button className="flex items-center gap-2 rounded-control px-2 py-1 hover:bg-canvas" aria-label="User menu">
            <span className="grid h-7 w-7 place-items-center rounded-full bg-primary text-xs font-semibold text-white">{(profile?.display_name ?? '?').slice(0, 1).toUpperCase()}</span>
            <span className="hidden max-w-[140px] truncate text-sm md:inline">{profile?.display_name}</span>
          </button>} />
        </header>
        <main id="main" className="min-w-0 flex-1 p-3 sm:p-5" tabIndex={-1}>
          <Crumbs area={area} />
          <Outlet />
        </main>
      </div>
      <Modal open={help} onOpenChange={setHelp} title="Keyboard shortcuts" description={`Shortcuts can be turned off in Profile. Home for you: ${homeFor(profile?.console)}`}>
        <table className="tbl min-w-0"><thead><tr><th scope="col">Keys</th><th scope="col">Action</th></tr></thead>
          <tbody>{SHORTCUTS.map(([k, a]) => <tr key={k}><td><kbd className="rounded border border-line bg-canvas px-1.5 py-0.5 font-mono text-xs">{k}</kbd></td><td>{a}</td></tr>)}</tbody></table>
        {env.usagePolicyUrl && <p className="mt-3 text-xs"><a className="text-primary underline" href={env.usagePolicyUrl} target="_blank" rel="noopener noreferrer">AI usage guidance</a></p>}
      </Modal>
      <IdleWatcher />
    </div>
  )
}
