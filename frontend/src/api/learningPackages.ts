import { getData, postData } from './client'
import type { ResourceSummary } from './resources'
import type { GenerationBasis } from './generation'

export interface KnowledgeImpact {
  impact_id: string
  status: 'pending' | 'dismissed' | 'refreshing' | 'resolved'
  reason: string
  affected_knowledge_ids: string[]
  affected_resource_ids: string[]
  affected_resource_count: number
  change_sequence: number
  refresh_available: boolean
  index_status: 'ready' | 'updating'
}

export interface LearningPackage {
  package_id: string
  task_id: string
  learner_id?: string | null
  profile_id?: string | null
  profile_version?: number | null
  status: string
  path_id?: string | null
  path_node_id?: string | null
  path_node_title?: string | null
  path_node_order?: number | null
  generation_basis?: GenerationBasis | null
  event_type: string
  source_task_id?: string | null
  is_current_package: boolean
  resources: Array<ResourceSummary & {
    membership_type: 'generated' | 'inherited'
    freshness_status: 'current' | 'knowledge_changed'
  }>
  knowledge_impact?: KnowledgeImpact | null
  package_quality?: ResourceSummary['package_quality']
  created_at?: string | null
}

export function getCurrentLearningPackage(domainCode: string, learnerId?: string) {
  const params = new URLSearchParams({ domain_code: domainCode })
  if (learnerId) params.set('learner_id', learnerId)
  return getData<LearningPackage | null>(`/learning-packages/current?${params.toString()}`)
}

export function getLearningPackage(taskId: string) {
  return getData<LearningPackage>(`/learning-packages/${encodeURIComponent(taskId)}`)
}

export function dismissKnowledgeImpact(taskId: string) {
  return postData<LearningPackage>(`/learning-packages/${taskId}/knowledge-impact/dismiss`, {})
}

export function refreshAffectedResources(taskId: string) {
  return postData<{
    task_id: string
    thread_id: string
    status: string
    event_type: string
    source_task_id: string
    resource_types: string[]
  }>(`/learning-packages/${taskId}/knowledge-refresh`, {})
}
