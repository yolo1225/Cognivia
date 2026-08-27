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
  ability_profile?: Record<string, any>
  path: string[]
  diagnostic_summary?: {
    answer_count: number
    correct_count: number
    total_score: number
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
  progress_comparison?: LearningProgressComparison
  learning_history?: LearningHistoryEvent[]
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

export interface LearningProgressComparison {
  available: boolean
  unavailable_reason?: string | null
  period?: { started_at: string; updated_at: string }
  baseline?: { profile_id: string; profile_version: number; radar: number[]; weak_knowledge_count: number }
  current?: { profile_id: string; profile_version: number; radar: number[]; weak_knowledge_count: number }
  ability_changes?: Array<{ key: string; label: string; before: number; after: number; delta: number }>
  average_ability_delta?: number
  knowledge_changes?: {
    consolidated: KnowledgeProgressItem[]
    improving: KnowledgeProgressItem[]
    unchanged: KnowledgeProgressItem[]
    new_weakness: KnowledgeProgressItem[]
  }
  path_progress?: { total: number; completed: number; current: number; locked: number; skipped: number; completion_rate: number | null }
  mistake_consolidation?: { total: number; pending: number; in_progress: number; consolidated: number; verified: number; consolidation_rate: number | null }
  timeline?: Array<{ type: string; title: string; occurred_at: string; profile_version: number | null; confidence: number; reason: string | null; evidence_refs: string[]; governance_status?: string; path_result?: Record<string, unknown> }>
}

export interface LearningHistoryEvent {
  event_id: string
  type: string
  title: string
  occurred_at: string
  path_id?: string | null
  path_node_id?: string | null
  task_id?: string | null
  feedback_id?: string | null
  profile_version?: number | null
  reason?: string | null
  evidence_refs: string[]
}

export interface KnowledgeProgressItem {
  knowledge_id: string
  name: string
  before_level?: number | null
  after_level?: number | null
}
