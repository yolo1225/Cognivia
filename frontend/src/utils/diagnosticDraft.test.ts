import { afterEach, describe, expect, it, vi } from 'vitest'

import { clearDiagnosticDraft, loadDiagnosticDraft, saveDiagnosticDraft } from './diagnosticDraft'

const storage = new Map<string, string>()

vi.stubGlobal('localStorage', {
  getItem: (key: string) => storage.get(key) ?? null,
  setItem: (key: string, value: string) => storage.set(key, value),
  removeItem: (key: string) => storage.delete(key),
})

afterEach(() => storage.clear())

describe('diagnostic draft storage', () => {
  it('restores answers and the current question for the same learner session', () => {
    saveDiagnosticDraft('learner_001', 'session_001', { 0: 2, 3: 'RAG uses retrieved context.' }, 3)

    expect(loadDiagnosticDraft('learner_001', 'session_001', 10)).toEqual({
      answers: { 0: 2, 3: 'RAG uses retrieved context.' },
      currentIndex: 3,
    })
  })

  it('keeps drafts isolated and drops stale question indexes', () => {
    saveDiagnosticDraft('learner_001', 'session_001', { 0: 1, 12: 'stale' }, 12)

    expect(loadDiagnosticDraft('learner_002', 'session_001', 10)).toBeNull()
    expect(loadDiagnosticDraft('learner_001', 'session_001', 10)).toEqual({
      answers: { 0: 1 },
      currentIndex: 9,
    })
  })

  it('removes drafts after a completed diagnostic', () => {
    saveDiagnosticDraft('learner_001', 'session_001', { 0: 1 }, 0)
    clearDiagnosticDraft('learner_001', 'session_001')

    expect(loadDiagnosticDraft('learner_001', 'session_001', 10)).toBeNull()
  })
})
