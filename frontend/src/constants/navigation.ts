import {
  Activity, BarChart3, BookOpen, Boxes, Building2, ClipboardList, Cpu, FileText, FolderOpen, Gauge, History, Home, KeyRound,
  LayoutDashboard, LifeBuoy, ListChecks, MessageSquare, MessagesSquare, Search, Settings, ShieldAlert, ShieldCheck, Users, UsersRound,
  Layers, Server, Sparkles, FlaskConical, ScrollText, UploadCloud, type LucideIcon,
} from 'lucide-react'

export interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  /** Tenant permissions: the item shows when the user holds any of them. Empty = always. */
  anyOf?: string[]
  /** Platform permissions. */
  platformAnyOf?: string[]
  end?: boolean
}
export interface NavGroup { title?: string; items: NavItem[] }

export const WORKSPACE_NAV: NavGroup[] = [
  { items: [
    { to: '/', label: 'Home', icon: Home, anyOf: ['chat.use', 'search.use'], end: true },
    { to: '/chat', label: 'AI chat', icon: MessageSquare, anyOf: ['chat.use'] },
    { to: '/search', label: 'Search', icon: Search, anyOf: ['search.use'] },
    { to: '/documents', label: 'Documents', icon: FileText, anyOf: ['documents.read'], end: true },
    { to: '/documents/upload', label: 'Upload', icon: UploadCloud, anyOf: ['documents.upload'] },
    { to: '/history', label: 'History', icon: History, anyOf: ['chat.use', 'search.use'] },
    { to: '/analytics/department', label: 'Department analytics', icon: BarChart3, anyOf: ['department.analytics.view', 'admin.analytics.view'] },
  ] },
]

export const ADMIN_NAV: NavGroup[] = [
  { items: [{ to: '/admin', label: 'Dashboard', icon: LayoutDashboard, anyOf: ['admin.dashboard.view'], end: true }] },
  { title: 'People', items: [
    { to: '/admin/users', label: 'Users', icon: Users, anyOf: ['admin.users.manage'] },
    { to: '/admin/roles', label: 'Roles & permissions', icon: KeyRound, anyOf: ['admin.roles.manage'] },
    { to: '/admin/organisation', label: 'Departments & teams', icon: Building2, anyOf: ['admin.departments.manage'] },
    { to: '/admin/groups', label: 'Groups', icon: UsersRound, anyOf: ['admin.groups.manage'] },
  ] },
  { title: 'Content', items: [
    { to: '/admin/collections', label: 'Collections', icon: FolderOpen, anyOf: ['admin.collections.manage'] },
    { to: '/admin/documents', label: 'Documents', icon: FileText, anyOf: ['admin.documents.manage'] },
    { to: '/admin/ingestion', label: 'Ingestion', icon: Layers, anyOf: ['admin.ingestion.manage'] },
  ] },
  { title: 'AI & quality', items: [
    { to: '/admin/ai', label: 'AI & RAG configuration', icon: Sparkles, anyOf: ['admin.ai_config.manage'] },
    { to: '/admin/feedback', label: 'Feedback review', icon: MessagesSquare, anyOf: ['feedback.review'] },
    { to: '/admin/evaluation', label: 'Evaluation', icon: FlaskConical, anyOf: ['evaluation.manage', 'evaluation.run'] },
  ] },
  { title: 'Insight & governance', items: [
    { to: '/admin/analytics', label: 'Analytics & usage', icon: BarChart3, anyOf: ['admin.analytics.view', 'admin.usage.view'] },
    { to: '/admin/reports', label: 'Reports', icon: ClipboardList, anyOf: ['admin.reports.export'] },
    { to: '/admin/audit', label: 'Audit log', icon: ScrollText, anyOf: ['admin.audit.view'] },
    { to: '/admin/settings', label: 'Settings', icon: Settings, anyOf: ['admin.settings.manage'] },
  ] },
]

export const PLATFORM_NAV: NavGroup[] = [
  { items: [{ to: '/platform', label: 'Dashboard', icon: Gauge, platformAnyOf: ['platform.dashboard.view'], end: true }] },
  { title: 'Tenants', items: [
    { to: '/platform/tenants', label: 'Tenants', icon: Building2, platformAnyOf: ['platform.tenants.view'] },
    { to: '/platform/plans', label: 'Plans & features', icon: Boxes, platformAnyOf: ['platform.plans.manage'] },
  ] },
  { title: 'AI', items: [
    { to: '/platform/ai/providers', label: 'AI providers', icon: Cpu, platformAnyOf: ['platform.ai.manage'] },
    { to: '/platform/ai/models', label: 'Model catalogue', icon: BookOpen, platformAnyOf: ['platform.ai.manage'] },
  ] },
  { title: 'Operations', items: [
    { to: '/platform/monitoring', label: 'Monitoring', icon: Activity, platformAnyOf: ['platform.monitoring.view'] },
    { to: '/platform/jobs', label: 'Jobs & workers', icon: ListChecks, platformAnyOf: ['platform.monitoring.view'] },
    { to: '/platform/security', label: 'Security events', icon: ShieldAlert, platformAnyOf: ['platform.security.view'] },
    { to: '/platform/audit', label: 'Platform audit', icon: ScrollText, platformAnyOf: ['platform.audit.view'] },
  ] },
  { title: 'Administration', items: [
    { to: '/platform/users', label: 'Platform users', icon: Users, platformAnyOf: ['platform.users.manage'] },
    { to: '/platform/settings', label: 'Settings', icon: Settings, platformAnyOf: ['platform.settings.manage'] },
    { to: '/platform/break-glass', label: 'Break-glass', icon: ShieldCheck, platformAnyOf: ['platform.break_glass.use'] },
  ] },
]

export const ICON_HELP = LifeBuoy
export const ICON_SERVER = Server
export const ICON_SHIELD = ShieldCheck

export const CRUMB_LABELS: Record<string, string> = {
  admin: 'Administration', platform: 'Platform', users: 'Users', roles: 'Roles & permissions', organisation: 'Departments & teams',
  groups: 'Groups', collections: 'Collections', documents: 'Documents', ingestion: 'Ingestion', ai: 'AI & RAG', providers: 'Providers',
  models: 'Models', feedback: 'Feedback review', evaluation: 'Evaluation', datasets: 'Datasets', runs: 'Runs', analytics: 'Analytics',
  reports: 'Reports', audit: 'Audit log', settings: 'Settings', tenants: 'Tenants', new: 'New', plans: 'Plans', monitoring: 'Monitoring',
  jobs: 'Jobs', security: 'Security events', 'break-glass': 'Break-glass',
}
