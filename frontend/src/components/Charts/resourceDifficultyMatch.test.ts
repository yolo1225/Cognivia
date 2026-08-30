import { describe, expect, it } from 'vitest'

import { toResourceDifficultyMatchData } from './resourceDifficultyMatch'

describe('resource difficulty match chart data', () => {
  it('keeps only resources with a real review metric and preserves zero scores', () => {
    const data = toResourceDifficultyMatchData([
      { resource_id: 'lecture', resource_type: 'lecture', resource_type_label: '讲义', title: 'RAG 检索基础与分块策略', difficulty: 2, difficulty_match_score: 91 },
      { resource_id: 'pending', resource_type: 'practice_guide', title: '待审核实训', difficulty: 4, difficulty_match_score: null },
      { resource_id: 'quiz', resource_type: 'graded_quiz', resource_type_label: '分级测验', title: '验证题', difficulty: 5, difficulty_match_score: 0 },
    ])

    expect(data).toEqual([
      { resourceId: 'lecture', label: '讲义 · RAG 检索基础与分…', title: 'RAG 检索基础与分块策略', difficulty: 2, difficultyMatchScore: 91 },
      { resourceId: 'quiz', label: '分级测验 · 验证题', title: '验证题', difficulty: 5, difficultyMatchScore: 0 },
    ])
  })

  it('clamps chart values without inventing a score for missing data', () => {
    expect(toResourceDifficultyMatchData([
      { resource_id: 'resource', resource_type: 'lecture', title: '资源', difficulty: 9, difficulty_match_score: 120 },
      { resource_id: 'missing', resource_type: 'lecture', title: '缺少审核', difficulty: 1 },
    ])).toEqual([
      { resourceId: 'resource', label: 'lecture · 资源', title: '资源', difficulty: 5, difficultyMatchScore: 100 },
    ])
  })
})
