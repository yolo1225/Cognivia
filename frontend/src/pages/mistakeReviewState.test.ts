import { describe, expect, it } from 'vitest'
import type { MistakeReviewItem } from '@/api/mistakeReview'
import { mistakePathLabel, mistakePathTone } from './mistakeReviewState'

function item(overrides: Partial<MistakeReviewItem>): MistakeReviewItem {
  return {
    item_id: 'mistake_1',
    knowledge_id: 'knowledge_1',
    knowledge_name: '知识点',
    category: '分类',
    source_type: 'initial_diagnostic',
    question_type: 'single_choice',
    difficulty: 2,
    status: 'pending',
    last_score: 0,
    error_summary: '需要巩固',
    last_wrong_at: null,
    review_count: 0,
    consolidated_at: null,
    recommended_resource: null,
    is_current_priority: false,
    path_node_status: null,
    path_order: null,
    ...overrides,
  }
}

describe('mistake review path labels', () => {
  it('marks current blockers as the first-priority task', () => {
    const value = item({ is_current_priority: true, path_node_status: 'current', path_order: 1 })
    expect(mistakePathLabel(value)).toBe('当前必做')
    expect(mistakePathTone(value)).toBe('is-priority')
  })

  it('keeps future-node mistakes visibly available for early practice', () => {
    const value = item({ path_node_status: 'locked', path_order: 3 })
    expect(mistakePathLabel(value)).toBe('路线第 3 节 · 可提前练习')
    expect(mistakePathTone(value)).toBe('is-future')
  })

  it('distinguishes completed and out-of-path mistakes', () => {
    expect(mistakePathLabel(item({ path_node_status: 'completed' }))).toBe('已完成节点')
    expect(mistakePathLabel(item({ path_node_status: null }))).toBe('路径外错题')
  })
})
