export interface GradedQuizDraftAnswer {
  selected: string[]
  text: string
  checked: boolean
  correct: boolean | null
  selfMarked: boolean
}

export interface GradedQuizDraft {
  answers: Record<string, GradedQuizDraftAnswer>
  currentIndex: number
  showSummary: boolean
}

function storageKey(learnerId: string, resourceId: string, resourceVersion: number | undefined) {
  return `cognivia:graded-quiz-draft:${learnerId}:${resourceId}:v${resourceVersion ?? 1}`
}

function getStorage() {
  try {
    return globalThis.localStorage
  } catch {
    return null
  }
}

function validAnswer(value: unknown): GradedQuizDraftAnswer | null {
  if (!value || typeof value !== 'object') return null
  const candidate = value as Partial<GradedQuizDraftAnswer>
  if (!Array.isArray(candidate.selected) || !candidate.selected.every(item => typeof item === 'string')) return null
  if (typeof candidate.text !== 'string' || typeof candidate.checked !== 'boolean' || typeof candidate.selfMarked !== 'boolean') return null
  if (candidate.correct !== true && candidate.correct !== false && candidate.correct !== null) return null
  return {
    selected: candidate.selected,
    text: candidate.text,
    checked: candidate.checked,
    correct: candidate.correct,
    selfMarked: candidate.selfMarked,
  }
}

export function loadGradedQuizDraft(
  learnerId: string,
  resourceId: string,
  resourceVersion: number | undefined,
  questionIds: string[],
): GradedQuizDraft | null {
  const storage = getStorage()
  if (!storage || !learnerId || !resourceId || questionIds.length === 0) return null

  try {
    const raw = storage.getItem(storageKey(learnerId, resourceId, resourceVersion))
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<GradedQuizDraft>
    const allowedIds = new Set(questionIds)
    const answers = Object.fromEntries(
      Object.entries(parsed.answers || {}).flatMap(([questionId, answer]) => {
        const restored = allowedIds.has(questionId) ? validAnswer(answer) : null
        return restored ? [[questionId, restored]] : []
      }),
    ) as Record<string, GradedQuizDraftAnswer>
    const requestedIndex = typeof parsed.currentIndex === 'number' && Number.isInteger(parsed.currentIndex)
      ? parsed.currentIndex
      : 0
    return {
      answers,
      currentIndex: Math.min(Math.max(0, requestedIndex), questionIds.length - 1),
      showSummary: parsed.showSummary === true,
    }
  } catch {
    return null
  }
}

export function saveGradedQuizDraft(
  learnerId: string,
  resourceId: string,
  resourceVersion: number | undefined,
  draft: GradedQuizDraft,
) {
  const storage = getStorage()
  if (!storage || !learnerId || !resourceId) return

  try {
    storage.setItem(storageKey(learnerId, resourceId, resourceVersion), JSON.stringify(draft))
  } catch {
    // Browser privacy settings can disable local storage; the current attempt remains usable.
  }
}
