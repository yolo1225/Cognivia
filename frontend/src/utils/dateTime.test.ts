import { describe, expect, it } from 'vitest'

import { formatBeijingDate, formatBeijingDateTime } from './dateTime'

describe('Beijing time formatting', () => {
  it('treats timezone-less API timestamps as UTC database values', () => {
    expect(formatBeijingDateTime('2026-08-11T07:34:19')).toBe('2026-08-11 15:34')
  })

  it('converts explicit UTC timestamps and handles Beijing date rollover', () => {
    expect(formatBeijingDateTime('2026-08-11T17:30:00Z')).toBe('2026-08-12 01:30')
    expect(formatBeijingDate('2026-08-11T17:30:00Z')).toBe('2026-08-12')
  })

  it('uses a stable placeholder for missing or invalid values', () => {
    expect(formatBeijingDateTime(null)).toBe('-')
    expect(formatBeijingDateTime('invalid')).toBe('-')
  })
})
