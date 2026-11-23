import axios, { type AxiosAdapter, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { apiClient, clean, onSessionEvent, registerStepUp } from '@/services/api/apiClient'
import { tokenStore } from '@/services/authentication/tokenStore'
import { ApiError } from '@/services/api/errors'

const envelope = (status: number, code: string) => ({ status, data: { error: { code, message: 'm', correlation_id: 'cid-1', details: [] } } })

function installAdapter(handler: (cfg: InternalAxiosRequestConfig, n: number) => { status: number; data: unknown }) {
  let n = 0
  const adapter: AxiosAdapter = (cfg) => {
    const { status, data } = handler(cfg as InternalAxiosRequestConfig, ++n)
    const res: AxiosResponse = { data, status, statusText: '', headers: {}, config: cfg as InternalAxiosRequestConfig }
    return status >= 400 ? Promise.reject(Object.assign(new Error('x'), { isAxiosError: true, response: res, config: cfg })) : Promise.resolve(res)
  }
  apiClient.defaults.adapter = adapter
}

const realAdapter = apiClient.defaults.adapter
beforeEach(() => tokenStore.set('old-access', 'refresh-1', new Date(Date.now() + 600_000).toISOString()))
afterEach(() => { tokenStore.clear(); apiClient.defaults.adapter = realAdapter; registerStepUp(null); vi.restoreAllMocks() })

describe('apiClient', () => {
  it('sends the bearer token and a fresh correlation id on every request', async () => {
    const seen: Record<string, unknown>[] = []
    installAdapter((cfg) => { seen.push({ auth: cfg.headers.get('Authorization'), cid: cfg.headers.get('X-Correlation-ID') }); return { status: 200, data: {} } })
    await apiClient.get('/documents'); await apiClient.get('/documents')
    expect(seen[0].auth).toBe('Bearer old-access')
    expect(seen[0].cid).toMatch(/^[0-9a-f]{32}$/)
    expect(seen[0].cid).not.toBe(seen[1].cid)
  })

  it('does not attach the token to public endpoints', async () => {
    let auth: unknown = 'unset'
    installAdapter((cfg) => { auth = cfg.headers.get('Authorization'); return { status: 200, data: {} } })
    await apiClient.post('/auth/login', {})
    expect(auth).toBeFalsy()
  })

  it('refreshes once (single-flight) for concurrent 401 token_expired and replays each request once', async () => {
    const post = vi.spyOn(axios, 'post').mockResolvedValue({ data: { access_token: 'new-access', refresh_token: 'refresh-2', expires_at: new Date(Date.now() + 600_000).toISOString() } })
    installAdapter((cfg) => (cfg.headers.get('Authorization') === 'Bearer new-access' ? { status: 200, data: { ok: true } } : envelope(401, 'token_expired')))
    const [a, b, c] = await Promise.all([apiClient.get('/documents'), apiClient.get('/collections'), apiClient.get('/conversations')])
    expect([a.data, b.data, c.data]).toEqual([{ ok: true }, { ok: true }, { ok: true }])
    expect(post).toHaveBeenCalledTimes(1)
    expect(tokenStore.access).toBe('new-access')
    expect(tokenStore.refresh).toBe('refresh-2') // refresh tokens rotate
  })

  it('signals session expiry when the refresh fails', async () => {
    vi.spyOn(axios, 'post').mockRejectedValue(new Error('401'))
    installAdapter(() => envelope(401, 'token_expired'))
    const events: string[] = []
    const off = onSessionEvent((e) => events.push(e))
    await expect(apiClient.get('/documents')).rejects.toMatchObject({ code: 'token_expired' })
    off()
    expect(events).toContain('expired')
    expect(tokenStore.access).toBeNull()
  })

  it('opens the step-up flow on step_up_required and replays the request after verification', async () => {
    let calls = 0
    installAdapter(() => (++calls === 1 ? envelope(401, 'step_up_required') : { status: 200, data: { saved: true } }))
    const handler = vi.fn().mockResolvedValue(true)
    registerStepUp(handler)
    const r = await apiClient.put('/admin/config/rag', {})
    expect(handler).toHaveBeenCalledTimes(1)
    expect(r.data).toEqual({ saved: true })
    expect(calls).toBe(2)
  })

  it('rejects with the original error when step-up is cancelled', async () => {
    installAdapter(() => envelope(401, 'step_up_required'))
    registerStepUp(() => Promise.resolve(false))
    await expect(apiClient.put('/admin/settings', {})).rejects.toMatchObject({ code: 'step_up_required' })
  })

  it('retries idempotent GETs on 503 but never retries POST', async () => {
    let gets = 0
    installAdapter((cfg) => { if (cfg.method === 'get') { gets++; return gets < 3 ? envelope(503, 'service_unavailable') : { status: 200, data: { ok: 1 } } } return envelope(503, 'service_unavailable') })
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const p = apiClient.get('/documents')
    await vi.advanceTimersByTimeAsync(5000)
    expect((await p).data).toEqual({ ok: 1 })
    expect(gets).toBe(3)
    let posts = 0
    installAdapter(() => { posts++; return envelope(503, 'service_unavailable') })
    await expect(apiClient.post('/documents', {})).rejects.toBeInstanceOf(ApiError)
    expect(posts).toBe(1)
    vi.useRealTimers()
  })

  it('flags a suspended tenant', async () => {
    installAdapter(() => envelope(403, 'tenant_unavailable'))
    const events: string[] = []
    const off = onSessionEvent((e) => events.push(e))
    await expect(apiClient.get('/documents')).rejects.toMatchObject({ status: 403 })
    off()
    expect(events).toContain('tenant_unavailable')
  })

  it('clean() drops empty params', () => expect(clean({ a: '', b: undefined, c: 'x', d: 0 })).toEqual({ c: 'x', d: 0 }))
})

describe('tokenStore', () => {
  it('keeps tokens in memory only', () => {
    expect(JSON.stringify(localStorage)).not.toMatch(/old-access|refresh-1/)
    expect(JSON.stringify(sessionStorage)).not.toMatch(/old-access|refresh-1/)
  })
})
