import { describe, expect, it } from 'vitest'
import { formatKnowledgeName } from './knowledgeName'

describe('formatKnowledgeName', () => {
  it('removes the imported document and internal-code prefix', () => {
    expect(formatKnowledgeName('AI 机器学习基础知识库 (ai_ml_basics) / 23. 线性回归从零实现')).toBe('线性回归从零实现')
  })

  it('preserves ordinary knowledge names', () => {
    expect(formatKnowledgeName('提示词工程基础')).toBe('提示词工程基础')
  })
})
