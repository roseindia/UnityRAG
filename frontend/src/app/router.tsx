import { lazy, Suspense, type ReactNode } from 'react'
import { createBrowserRouter, Link, Navigate, Outlet, useRouteError, type RouteObject } from 'react-router-dom'
import { Toaster } from 'sonner'
import { RequireAuth, RequireConsole, RequirePermission } from '@/app/guards'
import { Shell } from '@/components/layout/Shell'
import { StepUpProvider } from '@/components/dialogs/StepUpProvider'
import { ErrorBoundary } from '@/components/feedback/ErrorBoundary'
import { LoadingBlock } from '@/components/feedback/states'
import { Button } from '@/components/ui/button'
import { usePermissions } from '@/hooks/usePermissions'
import { useAuth } from '@/contexts/AuthContext'
import { homeFor } from '@/utils/returnTo'

const L = <T extends { default: React.ComponentType }>(f: () => Promise<T>) => lazy(f)
const named = <K extends string>(f: () => Promise<Record<K, React.ComponentType>>, k: K) => lazy(() => f().then((m) => ({ default: m[k] })))

// Workspace
const Login = L(() => import('@/features/authentication/LoginPage'))
const Profile = L(() => import('@/features/authentication/ProfilePage'))
const TenantPicker = named(() => import('@/features/authentication/OtherAuthPages'), 'TenantPickerPage')
const LoginCallback = named(() => import('@/features/authentication/OtherAuthPages'), 'LoginCallbackPage')
const ResetPassword = named(() => import('@/features/authentication/OtherAuthPages'), 'ResetPasswordPage')
const Home = L(() => import('@/features/dashboard/HomePage'))
const Chat = L(() => import('@/features/chat/ChatPage'))
const Search = L(() => import('@/features/search/SearchPage'))
const Documents = L(() => import('@/features/documents/DocumentsPage'))
const DocumentDetail = L(() => import('@/features/documents/DocumentDetailPage'))
const Upload = L(() => import('@/features/documents/UploadPage'))
const History = L(() => import('@/features/conversations/HistoryPage'))
const DeptAnalytics = L(() => import('@/features/analytics/DepartmentAnalyticsPage'))
// Tenant admin
const AdminDashboard = L(() => import('@/features/tenant-admin/DashboardPage'))
const Users = L(() => import('@/features/tenant-admin/UsersPage'))
const UserDetail = L(() => import('@/features/tenant-admin/UserDetailPage'))
const Roles = L(() => import('@/features/tenant-admin/RolesPage'))
const Organisation = named(() => import('@/features/tenant-admin/OrganisationPage'), 'OrganisationPage')
const Groups = named(() => import('@/features/tenant-admin/OrganisationPage'), 'GroupsPage')
const GroupDetail = named(() => import('@/features/tenant-admin/OrganisationPage'), 'GroupDetailPage')
const Collections = named(() => import('@/features/tenant-admin/CollectionsPage'), 'CollectionsPage')
const CollectionDetail = named(() => import('@/features/tenant-admin/CollectionsPage'), 'CollectionDetailPage')
const AdminDocuments = named(() => import('@/features/tenant-admin/AdminDocumentsPage'), 'AdminDocumentsPage')
const AdminDocumentDetail = named(() => import('@/features/tenant-admin/AdminDocumentsPage'), 'AdminDocumentDetailPage')
const Ingestion = L(() => import('@/features/tenant-admin/IngestionPage'))
const AiConfig = L(() => import('@/features/tenant-admin/AiConfigPage'))
const Analytics = named(() => import('@/features/tenant-admin/AnalyticsPages'), 'AnalyticsPage')
const Reports = named(() => import('@/features/tenant-admin/AnalyticsPages'), 'ReportsPage')
const Feedback = L(() => import('@/features/tenant-admin/FeedbackPage'))
const Evaluation = named(() => import('@/features/tenant-admin/EvaluationPages'), 'EvaluationPage')
const DatasetDetail = named(() => import('@/features/tenant-admin/EvaluationPages'), 'DatasetDetailPage')
const RunDetail = named(() => import('@/features/tenant-admin/EvaluationPages'), 'RunDetailPage')
const Audit = L(() => import('@/features/tenant-admin/AuditPage'))
const Settings = L(() => import('@/features/tenant-admin/SettingsPage'))
// Platform admin
const PlatformDashboard = L(() => import('@/features/platform-admin/PlatformDashboardPage'))
const Tenants = named(() => import('@/features/platform-admin/TenantsPage'), 'TenantsPage')
const TenantNew = named(() => import('@/features/platform-admin/TenantsPage'), 'TenantNewPage')
const TenantDetail = L(() => import('@/features/platform-admin/TenantDetailPage'))
const Plans = named(() => import('@/features/platform-admin/CatalogPages'), 'PlansPage')
const Providers = named(() => import('@/features/platform-admin/CatalogPages'), 'ProvidersPage')
const Models = named(() => import('@/features/platform-admin/CatalogPages'), 'ModelsPage')
const PlatformUsers = named(() => import('@/features/platform-admin/CatalogPages'), 'PlatformUsersPage')
const PlatformSettings = named(() => import('@/features/platform-admin/CatalogPages'), 'PlatformSettingsPage')
const Monitoring = named(() => import('@/features/platform-admin/OperationsPages'), 'MonitoringPage')
const Jobs = named(() => import('@/features/platform-admin/OperationsPages'), 'JobsPage')
const Security = named(() => import('@/features/platform-admin/OperationsPages'), 'SecurityEventsPage')
const PlatformAudit = named(() => import('@/features/platform-admin/OperationsPages'), 'PlatformAuditPage')
const BreakGlass = named(() => import('@/features/platform-admin/OperationsPages'), 'BreakGlassPage')
const BreakGlassGrant = named(() => import('@/features/platform-admin/OperationsPages'), 'BreakGlassGrantPage')

