import { env } from '@/config/env'
import { tokenStore } from '@/services/authentication/tokenStore'
import { correlationId } from '@/utils/ids'
import { refreshSession } from './apiClient'
import { ApiError, errorFromResponse } from './errors'

export interface SseEvent { event: string; data: string }

/** Incremental SSE parser: feed chunks, receive complete events. */
export function createSseParser(onEvent: (e: SseEvent) => void) {
  let buf = ''
  return (chunk: string) => {
    buf += chunk.replace(/\r\n/g, '\n')
    let idx: number
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      let event = 'message'
      const data: string[] = []
      for (const line of block.split('\n')) {
        if (line.startsWith(':')) continue
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''))
      }
      if (data.length || event !== 'message') onEvent({ event, data: data.join('\n') })
    }
  }
}

export interface StreamOptions {
  path: string
  body: unknown
  signal: AbortSignal
  onEvent: (e: SseEvent) => void
  idleMs?: number
}

/** POST + ReadableStream SSE client (EventSource cannot POST). Checks response.ok before reading. */
export async function postStream({ path, body, signal, onEvent, idleMs = 60_000 }: StreamOptions): Promise<void> {
  const send = () => fetch(`${env.apiBaseUrl}${path}`, {
    method: 'POST', signal,
    headers: {
      'Content-Type': 'application/json', Accept: 'text/event-stream',
      'X-Correlation-ID': correlationId(),
      ...(tokenStore.access ? { Authorization: `Bearer ${tokenStore.access}` } : {}),
    },
    body: JSON.stringify(body),
  })
  let res: Response
  try {
    res = await send()
    if (res.status === 401 && (await refreshSession())) res = await send()
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw new ApiError({ status: 0, code: 'aborted' })
    throw new ApiError({ status: 0, code: 'network_error' })
  }
  if (!res.ok || !res.body) {
    let data: unknown
    try { data = await res.json() } catch { data = undefined }
    const h: Record<string, unknown> = {}
    res.headers.forEach((v, k) => { h[k.toLowerCase()] = v })
    throw errorFromResponse(res.status, data, h)
  }
  const reader = res.body.getReader()
  const dec = new TextDecoder()
  const feed = createSseParser(onEvent)
  let watchdog: ReturnType<typeof setTimeout> | undefined
  const arm = () => {
    clearTimeout(watchdog)
    watchdog = setTimeout(() => { reader.cancel().catch(() => undefined) }, idleMs)
  }
  try {
    arm()
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      arm()
      feed(dec.decode(value, { stream: true }))
    }
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw new ApiError({ status: 0, code: 'aborted' })
    throw new ApiError({ status: 0, code: 'network_error' })
  } finally {
    clearTimeout(watchdog)
  }
}
