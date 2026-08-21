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
  domain_code: string
  status: string
  error_summary: string | null
  candidate_counts: Record<string, number>
  review_counts: Record<string, number>
}

export async function getKnowledgeImport(importId: string) {
  const response = await apiClient.get<ApiResponse<KnowledgeImportSummary>>(`/knowledge/imports/${importId}`)
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
