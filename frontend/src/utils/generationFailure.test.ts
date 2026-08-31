import { describe, expect, it } from 'vitest'

import { generationFailureCopy } from './generationFailure'

describe('generationFailureCopy', () => {
  it('explains incomplete practice steps without exposing an internal code', () => {
    const copy = generationFailureCopy('revision_required_practice_field_empty')
    expect(copy.title).toBe('实操指南步骤不完整')
    expect(copy.description).toContain('预期结果')
    expect(copy.description).not.toContain('revision_required')
  })
  it('distinguishes claim-free, convergence and quality failures', () => {
    expect(generationFailureCopy('revision_claim_set_empty_after_repair').title).toContain('缺少可核验内容')
    expect(generationFailureCopy('review_claim_set_empty').description).not.toContain('历史')
    expect(generationFailureCopy('revision_exhausted').title).toContain('质量指标')
    expect(generationFailureCopy('node_package_resources_incomplete').title).toContain('发布门槛')
  })

  it('describes policy rejection as an unsupported technical assertion', () => {
    const copy = generationFailureCopy('generated_content_policy_invalid')
    expect(copy.title).toContain('未验证的技术断言')
    expect(copy.description).toContain('教学动作本身不会触发')
  })

  it('keeps an unknown controlled reason visible', () => {
    expect(generationFailureCopy('custom_failure').description).toBe('custom_failure')
  })
})
