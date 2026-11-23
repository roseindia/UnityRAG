import { useMutation, useQueryClient, type QueryKey } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ApiError } from '@/services/api/errors'
import { useAuth } from '@/contexts/AuthContext'
import type { Row } from '@/types/api'

/** Tenant-scoped query keys always begin with the active tenant id from the session (Design Document 5.5). */
export function useTenantKey() {
  const { profile } = useAuth()
  return (...parts: unknown[]): QueryKey => [profile?.tenant_id ?? 'none', ...parts]
}

export const s = (v: unknown, fallback = '–'): string => (v === null || v === undefined || v === '' ? fallback : String(v))
export const n = (v: unknown): number | null => (typeof v === 'number' ? v : v !== null && v !== undefined && v !== '' && !Number.isNaN(Number(v)) ? Number(v) : null)
export const arrOf = (v: unknown): string[] => (Array.isArray(v) ? v.map(String) : [])

/** A write that invalidates its area and shows a success toast; errors surface as toasts unless handled by the caller. */
export function useWrite<A, R>(fn: (a: A) => Promise<R>, opts: { invalidate?: unknown[][]; success?: string; onSuccess?: (r: R) => void; silentError?: boolean } = {}) {
  const qc = useQueryClient()
  const { profile } = useAuth()
  return useMutation({
    mutationFn: fn,
    onSuccess: (r) => {
      // Platform-console queries are not tenant-scoped (their keys start with 'platform'), so they are invalidated as they are.
      opts.invalidate?.forEach((k) => void qc.invalidateQueries({ queryKey: k[0] === 'platform' ? k : [profile?.tenant_id, ...k] }))
      if (opts.success) toast.success(opts.success)
      opts.onSuccess?.(r)
    },
    onError: (e) => { if (!opts.silentError) toast.error(e instanceof ApiError ? e.message : 'Something went wrong.') },
  })
}

export type { Row }
