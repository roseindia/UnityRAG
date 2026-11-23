import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { createMemoryRouter, RouterProvider, type RouteObject } from 'react-router-dom'
import { TooltipProvider } from '@/components/ui/tooltip'
import type { Profile } from '@/types/api'

export const baseProfile: Profile = {
  account_id: 'a1', email: 'user@example.test', display_name: 'Test User', tenant_id: 't1', user_id: 'u1', user_type: 'employee', department_id: 'd1',
  platform_role: '', roles: ['member'], permissions: ['chat.use', 'search.use', 'documents.read', 'collections.read', 'feedback.submit'], platform_permissions: [],
  lines_of_business: ['motor'], jurisdictions: ['UK'], clearance_rank: 1, mfa_verified: false, console: 'user',
}

export const makeClient = () => new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } })

/** Render a screen inside a memory router and fresh query cache. */
export function renderScreen(ui: ReactElement, opts: { path?: string; entry?: string } = {}) {
  const routes: RouteObject[] = [{ path: opts.path ?? '*', element: ui }]
  const router = createMemoryRouter(routes, { initialEntries: [opts.entry ?? '/'] })
  const client = makeClient()
  const utils = render(<QueryClientProvider client={client}><TooltipProvider><RouterProvider router={router} /></TooltipProvider></QueryClientProvider>)
  return { ...utils, router, client }
}

export function renderRoutes(routes: RouteObject[], entry: string) {
  const router = createMemoryRouter(routes, { initialEntries: [entry] })
  const utils = render(<QueryClientProvider client={makeClient()}><TooltipProvider><RouterProvider router={router} /></TooltipProvider></QueryClientProvider>)
  return { ...utils, router }
}
