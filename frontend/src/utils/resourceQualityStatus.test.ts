import { describe, expect, it } from 'vitest'

import { resourceQualityStatusLabel, resourceQualityStatusTone } from './resourceQualityStatus'

describe('resource quality status presentation', () => {
  it('describes stale validation as regeneration, not manual review', () => {
    expect(resourceQualityStatusLabel('review_stale')).toBe('知识库已更新，需重新生成')
    expect(resourceQualityStatusTone('review_stale')).toBe('wait')
  })

  it('describes passed resources as automatically quality-validated', () => {
    expect(resourceQualityStatusLabel('passed')).toBe('质量校验通过')
    expect(resourceQualityStatusTone('passed')).toBe('ok')
  })
})
