import { postData } from './client'

export interface DiagnosticQuestion {
  question_id: string
  knowledge_id: number
  question_type: 'single_choice' | 'short_answer'
  stem: string
  options: string[]
  difficulty: number
}

export interface DiagnosticSession {
  session_id: string
  learner_id: string
  domain_code: string
  question_count: number
  status: string
  questions: DiagnosticQuestion[]
  selection_summary: {
    direction_tags: string[]
    single_choice_count: number
    short_answer_count: number
    theory_count: number
    practice_count: number
  }
}

export interface DiagnosticResult {
  session_id: string
  learner_id: string
  status: string
  score: number
  correct_count: number
  question_count: number
  profile_id: string
  profile_type: string
  ability_profile: Record<string, unknown>
  weak_knowledge: Array<{
    knowledge_id: string
    name: string
    category: string
    weakness_level: number
  }>
  learning_path_id: string
  learning_path?: {
    stages?: Array<{
      name: string
      description?: string
    }>
  }
  next_action: string
}

export function createDiagnosticSession(learnerId = 'learner_001') {
  return postData<DiagnosticSession>('/diagnostics/sessions', {
    learner_id: learnerId,
    domain_code: 'ai_app_dev',
    question_count: 10,
  })
}

export function submitDiagnosticSession(
  sessionId: string,
  answers: Array<{ question_id: string; answer: string | number }>,
  learnerId = 'learner_001',
) {
  return postData<DiagnosticResult>(`/diagnostics/sessions/${sessionId}/submit`, {
    learner_id: learnerId,
    domain_code: 'ai_app_dev',
    answers,
  })
}
