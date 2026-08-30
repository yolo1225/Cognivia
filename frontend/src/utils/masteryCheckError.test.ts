import { describe, expect, it } from 'vitest'

import { masteryCheckErrorMessage } from './masteryCheckError'

describe('masteryCheckErrorMessage', () => {
  it('explains when the current node has no scorable single-choice question', () => {
    expect(masteryCheckErrorMessage({
      response: { data: { error: { code: 'MASTERY_CHECK_QUESTION_UNAVAILABLE' } } },
    })).toBe('当前知识点缺少可判分的单选验证题，请联系管理员补题后重试。')
  })

  it('keeps the pending-assessment instruction specific', () => {
    expect(masteryCheckErrorMessage({
      response: { data: { error: { code: 'MASTERY_CHECK_PENDING' } } },
    })).toBe('已有掌握检查待完成，请先完成当前验证题。')
  })

  it('falls back safely when the server does not provide a known code', () => {
    expect(masteryCheckErrorMessage(new Error('network')))
      .toBe('暂时无法发起掌握检查，请刷新页面后重试。')
  })
})
