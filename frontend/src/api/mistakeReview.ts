import { getData, postData } from './client'

export type MistakeSourceType = 'initial_diagnostic' | 'path_assessment' | 'graded_quiz'
export type MistakeStatus = 'pending' | 'reviewing' | 'verification_pending' | 'consolidated' | 'needs_more_practice'

export interface RecommendedResource {
  resource_id: string
  title: string
  resource_type: string
}

export interface MistakeReviewItem {
  item_id: string
  knowledge_id: string | null
  knowledge_name: string
  category: string
  source_type: MistakeSourceType
  question_type: string
  difficulty: number
  status: MistakeStatus
  last_score: number | null
  error_summary: string
  last_wrong_at: string | null
  review_count: number
  consolidated_at: string | null
  recommended_resource: RecommendedResource | null
  question?: { stem: string; options: string[] } | null
  scoring_comment?: string | null
  has_profile_evidence?: boolean
  tutoring_available?: boolean
  evidence_governance?: GovernanceResult | null
  attempts?: ConsolidationHistory[]
}

export interface ConsolidationHistory {
  attempt_id: string
  status: string
  score: number | null
  threshold: number
  confidence: number | null
  scoring_method: string | null
  evidence_ref: string | null
  completed_at: string | null
}

export interface MistakeSummary {
  total: number
  pending: number
  in_progress: number
  consolidated: number
  verified: number
  consolidation_rate: number | null
  focus_knowledge: { knowledge_id: string; name: string } | null
}

export interface ConsolidationAttempt {
  attempt_id: string
  item_id: string
  question: {
    question_id: string
    stem: string
    options: string[]
    difficulty: number
    question_type: string
  }
  recommended_resource: RecommendedResource | null
}

export interface ConsolidationResult {
  attempt_id: string
  status: string
  score: number
  threshold: number
  passed: boolean
  confidence: number
  scoring_method: string
  evidence_ref: string
  explanation: string
  evidence: GovernanceResult['evidence']
  profile_result: GovernanceResult['profile_result']
  path_result: GovernanceResult['path_result']
}

export interface GovernanceResult {
  evidence: {
    evidence_ref: string
    governance_status: 'pending' | 'eligible' | 'conflicted' | 'consumed' | 'no_change' | 'rejected'
    eligible_evidence_count: number
    required_evidence_count: number
    governance_reason: string
  }
  profile_result: {
    evaluated: boolean
    profile_updated: boolean
    previous_profile_id: string | null
    resulting_profile_id: string | null
    resulting_profile_version: number | null
    decision_reason: string | null
  }
  path_result: {
    updated: boolean
    completed_node_id: string | null
    current_node_id: string | null
    resulting_path_id: string | null
  }
}

export function getMistakeSummary(domainCode: string, learnerId?: string) {
  const params = new URLSearchParams({ domain_code: domainCode })
  if (learnerId) params.set('learner_id', learnerId)
  return getData<MistakeSummary>(`/mistake-review/summary?${params}`)
}

export function listMistakeItems(filters: {
  domainCode: string
  learnerId?: string
  status?: string
  sourceType?: string
  difficulty?: number
  page?: number
  pageSize?: number
}) {
  const params = new URLSearchParams({
    domain_code: filters.domainCode,
    page: String(filters.page || 1),
    page_size: String(filters.pageSize || 20),
  })
  if (filters.learnerId) params.set('learner_id', filters.learnerId)
  if (filters.status) params.set('status', filters.status)
  if (filters.sourceType) params.set('source_type', filters.sourceType)
  if (filters.difficulty) params.set('difficulty', String(filters.difficulty))
  return getData<{ items: MistakeReviewItem[]; total: number; page: number; page_size: number }>(`/mistake-review/items?${params}`)
}

export function getMistakeItem(itemId: string, learnerId?: string) {
  const query = learnerId ? `?learner_id=${encodeURIComponent(learnerId)}` : ''
  return getData<MistakeReviewItem>(`/mistake-review/items/${itemId}${query}`)
}

export function startConsolidation(itemId: string, learnerId?: string) {
  return postData<ConsolidationAttempt>(`/mistake-review/items/${itemId}/start`, { learner_id: learnerId })
}

export function answerConsolidation(itemId: string, attemptId: string, answer: number, learnerId?: string) {
  return postData<ConsolidationResult>(`/mistake-review/items/${itemId}/attempts/${attemptId}/answer`, {
    learner_id: learnerId,
    answer,
  })
}
