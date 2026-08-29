import { describe, expect, it } from 'vitest'

import { darkChartTheme, lightChartTheme } from './chartTheme'

describe('chart theme defaults', () => {
  it('keeps chart text and canvas values explicit for all chart renderers', () => {
    expect(lightChartTheme.canvas).toBe('#fbfcfe')
    expect(lightChartTheme.text).toBe('#172231')
    expect(lightChartTheme.tooltipText).toBe('#f8fafc')
    expect(lightChartTheme.categoryColors).toHaveLength(6)
  })

  it('provides a distinct readable palette for the dark canvas and tooltip', () => {
    expect(darkChartTheme.canvas).not.toBe(lightChartTheme.canvas)
    expect(darkChartTheme.text).not.toBe(lightChartTheme.text)
    expect(darkChartTheme.grid).not.toBe(lightChartTheme.grid)
    expect(darkChartTheme.tooltipText).toBe('#edf3fb')
    expect(darkChartTheme.pendingLink).toBe(darkChartTheme.line)
    expect(darkChartTheme.categoryColors).toHaveLength(6)
  })
})
