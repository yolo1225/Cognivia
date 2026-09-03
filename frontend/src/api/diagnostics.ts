import { getData, postData } from './client'

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
    algorithm_version?: string
    random_seed?: number
    question_ids?: string[]
    difficulty_distribution?: Record<string, number>
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
  evidence_sufficient?: boolean
  evidence_reason?: string | null
  profile_reliability_status?: 'evidence_sufficient' | 'provisional'
  profile_reliability_message?: string | null
  learning_path_id: string | null
  learning_path?: {
    nodes?: Array<{
      path_node_id: string
      title: string
      status: 'current' | 'locked' | 'completed' | 'skipped'
      learning_objective?: string
      recommendation_reason?: string
      knowledge_items?: Array<{ knowledge_id: string; name: string; category: string }>
      focus_knowledge_ids?: string[]
      path_order?: number
    }>
    stages?: Array<{
      name: string
      description?: string
    }>
  } | null
  next_action: string
  answer_results: DiagnosticAnswerResult[]
}

export interface DiagnosticCriterionResult {
  criterion_id: string
  score: number
  rationale: string
}

export interface DiagnosticAnswerResult {
  question_id: string
  question_type: 'single_choice' | 'short_answer'
  score: number
  is_correct: boolean
  scoring_method: 'deterministic' | 'ai_rubric' | string
  ai_comment?: string | null
  criteria: DiagnosticCriterionResult[]
  matched_points: string[]
  missing_points: string[]
  factual_errors: string[]
  confidence: number | null
  scoring_uncertain: boolean
}

export interface DiagnosticSessionStatus extends DiagnosticSession {
  status: 'created' | 'scoring' | 'pending_scoring' | 'scored' | 'failed'
  progress: number
  scoring_attempts: number
  error_code: string | null
  retryable: boolean
  result: DiagnosticResult | null
  status_url?: string
  events_url?: string
}

export function createDiagnosticSession(domainCode: string, learnerId = 'learner_001') {
  return postData<DiagnosticSession>('/diagnostics/sessions', {
    learner_id: learnerId,
    domain_code: domainCode,
    question_count: 10,
  })
}

export function submitDiagnosticSession(
  sessionId: string,
  answers: Array<{ question_id: string; answer: string | number }>,
  domainCode: string,
  learnerId = 'learner_001',
) {
  return postData<DiagnosticSessionStatus>(`/diagnostics/sessions/${sessionId}/submit`, {
    learner_id: learnerId,
    domain_code: domainCode,
    answers,
  })
}

export function getDiagnosticSession(sessionId: string, learnerId: string) {
  return getData<DiagnosticSessionStatus>(
    `/diagnostics/sessions/${sessionId}?learner_id=${encodeURIComponent(learnerId)}`,
  )
}

export function getCurrentDiagnosticSession(
  learnerId: string,
  domainCode: string,
) {
  return getData<DiagnosticSessionStatus | null>(
    `/diagnostics/sessions/current?learner_id=${encodeURIComponent(learnerId)}&domain_code=${encodeURIComponent(domainCode)}`,
  )
}

export function retryDiagnosticSession(sessionId: string, learnerId: string) {
  return postData<DiagnosticSessionStatus>(`/diagnostics/sessions/${sessionId}/retry`, {
    learner_id: learnerId,
  })
}

export type DiagnosticStreamEvent = {
  type: 'status' | 'completed' | 'pending' | 'failed'
} & DiagnosticSessionStatus

export function streamDiagnosticSession(
  sessionId: string,
  learnerId: string,
  onEvent: (event: DiagnosticStreamEvent) => void,
) {
  const baseUrl = import.meta.env.VITE_API_BASE_URL || '/api/v1'
  const url = `${baseUrl}/diagnostics/sessions/${sessionId}/events?learner_id=${encodeURIComponent(learnerId)}`
  const source = new EventSource(url, { withCredentials: true })
  for (const type of ['status', 'completed', 'pending', 'failed'] as const) {
    source.addEventListener(type, raw => {
      onEvent({ type, ...JSON.parse((raw as MessageEvent).data) } as DiagnosticStreamEvent)
      if (type !== 'status') source.close()
    })
  }
  return source
}
