import { getData, postData } from './client'
import type { ResourceQualityMetrics } from './resources'

export interface GenerationTaskResult {
  task_id: string
  thread_id: string
  learner_id?: string | null
  profile_id?: string | null
  profile_version?: number | null
  profile_source?: string | null
  profile_changed_dimensions?: string[]
  status: string
  trigger_type: string
  execution_mode: string
  resource_types: string[]
  agent_graph: string
  decision: string
  agent_trace: Array<{
    agent_name: string
    status: string
    output: Record<string, unknown>
  }>
  resources: Array<{
    resource_id: string
    resource_type: string
    title: string
    difficulty: number
    review_status: string
    version?: number
    is_current?: boolean
    sources: string[]
    knowledge_coverage?: Record<string, string[]>
    membership_type?: 'generated' | 'inherited'
    freshness_status?: 'current' | 'knowledge_changed'
  }>
}

export interface GenerationTaskDetail {
  task_id: string
  thread_id?: string
  learner_id?: string | null
  profile_id?: string | null
  profile_version?: number | null
  profile_source?: string | null
  profile_changed_dimensions?: string[]
  status: string
  domain_code?: string
  progress?: number
  trigger_type?: string
  execution_mode?: string
  resource_types?: string[]
  event_type?: string
  source_task_id?: string | null
  is_current_package?: boolean
  inherited_resource_count?: number
  revision_count: number
  decision: string
  package_quality?: ResourceQualityMetrics | null
  failure_reason?: string | null
  package_coverage?: {
    required_knowledge_ids?: string[]
    covered_knowledge_ids?: string[]
    missing_knowledge_ids?: string[]
    coverage_score?: number
    passed?: boolean
  }
  source_feedback?: {
    feedback_type: string
    triggered_action: string
    recommended_action?: string | null
    comment: string
    rating?: number | null
  } | null
  source_resource?: {
    resource_id: string
    title: string
    resource_type: string
    version: number
  } | null
  created_at?: string | null
  updated_at?: string | null
  resources: GenerationTaskResult['resources']
}

export interface GenerationTaskFilters {
  learnerId?: string
  domainCode?: string
  status?: string
  limit?: number
}

export interface AgentRun {
  run_id: number
  task_id: string
  agent_name: string
  status: string
  input_summary: Record<string, unknown>
  output_summary: Record<string, unknown>
  error?: string | null
}

export function createGenerationTask(
  domainCode: string,
  profileId?: string,
  learnerId?: string,
  learningGoal = '个性化学习资源生成',
) {
  const body: Record<string, unknown> = {
    profile_id: profileId,
    domain_code: domainCode,
    trigger_type: 'initial_generation',
    execution_mode: 'auto',
    learning_goal: learningGoal,
    resource_types: ['lecture', 'practice_guide', 'graded_quiz'],
  }
  if (learnerId) body.learner_id = learnerId
  return postData<GenerationTaskResult>('/generation-tasks', body)
}

export function getAgentRuns(taskId: string) {
  return getData<AgentRun[]>(`/generation-tasks/${taskId}/agent-runs`)
}

export function getGenerationTask(taskId: string) {
  return getData<GenerationTaskDetail>(`/generation-tasks/${taskId}`)
}

export function retryGenerationTask(taskId: string) {
  return postData<GenerationTaskDetail>(`/generation-tasks/${taskId}/retry`, {})
}

export function getActiveGenerationTask(learnerId?: string) {
  const query = learnerId ? `?learner_id=${encodeURIComponent(learnerId)}` : ''
  return getData<GenerationTaskDetail | null>(`/generation-tasks/active${query}`)
}

export function listGenerationTasks(filters: GenerationTaskFilters = {}) {
  const params = new URLSearchParams()
  if (filters.learnerId) params.set('learner_id', filters.learnerId)
  if (filters.domainCode) params.set('domain_code', filters.domainCode)
  if (filters.status) params.set('status', filters.status)
  params.set('limit', String(filters.limit || 50))
  return getData<GenerationTaskDetail[]>(`/generation-tasks?${params.toString()}`)
}
