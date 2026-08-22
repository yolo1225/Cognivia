import { postData } from './client'

export type PathNodeStatus = 'locked' | 'current' | 'completed' | 'skipped'

export interface LearningPathNode {
  path_node_id: string
  knowledge_id: string
  title: string
  path_order: number
  status: PathNodeStatus
  completed_at?: string | null
  completion_evidence_ids: string[]
  completion_condition: { type: string; threshold: number }
  resource_state?: 'not_generated' | 'generating' | 'ready' | 'failed'
  resource_task_id?: string | null
}

export interface PathNodeAssessment {
  assessment_id: string
  path_id: string
  node_id: string
  question_id: string
  question_type: string
  difficulty: number
  stem: string
  options: string[]
  status: 'pending' | 'scored'
  score?: number | null
  passed?: boolean | null
}

export interface PathNodeAssessmentResult {
  assessment_id: string
  path_id: string
  node_id: string
  score: number
  threshold: number
  passed: boolean
  evidence_id: string
  completed_node_id?: string | null
  current_node_id?: string | null
  path_completed: boolean
  profile_adjustment_task_id?: string | null
}

export function startPathNodeAssessment(pathId: string, nodeId: string) {
  return postData<PathNodeAssessment>(
    `/learning-paths/${encodeURIComponent(pathId)}/nodes/${encodeURIComponent(nodeId)}/assessments`,
    {},
  )
}

export function answerPathNodeAssessment(pathId: string, nodeId: string, assessmentId: string, answer: number) {
  return postData<PathNodeAssessmentResult>(
    `/learning-paths/${encodeURIComponent(pathId)}/nodes/${encodeURIComponent(nodeId)}/assessments/${encodeURIComponent(assessmentId)}/answer`,
    { answer },
  )
}

export interface LearningPathState {
  path_id: string
  current_node_id?: string | null
  nodes: LearningPathNode[]
  stages: Array<{ name: string; description?: string; knowledge_ids?: string[] }>
}
