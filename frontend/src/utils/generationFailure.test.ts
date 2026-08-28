import { describe, expect, it } from 'vitest'

import { generationFailureCopy } from './generationFailure'

describe('generationFailureCopy', () => {
  it('distinguishes claim-free, convergence and quality failures', () => {
    expect(generationFailureCopy('revision_claim_set_empty_after_repair').title).toContain('缺少可核验内容')
    expect(generationFailureCopy('revision_exhausted').title).toContain('质量指标')
    expect(generationFailureCopy('node_package_resources_incomplete').title).toContain('发布门槛')
  })

  it('keeps an unknown controlled reason visible', () => {
    expect(generationFailureCopy('custom_failure').description).toBe('custom_failure')
  })
})
