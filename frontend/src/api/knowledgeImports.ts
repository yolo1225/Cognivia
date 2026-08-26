import { apiClient } from './client'
import type { ApiResponse } from '@/types/api'

export type ImportCandidateType = 'knowledge_item' | 'knowledge_relation' | 'diagnostic_question'
export type ImportCandidateStatus = 'pending' | 'approved' | 'rejected' | 'needs_edit' | 'published'

export interface ImportCandidate {
  candidate_id: string
  candidate_type: ImportCandidateType
  payload: Record<string, any>
  source_locator: Record<string, any>
  confidence: number
  status: ImportCandidateStatus
  validation_errors: string[]
}

export interface KnowledgeImportSummary {
  import_id: string
  run_id: string
  document_public_id?: string
  domain_code: string
  status: string
  current_step: string
  attempt: number
  input_version: string
  error_code?: string | null
  error_summary: string | null
  candidate_counts?: Record<string, number>
  review_counts?: Record<string, number>
  knowledge_items?: number
  diagnostic_questions?: number
  relations_generated?: number
  relations_accepted?: number
  relations_filtered?: number
  factual_relations?: number
  recommended_relations?: number
  source_traceability?: number
  directional_relations?: number
  related_relations?: number
  path_participating_nodes?: number
  path_participation_ratio?: number
  isolated_nodes?: number
  isolated_node_ratio?: number
  cycle_count?: number
  unresolved_relation_conflicts?: number
  question_knowledge_coverage?: number
  retrieval_hit_rate?: number
  repair_rounds?: number
  quality_gate_passed?: boolean
  blocking_issues?: Array<{ code: string; message: string; actual?: number; count?: number }>
  direction_metrics?: DirectionQualityMetric[]
  projected_readiness?: Record<string, any>
  candidate_manifest?: { index_version: string; active_collection: string } | null
  smoke_test?: Record<string, any> | null
  quality_baseline_version?: string
  completed_batches?: number
  failed_batches?: number
  running_batches?: number
  total_batches?: number
  reused_batches?: number
  model_calls?: number
  tokens_input?: number
  tokens_output?: number
  model_duration_ms?: number
  empty_result_batches?: number
  elapsed_ms?: number
  eta_seconds?: number
  events?: ImportEvent[]
}

export interface DirectionQualityMetric {
  value: string
  label: string
  nodes: number
  directional_relations: number
  path_participating_nodes: number
  path_participation_ratio: number
  isolated_nodes: number
  longest_path_nodes: number
}

export interface ImportEvent {
  event_id: number
  run_id: string
  step: string
  attempt: number
  status: string
  timestamp?: string
  error_summary?: string | null
}

export interface GraphPreviewNode {
  id: string
  knowledge_id: string
  name: string
  category: string
  difficulty: number
  tags: string[]
  action: string
  source_chunk_ids: string[]
  directions: string[]
  isolated: boolean
  path_participating: boolean
  source_complete: boolean
}

export interface GraphPreviewEdge {
  id: string
  source: string
  target: string
  relation_type: string
  confidence: number
  accepted: boolean
  reason?: string
  evidence?: string | string[]
  review_result: string
  evidence_kind: 'text_quote' | 'structured_metadata' | 'curriculum_rule'
  score_components: Record<string, number>
  generation_method?: string
  review_verdict?: string
  filter_reasons: string[]
}

export interface GraphPreview { import_id: string; nodes: GraphPreviewNode[]; edges: GraphPreviewEdge[] }

export async function getKnowledgeImport(importId: string) {
  const response = await apiClient.get<ApiResponse<KnowledgeImportSummary>>(`/knowledge/imports/${importId}`)
  return response.data.data
}

export async function cancelKnowledgeImport(importId: string) {
  const response = await apiClient.post<ApiResponse<KnowledgeImportSummary & { cancel_requested: boolean }>>(
    `/knowledge/imports/${importId}/cancel`,
    {},
  )
  return response.data.data
}

export async function getKnowledgeImportSummary(importId: string) {
  const response = await apiClient.get<ApiResponse<KnowledgeImportSummary>>(`/knowledge/imports/${importId}/summary`)
  return response.data.data
}

export async function getKnowledgeImportGraph(importId: string) {
  const response = await apiClient.get<ApiResponse<GraphPreview>>(`/knowledge/imports/${importId}/graph-preview`)
  return response.data.data
}

export async function confirmKnowledgeImport(importId: string, inputVersion: string, indexVersion: string) {
  const response = await apiClient.post<ApiResponse<Record<string, any>>>(`/knowledge/imports/${importId}/confirm-publish`, {
    input_version: inputVersion,
    index_version: indexVersion,
  })
  return response.data.data
}

export async function listImportCandidates(importId: string) {
  const response = await apiClient.get<ApiResponse<{ import_id: string; candidates: ImportCandidate[] }>>(`/knowledge/imports/${importId}/candidates`)
  return response.data.data.candidates
}

export async function updateImportCandidate(importId: string, candidateId: string, payload: Record<string, any>) {
  const response = await apiClient.patch<ApiResponse<ImportCandidate>>(`/knowledge/imports/${importId}/candidates/${candidateId}`, { payload })
  return response.data.data
}

export async function validateKnowledgeImport(importId: string) {
  const response = await apiClient.post<ApiResponse<{ total: number; valid: number; invalid: number }>>(`/knowledge/imports/${importId}/validate`, {})
  return response.data.data
}

export async function approveKnowledgeImport(importId: string) {
  const response = await apiClient.post<ApiResponse<Record<string, number | string>>>(`/knowledge/imports/${importId}/approve`, {})
  return response.data.data
}

export async function buildKnowledgeImportIndex(importId: string) {
  const response = await apiClient.post<ApiResponse<{ job_id: number; status: string }>>(`/knowledge/imports/${importId}/build-index`, {})
  return response.data.data
}

export async function smokeKnowledgeImport(importId: string) {
  const response = await apiClient.post<ApiResponse<{ passed: boolean }>>(`/knowledge/imports/${importId}/smoke-test`, {})
  return response.data.data
}

export async function publishKnowledgeImport(importId: string) {
  const response = await apiClient.post<ApiResponse<{ import_id: string; status: string }>>(`/knowledge/imports/${importId}/publish`, {})
  return response.data.data
}
