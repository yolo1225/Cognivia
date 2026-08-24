import { postData } from './client'

export interface LearningAdjustmentSummary {
  proposal_id: string
  hypothesis_type: 'mastery_up' | 'support_down'
  status: 'resource_pending'
  decision: 'confirmed_mastery' | 'confirmed_support_need'
  resource_recommendation: {
    proposal_id: string
    path_id: string
    path_node_id: string | null
    resource_types: string[]
    mode: 'next_node' | 'remedial'
  }
}

export function decideLearningAdjustmentResource(proposalId: string, decision: 'generate' | 'skip') {
  return postData<{ proposal_id: string; decision: 'generate' | 'skip'; task_id: string | null }>(
    `/learning-adjustments/${proposalId}/resource-decision`,
    { decision },
  )
}
