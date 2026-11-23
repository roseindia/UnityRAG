/**
 * Locate a cited passage inside a page's text for highlighting.
 *
 * The cited text is a chunk: it may start with a "Title > Section" breadcrumb, and its whitespace (line breaks,
 * table spacing) differs from the page text. Both sides are compared with whitespace collapsed and case folded,
 * and the match is mapped back to offsets in the original page text.
 */

interface Normalized { norm: string; map: number[] }

function normalizeWithMap(s: string): Normalized {
  const out: string[] = []
  const map: number[] = []
  let pendingSpace = false
  for (let i = 0; i < s.length; i++) {
    const ch = s[i]
    // Table pipes are treated as spaces so table rows match their flattened text.
    if (/[\s|]/.test(ch)) {
      if (out.length > 0) pendingSpace = true
      continue
    }
    if (pendingSpace) {
      out.push(' ')
      map.push(i)
      pendingSpace = false
    }
    out.push(ch.toLowerCase())
    map.push(i)
  }
  return { norm: out.join(''), map }
}

/** Returns [start, end) offsets in `text` of the passage, or null when the passage is not on this page. */
export function findHighlightRange(text: string, passage: string | undefined): [number, number] | null {
  if (!text || !passage) return null
  // Drop the navigation prefix ("Title > Section > ") that chunking prepends; the body follows the last " > ".
  const body = passage.includes(' > ') ? passage.slice(passage.lastIndexOf(' > ') + 3) : passage
  const page = normalizeWithMap(text)
  const wanted = normalizeWithMap(body).norm
  // Whole passage first (from its start, then shorter prefixes), then single sentences: a chunk often starts on a
  // different page than the sentence that matters, or a masked token sits inside it.
  for (const len of [200, 100, 60, 30]) {
    const probe = wanted.slice(0, len).trim()
    if (probe.length < 15) continue
    const idx = page.norm.indexOf(probe)
    if (idx < 0) continue
    const endNorm = Math.min(idx + wanted.length, page.norm.length)
    return [page.map[idx], page.map[endNorm - 1] + 1]
  }
  for (const sentence of body.split(/(?<=[.!?;])\s+|\n+/)) {
    const sent = normalizeWithMap(sentence).norm.trim()
    if (sent.length < 30) continue
    const idx = page.norm.indexOf(sent.slice(0, 200))
    if (idx < 0) continue
    const endNorm = Math.min(idx + sent.length, page.norm.length)
    return [page.map[idx], page.map[endNorm - 1] + 1]
  }
  return null
}
