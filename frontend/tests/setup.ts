import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

afterEach(() => cleanup())

// jsdom lacks these browser APIs used by Radix and Recharts.
class RO { observe() { /* noop */ } unobserve() { /* noop */ } disconnect() { /* noop */ } }
;(globalThis as unknown as { ResizeObserver: typeof RO }).ResizeObserver ??= RO
if (!window.matchMedia) {
  window.matchMedia = ((q: string) => ({ matches: false, media: q, onchange: null, addEventListener: () => undefined, removeEventListener: () => undefined, addListener: () => undefined, removeListener: () => undefined, dispatchEvent: () => false })) as typeof window.matchMedia
}
Element.prototype.scrollIntoView ??= () => undefined
Element.prototype.hasPointerCapture ??= () => false
