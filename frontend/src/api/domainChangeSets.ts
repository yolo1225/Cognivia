import { apiClient } from './client'
import type { ApiResponse } from '@/types/api'

export interface DomainChangeSet {
  change_set_id: string
  domain_code: string
  status: 'preparing' | 'ready_for_questions' | 'questions_preparing' | 'ready_to_activate' | 'activated' | 'cancelled'
  mode: 'append' | 'replace'
  summary: { documents?: string[]; question_runs?: string[]; remaining_question_slots?: number }
  error_summary: string | null
}

export async function listDomainChangeSets(domainCode: string) {
  const response = await apiClient.get<ApiResponse<{ domain_code: string; change_sets: DomainChangeSet[] }>>(
    '/domain-change-sets',
    { params: { domain_code: domainCode } },
  )
  return response.data.data.change_sets
}

export async function activateDomainChangeSet(changeSetId: string) {
  const response = await apiClient.post<ApiResponse<DomainChangeSet>>(
    `/domain-change-sets/${changeSetId}/activate`,
    {},
  )
  return response.data.data
}
