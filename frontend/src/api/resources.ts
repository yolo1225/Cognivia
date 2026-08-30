import { apiClient, getData, postData, putData } from './client'
import type { NodeGate } from './tutoring'

export type QuizLevel = 'foundation' | 'improvement' | 'challenge'
export type QuestionType = 'single_choice' | 'multiple_choice' | 'short_answer' | 'coding'

export interface QuizQuestion {
  question_id: string
  level: QuizLevel
  question_type: QuestionType
  prompt: string
  options: string[]
  correct_answer: string
  explanation: string
  knowledge_id: string
  related_knowledge_ids?: string[]
  difficulty: number
  source_ref_ids: string[]
  reference_question_ids?: string[]
}

export interface GradedQuizContent {
  resource_type: 'graded_quiz'
  title: string
  target_audience: string
  learning_objectives: string[]
  questions: QuizQuestion[]
}

export interface ConceptBlock {
  title: string
  explanation: string
  example?: string | null
  source_ref_ids: string[]
}

export interface MisconceptionBlock {
  misconception: string
  correction: string
  source_ref_ids: string[]
}

export interface LectureContent {
  resource_type: 'lecture'
  title: string
  target_audience: string
  learning_objectives: string[]
  prerequisite_knowledge: string[]
  core_concepts: ConceptBlock[]
  misconceptions: MisconceptionBlock[]
  summary: string
}

export interface PracticeStep {
  order: number
  title: string
  instruction: string
  code_or_command?: string | null
  expected_result: string
  troubleshooting?: string | null
  source_ref_ids: string[]
}

export interface PracticeGuideContent {
  resource_type: 'practice_guide'
  title: string
  target_audience: string
  learning_objectives: string[]
  environment_requirements: string[]
  steps: PracticeStep[]
  acceptance_criteria: string[]
}

export type StructuredResourceContent = LectureContent | PracticeGuideContent | GradedQuizContent

export interface ResourceSummary {
  resource_id: string
  resource_type: string
  title: string
  content?: string
  difficulty: number
  review_status: string
  sources: string[]
  source_details?: Array<{ knowledge_id: string; name: string; source_title: string }>
  learner_profile_type?: string
  version?: number
  is_current?: boolean
  generation_task_id?: string | null
  generation_task_status?: string | null
  generation_decision?: string | null
  generated_at?: string | null
  task_created_at?: string | null
  quality_metrics?: ResourceQualityMetrics | null
  package_quality?: ResourceQualityMetrics | null
  package_status?: string
  failure_reason?: string | null
  structured_content?: StructuredResourceContent | null
  membership_type?: 'generated' | 'inherited'
  freshness_status?: 'current' | 'knowledge_changed'
}

export interface ResourceQualityMetrics {
  verifiable_claim_count: number
  hallucinated_claim_count: number
  hallucination_rate: number
  difficulty_match_score: number
  covered_core_knowledge_count: number
  target_core_knowledge_count: number
  core_knowledge_coverage: number
  passed: boolean
  revision_count: number
}

export interface ResourceQuizAttempt {
  attempt_id: string
  resource_version: number
  status: 'in_progress' | 'completed'
  current_question_id?: string | null
  answers: Record<string, {
    answer: string | string[]
    checked: boolean
    correct: boolean | null
    self_checked: boolean
    synced_at?: string
  }>
  objective_correct: number
  objective_total: number
  completed_at?: string | null
  evidence_result?: {
    materialized_count: number
    evidence_ids: string[]
    governance_results?: Array<Record<string, unknown>>
  }
  node_gate?: NodeGate | null
}

export function createQuizAttempt(resourceId: string, learnerId?: string) {
  return postData<ResourceQuizAttempt>(`/resources/${resourceId}/quiz-attempts`, { learner_id: learnerId })
}

export function saveQuizAnswer(
  resourceId: string,
  attemptId: string,
  questionId: string,
  answer: string | string[],
  learnerId?: string,
  selfChecked = false,
) {
  return putData<ResourceQuizAttempt & { question_id: string; correct: boolean | null; synced: boolean }>(
    `/resources/${resourceId}/quiz-attempts/${attemptId}/answers/${encodeURIComponent(questionId)}`,
    { learner_id: learnerId, answer, self_checked: selfChecked },
  )
}

export function completeQuizAttempt(resourceId: string, attemptId: string, learnerId?: string) {
  return postData<ResourceQuizAttempt>(`/resources/${resourceId}/quiz-attempts/${attemptId}/complete`, { learner_id: learnerId })
}

export function listResources(filters: { taskId?: string; learnerId?: string; domainCode?: string } = {}) {
  const params = new URLSearchParams()
  if (filters.taskId) params.set('task_id', filters.taskId)
  if (filters.learnerId) params.set('learner_id', filters.learnerId)
  if (filters.domainCode) params.set('domain_code', filters.domainCode)
  const query = params.toString()
  return getData<ResourceSummary[]>(`/resources${query ? `?${query}` : ''}`)
}

export function listResourceVersions(resourceId: string) {
  return getData<Array<{
    resource_id: string
    series_id: string
    version: number
    is_current: boolean
    review_status: string
    adaptation_reason: string
    created_at: string | null
  }>>(`/resources/${resourceId}/versions`)
}

export function exportResource(
  resourceId: string,
  format: 'markdown' | 'pdf' | 'word',
  audience: 'learner' | 'teacher' = 'learner',
) {
  return postData<{
    resource_version: number
    file_name: string
    file_hash: string
    review_report_id: string | null
    review_status: string
    download_url: string
  }>(`/resources/${resourceId}/export`, { format, audience })
}

export async function downloadResourceExport(downloadUrl: string): Promise<Blob> {
  // download_url is absolute from the backend root (e.g. /api/v1/resources/exports/x.pdf);
  // the axios baseURL already includes /api/v1, so strip that prefix.
  const path = downloadUrl.replace(/^\/api\/v1/, '')
  const response = await apiClient.get(path, { responseType: 'blob' })
  return response.data as Blob
}

export function submitFeedback(
  resourceId: string,
  feedbackType: string,
  rating = 3,
  learnerId?: string,
) {
  const body: Record<string, unknown> = {
    feedback_type: feedbackType,
    rating,
  }
  if (learnerId) body.learner_id = learnerId
  return postData(`/resources/${resourceId}/feedback`, body)
}
