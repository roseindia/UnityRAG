// Tokens live in module memory only. They are never written to localStorage,
// sessionStorage or IndexedDB (Design Document 5.4 / 18) and never logged.
type Listener = () => void

interface Tokens { access: string; refresh: string; expiresAt: number }
let tokens: Tokens | null = null
const listeners = new Set<Listener>()

export const tokenStore = {
  set(access: string, refresh: string, expiresAtIso: string) {
    tokens = { access, refresh, expiresAt: Date.parse(expiresAtIso) }
    listeners.forEach((l) => l())
  },
  clear() {
    tokens = null
    listeners.forEach((l) => l())
  },
  get access() { return tokens?.access ?? null },
  get refresh() { return tokens?.refresh ?? null },
  get expiresAt() { return tokens?.expiresAt ?? null },
  subscribe(l: Listener) { listeners.add(l); return () => { listeners.delete(l) } },
}