const S = ({ children }: { children: ReactNode }) => <Suspense fallback={<LoadingBlock rows={6} />}><ErrorBoundary panel>{children}</ErrorBoundary></Suspense>

function RootLayout() {
  return (
    <StepUpProvider>
      <Suspense fallback={<LoadingBlock rows={6} />}><Outlet /></Suspense>
      <Toaster position="top-right" closeButton richColors duration={6000} />
    </StepUpProvider>
  )
}

export function NotFoundPage() {
  return (
    <div className="mx-auto mt-24 max-w-md px-4 text-center">
      <h1 className="text-2xl">Page not found</h1>
      <p className="mt-1 text-ink-muted">The page you asked for does not exist or has moved.</p>
      <Button asChild className="mt-4"><Link to="/">Back to home</Link></Button>
    </div>
  )
}

function RouteError() {
  useRouteError()
  return <ErrorBoundaryFallback />
}
function ErrorBoundaryFallback() {
  return (
    <div role="alert" className="mx-auto mt-24 max-w-md px-4 text-center">
      <h1>Something went wrong</h1>
      <p className="mt-1 text-ink-muted">The page could not be displayed.</p>
      <Button className="mt-4" onClick={() => window.location.assign('/')}>Reload</Button>
    </div>
  )
}

/** Platform-only users land in their own console; others see the workspace home. */
function HomeGate() {
  const p = usePermissions()
  const { profile } = useAuth()
  if (!p.canAny(['chat.use', 'search.use'])) return <Navigate to={homeFor(profile?.console) === '/' ? (p.hasAdminAccess ? '/admin' : '/profile') : homeFor(profile?.console)} replace />
  return <S><Home /></S>
}

const need = (anyOf: string[], el: ReactNode) => <RequirePermission anyOf={anyOf}><S>{el}</S></RequirePermission>
const needP = (platform: string[], el: ReactNode) => <RequirePermission platform={platform}><S>{el}</S></RequirePermission>

