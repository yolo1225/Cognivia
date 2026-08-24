import { getData } from './client'
import type { LearningPathState } from './learningPaths'
import type { LearningAdjustmentSummary } from './learningAdjustments'

export interface LearningReport {
  diagnosis_completed?: boolean
  profile_ready?: boolean
  profile_source?: string | null
  learner_id: string
  domain_code: string
  profile_id?: string | null
  profile_type?: string
  education_level?: string
  major?: string
  direction_tags?: string[]
  context_snapshot?: Record<string, unknown>
  radar: number[]
  path: string[]
  diagnostic_summary?: {
    answer_count: number
    correct_count: number
    accuracy: number
    latest_session_id?: string | null
  }
  path_detail?: Array<{
    name: string
    description?: string
  }>
  learning_path?: LearningPathState
  weak_knowledge?: Array<{
    knowledge_id: string
    name: string
    category: string
    weakness_level: number
  }>
  metrics: {
    hallucination_rate: number
    difficulty_match: number
    difficulty_match_accuracy?: number
    knowledge_coverage: number
  }
  loop_status: {
    diagnosis: string
    profile: string
    generation: string
    review: string
    feedback: string
    path_update: string
  }
  resource_summary: {
    total: number
    by_type: Record<string, number>
    recent: Array<{
      resource_id: string
      resource_type: string
      resource_type_label: string
      title: string
      difficulty: number
      review_status: string
      source_count: number
      generation_task_id?: string | null
      generation_status?: string | null
      generation_decision?: string | null
      generated_at?: string | null
    }>
  }
  review_summary: {
    total_reports: number
    passed: number
    review_status_counts: Record<string, number>
    source_coverage: number
  }
  feedback_summary: {
    total: number
    latest_action?: string | null
    learning_path_needs_refresh: boolean
    path_refresh_performed?: boolean
    recent: Array<{
      resource_id: string
      resource_title: string
      feedback_type: string
      rating: number
      triggered_action: string
      created_at?: string | null
    }>
  }
  learning_adjustments?: LearningAdjustmentSummary[]
  profile_changes?: Array<{
    proposal_id: string
    hypothesis_type: 'mastery_up' | 'support_down'
    decision: string
    status: string
    resource_decision?: string | null
    created_at?: string | null
    updated_at?: string | null
    profile_change_summary: {
      original_profile_id: string
      original_profile_version: number
      resulting_profile_id: string
      resulting_profile_version: number
      knowledge_id: string
      knowledge_name: string
      before_state: string
      after_state: string
      before_weakness_level?: number | null
      after_weakness_level?: number | null
      removed_from_weak_knowledge?: boolean
      removed_from_blind_spots?: boolean
      interaction_evidence_ids?: string[]
      evidence_ids?: string[]
      completed_node_id?: string | null
      current_node_id?: string | null
      profile_changed: boolean
      ability_score_changes: Record<string, { before: number; after: number }>
      ability_summary: string
    }
  }>
  next_actions: Array<{
    type: string
    label: string
    description: string
    route: string
  }>
}

export function getLearningReport(learnerId: string, taskId?: string) {
  const params = taskId ? `?task_id=${encodeURIComponent(taskId)}` : ''
  return getData<LearningReport>(`/reports/learners/${learnerId}${params}`)
}
