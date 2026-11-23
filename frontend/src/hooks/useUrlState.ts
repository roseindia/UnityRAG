import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'

/** Filters, paging and tab selection live in the URL so they can be shared and bookmarked. */
export function useUrlState<T extends Record<string, string>>(defaults: T) {
  const [params, setParams] = useSearchParams()
  const state = useMemo(() => {
    const out = { ...defaults }
    for (const k of Object.keys(defaults)) {
      const v = params.get(k)
      if (v !== null) (out as Record<string, string>)[k] = v
    }
    return out
  }, [params, defaults])

  const set = useCallback((patch: Partial<Record<keyof T, string | undefined>>, opts?: { keepOffset?: boolean }) => {
    setParams((prev) => {
      const next = new URLSearchParams(prev)
      for (const [k, v] of Object.entries(patch)) {
        if (v === undefined || v === '' || v === (defaults as Record<string, string>)[k]) next.delete(k)
        else next.set(k, v)
      }
      if (!opts?.keepOffset && !('offset' in patch)) next.delete('offset')
      return next
    }, { replace: true })
  }, [setParams, defaults])

  return [state, set] as const
}
