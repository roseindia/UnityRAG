import { useMemo } from 'react'
import { useAuth } from '@/contexts/AuthContext'
import type { Profile } from '@/types/api'

/** Pure helpers so route tables and tests can use them without React. */
export function buildPermissionApi(profile: Profile | null) {
  const tenant = new Set(profile?.permissions ?? [])
  const platform = new Set(profile?.platform_permissions ?? [])
  const can = (p: string) => tenant.has(p)
  const canAny = (ps: readonly string[]) => ps.some((p) => tenant.has(p))
  const platformCan = (p: string) => platform.has(p)
  const platformCanAny = (ps: readonly string[]) => ps.some((p) => platform.has(p))
  // The admin tree needs at least one admin-area permission (Design Document 5.3).
  const hasAdminAccess = [...tenant].some((p) => p.startsWith('admin.') || p === 'feedback.review' || p.startsWith('evaluation.'))
  const hasPlatformAccess = !!profile?.platform_role && platform.size > 0
  return { can, canAny, platformCan, platformCanAny, hasAdminAccess, hasPlatformAccess }
}

// Visibility derives from the permission lists in /auth/me, never from role codes.
export function usePermissions() {
  const { profile } = useAuth()
  return useMemo(() => buildPermissionApi(profile), [profile])
}
