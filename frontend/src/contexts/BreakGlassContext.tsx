import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'

export interface Grant { grantId: string; tenantId: string; tenantName?: string; expiresAt: number }

interface Ctx { grant: Grant | null; start: (g: Grant) => void; end: () => void }
const C = createContext<Ctx | null>(null)

/** Break-glass grants are held in memory only. When one ends, everything loaded under it is removed from the cache. */
export function BreakGlassProvider({ children }: { children: ReactNode }) {
  const [grant, setGrant] = useState<Grant | null>(null)
  const qc = useQueryClient()

  const end = useCallback(() => {
    setGrant(null)
    qc.removeQueries({ queryKey: ['platform', 'break-glass'] })
  }, [qc])

  useEffect(() => {
    if (!grant) return
    const ms = grant.expiresAt - Date.now()
    if (ms <= 0) { end(); return }
    const t = setTimeout(end, ms)
    return () => clearTimeout(t)
  }, [grant, end])

  const value = useMemo(() => ({ grant, start: setGrant, end }), [grant, end])
  return <C.Provider value={value}>{children}</C.Provider>
}

export function useBreakGlass(): Ctx {
  const v = useContext(C)
  if (!v) throw new Error('useBreakGlass must be used inside <BreakGlassProvider>')
  return v
}
