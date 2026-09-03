import { postData } from './client'

export interface LearningAdjustmentSummary {
  proposal_id: string
  hypothesis_type: 'mastery_up' | 'support_down'
  status: 'resource_pending' | 'resource_started' | 'resource_skipped' | 'evidence_recorded' | 'no_change'
  decision?: 'confirmed_mastery' | 'confirmed_support_need' | null
  resource_recommendation: {
    proposal_id: string
    path_id: string
    path_node_id: string | null
    resource_types: string[]
    mode: 'next_node' | 'remedial'
    decision_type?: 'remedial' | 'challenge' | 'no_generation' | 'future_path_reprioritize' | 'next_stage'
    reason?: string
    affected_knowledge_ids?: string[]
    requires_confirmation?: boolean
    current_resource_handling?: 'keep_current' | 'keep_for_review' | 'archive_for_review'
  }
  generation_task?: {
    task_id: string
    status: 'pending' | 'retry_pending' | 'running' | 'revision_required' | 'completed' | 'failed'
    decision: string
    failure_reason?: string | null
    event_type: string
    published_resource_types: string[]
  } | null
  recovery_available?: boolean
  profile_version?: number | null
  previous_profile_version?: number | null
  current_node?: { path_node_id?: string | null; title?: string | null }
  affected_resources?: Array<{ resource_id: string; resource_type: string; title: string }>
  node_gate?: {
    can_advance: boolean
    reason: string
    blocking_mistake_count: number
    quiz_completed: boolean
  } | null
  route_message?: { reason: string; title: string; description: string } | null
}

export function decideLearningAdjustmentResource(proposalId: string, decision: 'generate' | 'skip') {
  return postData<{ proposal_id: string; decision: 'generate' | 'skip'; task_id: string | null; recovered?: boolean }>(
    `/learning-adjustments/${proposalId}/resource-decision`,
    { decision },
  )
}