export const routes: RouteObject[] = [
  {
    element: <RootLayout />, errorElement: <RouteError />,
    children: [
      { path: '/login', element: <S><Login /></S> },
      { path: '/login/callback', element: <S><LoginCallback /></S> },
      { path: '/reset-password', element: <S><ResetPassword /></S> },
      {
        element: <RequireAuth />,
        children: [
          { path: '/select-tenant', element: <S><TenantPicker /></S> },
          {
            element: <Shell area="workspace" />,
            children: [
              { path: '/', element: <HomeGate /> },
              { path: '/chat', element: need(['chat.use'], <Chat />) },
              { path: '/chat/:conversationId', element: need(['chat.use'], <Chat />) },
              { path: '/search', element: need(['search.use'], <Search />) },
              { path: '/documents', element: need(['documents.read'], <Documents />) },
              { path: '/documents/upload', element: need(['documents.upload'], <Upload />) },
              { path: '/documents/:id', element: need(['documents.read'], <DocumentDetail />) },
              { path: '/history', element: need(['chat.use', 'search.use'], <History />) },
              { path: '/analytics/department', element: need(['department.analytics.view', 'admin.analytics.view'], <DeptAnalytics />) },
              { path: '/profile', element: <S><Profile /></S> },
              { path: '/profile/security', element: <S><Profile /></S> },
            ],
          },
          {
            path: '/admin', element: <RequireConsole kind="admin" />,
            children: [{
              element: <Shell area="admin" />,
              children: [
                { index: true, element: need(['admin.dashboard.view'], <AdminDashboard />) },
                { path: 'users', element: need(['admin.users.manage'], <Users />) },
                { path: 'users/:id', element: need(['admin.users.manage'], <UserDetail />) },
                { path: 'roles', element: need(['admin.roles.manage'], <Roles />) },
                { path: 'organisation', element: need(['admin.departments.manage'], <Organisation />) },
                { path: 'groups', element: need(['admin.groups.manage'], <Groups />) },
                { path: 'groups/:id', element: need(['admin.groups.manage'], <GroupDetail />) },
                { path: 'collections', element: need(['admin.collections.manage'], <Collections />) },
                { path: 'collections/:id', element: need(['admin.collections.manage'], <CollectionDetail />) },
                { path: 'documents', element: need(['admin.documents.manage'], <AdminDocuments />) },
                { path: 'documents/:id', element: need(['admin.documents.manage'], <AdminDocumentDetail />) },
                { path: 'ingestion', element: need(['admin.ingestion.manage'], <Ingestion />) },
                { path: 'ai', element: need(['admin.ai_config.manage'], <AiConfig />) },
                { path: 'analytics', element: need(['admin.analytics.view', 'admin.usage.view'], <Analytics />) },
                { path: 'reports', element: need(['admin.reports.export'], <Reports />) },
                { path: 'feedback', element: need(['feedback.review'], <Feedback />) },
                { path: 'evaluation', element: need(['evaluation.manage', 'evaluation.run'], <Evaluation />) },
                { path: 'evaluation/datasets/:id', element: need(['evaluation.manage'], <DatasetDetail />) },
                { path: 'evaluation/runs/:id', element: need(['evaluation.run'], <RunDetail />) },
                { path: 'audit', element: need(['admin.audit.view'], <Audit />) },
                { path: 'settings', element: need(['admin.settings.manage'], <Settings />) },
              ],
            }],
          },
          {
            path: '/platform', element: <RequireConsole kind="platform" />,
            children: [{
              element: <Shell area="platform" />,
              children: [
                { index: true, element: needP(['platform.dashboard.view'], <PlatformDashboard />) },
                { path: 'tenants', element: needP(['platform.tenants.view'], <Tenants />) },
                { path: 'tenants/new', element: needP(['platform.tenants.manage'], <TenantNew />) },
                { path: 'tenants/:id', element: needP(['platform.tenants.view'], <TenantDetail />) },
                { path: 'plans', element: needP(['platform.plans.manage'], <Plans />) },
                { path: 'ai/providers', element: needP(['platform.ai.manage'], <Providers />) },
                { path: 'ai/models', element: needP(['platform.ai.manage'], <Models />) },
                { path: 'users', element: needP(['platform.users.manage'], <PlatformUsers />) },
                { path: 'monitoring', element: needP(['platform.monitoring.view'], <Monitoring />) },
                { path: 'jobs', element: needP(['platform.monitoring.view'], <Jobs />) },
                { path: 'security', element: needP(['platform.security.view'], <Security />) },
                { path: 'audit', element: needP(['platform.audit.view'], <PlatformAudit />) },
                { path: 'settings', element: needP(['platform.settings.manage'], <PlatformSettings />) },
                { path: 'break-glass', element: needP(['platform.break_glass.use'], <BreakGlass />) },
                { path: 'break-glass/:grantId', element: needP(['platform.break_glass.use'], <BreakGlassGrant />) },
              ],
            }],
          },
        ],
      },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
]

export const router = createBrowserRouter(routes)
