import { apiClient } from './client'
import type { ApiResponse } from '@/types/api'

export interface QuestionImportRun {
  run_id: string
  domain_code: string
  template_version: string
  knowledge_catalog_fingerprint: string
  question_inventory_fingerprint: string
  knowledge_scope: string[]
  change_set_id: string | null
  original_name: string
  status: 'uploaded' | 'needs_attention' | 'ready_to_publish' | 'published' | 'cancelled'
  error_summary: string | null
  row_count: number
  valid_row_count: number
  needs_attention_count: number
  template_invalid_count: number
  published_at: string | null
}

export interface QuestionImportRow {
  row_id: string
  row_number: number
  question_external_id: string
  slot_key: string
  knowledge_ref: string
  question_type: string
  difficulty: number | null
  stem: string
  options: string[]
  answer: string | number | null
  explanation: string
  rubric: string[]
  purpose: string | null
  quiz_level: string | null
  status: string
  validation_errors: string[]
}

export async function downloadQuestionTemplate(
  domainCode: string,
  knowledgeIds: string[] = [],
  changeSetId?: string,
) {
  return apiClient.get('/question-imports/template', {
    params: { domain_code: domainCode, knowledge_id: knowledgeIds, change_set_id: changeSetId },
    responseType: 'blob',
  })
}

export async function uploadQuestionImport(file: File, domainCode: string, changeSetId?: string) {
  const response = await apiClient.post<ApiResponse<QuestionImportRun>>('/question-imports', file, {
    params: { domain_code: domainCode, change_set_id: changeSetId },
    headers: { 'Content-Type': file.type || 'application/octet-stream', 'X-File-Name': encodeURIComponent(file.name) },
  })
  return response.data.data
}

export async function getQuestionImport(runId: string) {
  const response = await apiClient.get<ApiResponse<QuestionImportRun>>(`/question-imports/${runId}`)
  return response.data.data
}

export async function listQuestionImportRows(runId: string) {
  const response = await apiClient.get<ApiResponse<{ run_id: string; rows: QuestionImportRow[] }>>(`/question-imports/${runId}/rows`)
  return response.data.data.rows
}

export async function validateQuestionImport(runId: string) {
  const response = await apiClient.post<ApiResponse<QuestionImportRun>>(`/question-imports/${runId}/validate`, {})
  return response.data.data
}

export async function publishQuestionImport(runId: string) {
  const response = await apiClient.post<ApiResponse<QuestionImportRun>>(`/question-imports/${runId}/confirm-publish`, {})
  return response.data.data
}
