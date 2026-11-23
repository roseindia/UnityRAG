// Open-redirect protection: returnTo must be a same-origin relative path that matches a known route prefix.
const ALLOWED = ['/', '/chat', '/search', '/documents', '/history', '/analytics', '/profile', '/admin', '/platform']

export function safeReturnTo(raw: string | null | undefined): string {
  if (!raw || !raw.startsWith('/') || raw.startsWith('//') || raw.includes('\\') || /^\/[a-z]+:/i.test(raw)) return '/'
  const path = raw.split('?')[0].split('#')[0]
  const ok = path === '/' || ALLOWED.some((p) => p !== '/' && (path === p || path.startsWith(`${p}/`)))
  return ok ? raw : '/'
}

export function homeFor(consoleKind: string | undefined): string {
  if (consoleKind === 'platform_admin') return '/platform'
  if (consoleKind === 'tenant_admin') return '/admin'
  return '/'
}
