import axios, { AxiosError, type AxiosRequestConfig, type InternalAxiosRequestConfig } from 'axios'
import { env } from '@/config/env'
import { tokenStore } from '@/services/authentication/tokenStore'
import { correlationId } from '@/utils/ids'
import { ApiError, errorFromResponse } from './errors'
import type { TokenResponse } from '@/types/api'

export const apiClient = axios.create({ baseURL: env.apiBaseUrl, timeout: 30_000 })

const PUBLIC = ['/auth/login', '/auth/refresh', '/auth/oidc/exchange', '/auth/password/reset']
const isPublic = (url?: string) => !!url && PUBLIC.some((p) => url.startsWith(p))

type Cfg = InternalAxiosRequestConfig & { _retried?: boolean; _attempt?: number; _stepUp?: boolean }

// ---- events the app shell subscribes to ----
type SessionEvent = 'expired' | 'tenant_unavailable'
const sessionListeners = new Set<(e: SessionEvent, reason?: string) => void>()
export const onSessionEvent = (fn: (e: SessionEvent, reason?: string) => void) => {
  sessionListeners.add(fn)
  return () => { sessionListeners.delete(fn) }
}
const emit = (e: SessionEvent, reason?: string) => sessionListeners.forEach((l) => l(e, reason))

// Step-up (MFA) handler registered by StepUpProvider. Resolves true when verified.
let stepUpHandler: (() => Promise<boolean>) | null = null
export const registerStepUp = (fn: (() => Promise<boolean>) | null) => { stepUpHandler = fn }

// Latest correlation id seen on an error (for "Copy reference" on the global boundary).
export const lastReference = { id: undefined as string | undefined }

apiClient.interceptors.request.use((cfg) => {
  cfg.headers.set('X-Correlation-ID', correlationId())
  const t = tokenStore.access
  if (t && !isPublic(cfg.url)) cfg.headers.set('Authorization', `Bearer ${t}`)
  return cfg
})

// ---- single-flight refresh ----
let refreshing: Promise<boolean> | null = null
export function refreshSession(): Promise<boolean> {
  if (refreshing) return refreshing
  const rt = tokenStore.refresh
  if (!rt) return Promise.resolve(false)
  refreshing = axios
    .post<TokenResponse>(`${env.apiBaseUrl}/auth/refresh`, { refresh_token: rt }, { timeout: 15_000, headers: { 'X-Correlation-ID': correlationId() } })
    .then((r) => { tokenStore.set(r.data.access_token, r.data.refresh_token, r.data.expires_at); return true })
    .catch(() => { tokenStore.clear(); return false })
    .finally(() => { refreshing = null })
  return refreshing
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

apiClient.interceptors.response.use(
  (r) => r,
  async (err: AxiosError) => {
    const cfg = err.config as Cfg | undefined
    if (err.code === 'ERR_CANCELED') throw new ApiError({ status: 0, code: 'aborted' })
    if (!err.response) {
      // Network error: retry idempotent GETs twice with backoff + jitter.
      if (cfg && cfg.method === 'get' && (cfg._attempt ?? 0) < 2) {
        cfg._attempt = (cfg._attempt ?? 0) + 1
        await sleep(300 * 2 ** cfg._attempt + Math.random() * 200)
        return apiClient.request(cfg)
      }
      throw new ApiError({ status: 0, code: 'network_error' })
    }
    const { status, data, headers } = err.response
    let parsed: unknown = data
    if (data instanceof Blob && data.type.includes('json')) {
      try { parsed = JSON.parse(await data.text()) } catch { parsed = undefined }
    }
    const apiErr = errorFromResponse(status, parsed, headers as Record<string, unknown>)
    if (apiErr.correlationId) lastReference.id = apiErr.correlationId

    if (cfg && cfg.method === 'get' && [502, 503, 504].includes(status) && (cfg._attempt ?? 0) < 2) {
      cfg._attempt = (cfg._attempt ?? 0) + 1
      await sleep(300 * 2 ** cfg._attempt + Math.random() * 200)
      return apiClient.request(cfg)
    }
    if (status === 401 && cfg && !isPublic(cfg.url)) {
      if (['token_expired', 'invalid_token', 'authentication_required'].includes(apiErr.code) && !cfg._retried) {
        cfg._retried = true
        if (await refreshSession()) return apiClient.request(cfg)
        emit('expired', 'Your session has expired. Please sign in again.')
      } else if (apiErr.code === 'step_up_required' && !cfg._stepUp && stepUpHandler) {
        cfg._stepUp = true
        if (await stepUpHandler()) return apiClient.request(cfg)
      } else if (['token_reuse', 'invalid_refresh_token'].includes(apiErr.code)) {
        tokenStore.clear()
        emit('expired', apiErr.message)
      }
    }
    if (status === 403 && apiErr.code === 'tenant_unavailable') emit('tenant_unavailable')
    throw apiErr
  },
)

export const get = <T>(url: string, params?: object, cfg?: AxiosRequestConfig) => apiClient.get<T>(url, { params, ...cfg }).then((r) => r.data)
export const post = <T>(url: string, body?: unknown, cfg?: AxiosRequestConfig) => apiClient.post<T>(url, body, cfg).then((r) => r.data)
export const put = <T>(url: string, body?: unknown, cfg?: AxiosRequestConfig) => apiClient.put<T>(url, body, cfg).then((r) => r.data)
export const del = <T>(url: string, params?: object, cfg?: AxiosRequestConfig) => apiClient.delete<T>(url, { params, ...cfg }).then((r) => r.data)

/** Drop undefined/empty params so URLs stay clean. */
export function clean<T extends object>(o: T): Partial<T> {
  return Object.fromEntries(Object.entries(o).filter(([, v]) => v !== undefined && v !== '' && v !== null)) as Partial<T>
}

/** Download a file as a Blob with the bearer token and save it (the token never goes into a URL). */
export async function downloadBlob(url: string, params?: object, fallbackName = 'download'): Promise<string> {
  const r = await apiClient.get<Blob>(url, { params, responseType: 'blob', timeout: 120_000 })
  const cd = (r.headers['content-disposition'] as string | undefined) ?? ''
  const m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(cd)
  const name = m ? decodeURIComponent(m[1]) : fallbackName
  const href = URL.createObjectURL(r.data)
  const a = document.createElement('a')
  a.href = href
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(href), 10_000)
  return name
}
