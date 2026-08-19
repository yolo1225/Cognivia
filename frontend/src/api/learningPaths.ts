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
}

export interface LearningPathState {
  path_id: string
  current_node_id?: string | null
  nodes: LearningPathNode[]
  stages: Array<{ name: string; description?: string; knowledge_ids?: string[] }>
}

export interface PathVerification {
  path_id: string
  node_id: string
  verified: boolean
  reason: string
  threshold: number
  best_score?: number | null
  evidence_ids: string[]
  node: LearningPathNode
}

export function verifyPathNode(pathId: string, nodeId: string, evidenceIds: string[] = []) {
  return postData<PathVerification>(
    `/learning-paths/${encodeURIComponent(pathId)}/nodes/${encodeURIComponent(nodeId)}/verify`,
    { evidence_ids: evidenceIds },
  )
}

export function completePathNode(pathId: string, nodeId: string, evidenceIds: string[]) {
  return postData<{ path: LearningPathState; completed_node_id: string }>(
    `/learning-paths/${encodeURIComponent(pathId)}/nodes/${encodeURIComponent(nodeId)}/complete`,
    { evidence_ids: evidenceIds },
  )
}
