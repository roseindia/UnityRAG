import { describe, expect, it } from 'vitest'
import { findHighlightRange } from '@/utils/highlight'

const page = [
  '# post-hoc: which pairs differ?',
  'print(stats.tukey_hsd(*samples))',
  '',
  'Task 3: Integrating the Statistical Findings',
  '1. Comparing the three tests',
  'Test Project question Key result',
  'Z-test (Assignment 4) Do card and cash trips have different mean fares?',
  'z = 5.91, difference $1.15, d = 0.118',
].join('\n')

describe('findHighlightRange', () => {
  it('finds a chunk with a breadcrumb prefix and different whitespace', () => {
    const chunk = 'post-hoc: which pairs differ? > 1. Comparing the three tests Test Project question Key result Z-test (Assignment 4) Do card and cash trips have different mean fares? z = 5.91, difference $1.15, d = 0.118'
    const range = findHighlightRange(page, chunk)
    expect(range).not.toBeNull()
    const [s, e] = range!
    expect(page.slice(s, e).startsWith('1. Comparing the three tests')).toBe(true)
    expect(page.slice(s, e).endsWith('d = 0.118')).toBe(true)
  })

  it('returns null when the passage is not on the page', () => {
    expect(findHighlightRange(page, 'completely unrelated sentence about life insurance riders')).toBeNull()
  })

  it('returns null without text or passage', () => {
    expect(findHighlightRange('', 'anything at all here')).toBeNull()
    expect(findHighlightRange(page, undefined)).toBeNull()
  })
})

describe('findHighlightRange with a Ujjawal-style page', () => {
  it('highlights the cited sentence even when the passage spans a masked token', () => {
    const page2 = 'Motivated B.Tech Computer Science student specializing in Data\nAnalytics at Delhi Technological University (DTU), with a strong\nfoundation in data structures, algorithms, statistics, and machine learning.'
    const chunk = 'Ujjawal Roy is a B.Tech CSDA student with a foundation in data structures and currently exploring opportunities in AI/ML. Motivated B.Tech Computer Science student specializing in Data Analytics at Delhi Technological University (DTU)'
    const range = findHighlightRange(page2, chunk)
    expect(range).not.toBeNull()
    expect(page2.slice(range![0], range![1]).startsWith('Motivated')).toBe(true)
  })
})
