/** WCAG relative luminance contrast of a #RRGGBB colour against white. Tenant accents must reach 4.5:1 (Design Document 14.2). */
export function contrastOnWhite(hex: string): number | null {
  const m = /^#([0-9a-f]{6})$/i.exec(hex.trim())
  if (!m) return null
  const c = [0, 2, 4].map((i) => parseInt(m[1].slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4))
  const lum = 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
  return 1.05 / (lum + 0.05)
}

export const accentAllowed = (hex: string) => (contrastOnWhite(hex) ?? 0) >= 4.5
