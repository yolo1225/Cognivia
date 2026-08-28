import { postData } from './client'

export interface LearningAdjustmentSummary {
  proposal_id: string
  hypothesis_type: 'mastery_up' | 'support_down'
  status: 'resource_pending' | 'resource_started'
  decision?: 'confirmed_mastery' | 'confirmed_support_need' | null
  resource_recommendation: {
    proposal_id: string
    path_id: string
    path_node_id: string | null
    resource_types: string[]
    mode: 'next_node' | 'remedial'
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
}

export function decideLearningAdjustmentResource(proposalId: string, decision: 'generate' | 'skip') {
  return postData<{ proposal_id: string; decision: 'generate' | 'skip'; task_id: string | null; recovered?: boolean }>(
    `/learning-adjustments/${proposalId}/resource-decision`,
    { decision },
  )
}
