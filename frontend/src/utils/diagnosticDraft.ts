export type DiagnosticDraftAnswer = string | number

interface DiagnosticDraft {
  answers: Record<number, DiagnosticDraftAnswer>
  currentIndex: number
}

function storageKey(learnerId: string, sessionId: string) {
  return `cognivia:diagnostic-draft:${learnerId}:${sessionId}`
}

function getStorage() {
  try {
    return globalThis.localStorage
  } catch {
    return null
  }
}

export function loadDiagnosticDraft(
  learnerId: string,
  sessionId: string,
  questionCount: number,
): DiagnosticDraft | null {
  const storage = getStorage()
  if (!storage || !learnerId || !sessionId) return null

  try {
    const raw = storage.getItem(storageKey(learnerId, sessionId))
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<DiagnosticDraft>
    const answers = Object.fromEntries(
      Object.entries(parsed.answers || {}).flatMap(([index, answer]) => {
        const numericIndex = Number(index)
        return Number.isInteger(numericIndex)
          && numericIndex >= 0
          && numericIndex < questionCount
          && (typeof answer === 'string' || typeof answer === 'number')
          ? [[numericIndex, answer]]
          : []
      }),
    ) as Record<number, DiagnosticDraftAnswer>
    const requestedIndex = typeof parsed.currentIndex === 'number'
      && Number.isInteger(parsed.currentIndex)
      ? parsed.currentIndex
      : 0
    const currentIndex = Math.min(
      Math.max(0, requestedIndex),
      Math.max(0, questionCount - 1),
    )
    return { answers, currentIndex }
  } catch {
    return null
  }
}

export function saveDiagnosticDraft(
  learnerId: string,
  sessionId: string,
  answers: Record<number, DiagnosticDraftAnswer>,
  currentIndex: number,
) {
  const storage = getStorage()
  if (!storage || !learnerId || !sessionId) return

  try {
    storage.setItem(storageKey(learnerId, sessionId), JSON.stringify({ answers, currentIndex }))
  } catch {
    // Browser privacy settings can disable local storage; the active session remains usable.
  }
}

export function clearDiagnosticDraft(learnerId: string, sessionId: string) {
  const storage = getStorage()
  if (!storage || !learnerId || !sessionId) return

  try {
    storage.removeItem(storageKey(learnerId, sessionId))
  } catch {
    // Nothing else is required when browser storage is unavailable.
  }
}
