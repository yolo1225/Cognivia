import { afterEach, describe, expect, it, vi } from 'vitest'

import { loadGradedQuizDraft, saveGradedQuizDraft } from './gradedQuizDraft'

const storage = new Map<string, string>()

vi.stubGlobal('localStorage', {
  getItem: (key: string) => storage.get(key) ?? null,
  setItem: (key: string, value: string) => storage.set(key, value),
  removeItem: (key: string) => storage.delete(key),
})

afterEach(() => storage.clear())

describe('graded quiz draft storage', () => {
  it('restores answers, summary state, and the current question for the same resource version', () => {
    saveGradedQuizDraft('learner_001', 'resource_001', 2, {
      answers: {
        q1: { selected: ['A'], text: '', checked: true, correct: true, selfMarked: false },
        q2: { selected: [], text: 'RAG retrieves relevant context.', checked: false, correct: null, selfMarked: false },
      },
      currentIndex: 1,
      showSummary: false,
    })

    expect(loadGradedQuizDraft('learner_001', 'resource_001', 2, ['q1', 'q2'])).toEqual({
      answers: {
        q1: { selected: ['A'], text: '', checked: true, correct: true, selfMarked: false },
        q2: { selected: [], text: 'RAG retrieves relevant context.', checked: false, correct: null, selfMarked: false },
      },
      currentIndex: 1,
      showSummary: false,
    })
  })

  it('isolates drafts by learner and resource version, and drops removed questions', () => {
    saveGradedQuizDraft('learner_001', 'resource_001', 1, {
      answers: {
        q1: { selected: ['A'], text: '', checked: true, correct: true, selfMarked: false },
        removed: { selected: ['B'], text: '', checked: true, correct: false, selfMarked: false },
      },
      currentIndex: 8,
      showSummary: true,
    })

    expect(loadGradedQuizDraft('learner_002', 'resource_001', 1, ['q1'])).toBeNull()
    expect(loadGradedQuizDraft('learner_001', 'resource_001', 2, ['q1'])).toBeNull()
    expect(loadGradedQuizDraft('learner_001', 'resource_001', 1, ['q1'])).toEqual({
      answers: { q1: { selected: ['A'], text: '', checked: true, correct: true, selfMarked: false } },
      currentIndex: 0,
      showSummary: true,
    })
  })
})
