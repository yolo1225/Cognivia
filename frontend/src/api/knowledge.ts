import { getData, patchData, postData, type MutationOptions } from '@/api/client'

export interface KnowledgeItem {
  knowledge_id: string
  domain_code: string
  name: string
  category: string
  difficulty: number
  tags: string[]
  content: string
  source_title: string
  source_url: string | null
  license_note: string
  needs_reembedding: boolean
}

export interface KnowledgeItemsResponse {
  domain_code: string
  items: KnowledgeItem[]
  total: number
  limit: number
  offset: number
  mvp_target: number
}

export interface KnowledgeSearchMatch {
  id: string
  knowledge_id: string
  name: string
  category: string
  difficulty: number
  source_title: string
  similarity: number
  preview: string
}

export interface KnowledgeSearchResponse {
  domain_code: string
  query: string
  matches: KnowledgeSearchMatch[]
  total: number
  embedding_model: string
  index_version: string
}

export interface KnowledgeItemCreateRequest {
  domain_code: string
  name: string
  category: string
  difficulty: number
  tags: string[]
  content: string
  source_title: string
  source_url?: string | null
  license_note: string
}

export interface KnowledgeItemCreateResponse {
  item: KnowledgeItem
  index_status: string
  affected_learning_paths: number
  affected_resources: number
  affected_knowledge_ids: string[]
  next_action: string
}

export interface KnowledgeItemUpdateRequest {
  name?: string
  category?: string
  difficulty?: number
  tags?: string[]
  content?: string
  source_title?: string
  source_url?: string | null
  license_note?: string
  prerequisites?: string[]
  related?: string[]
}

export interface KnowledgeIndexResult {
  status: 'built' | 'unchanged'
  affected_domain: string
  indexed_items: number
  indexed_chunks: number
  embedding_model: string
  active_collection: string
  index_version: string
}

export interface CandidateIndexStatus {
  domain_code: string
  status: 'ready' | 'missing' | 'invalid' | 'stale'
  pending_reembedding: number
  active_collection?: string
  indexed_items?: number
  indexed_chunks?: number
  embedding_model?: string
  index_version?: string
  last_successful_sync_at?: string
  reason?: string
}

export function listKnowledgeItems(domainCode = 'ai_app_dev', limit = 100) {
  const params = new URLSearchParams({
    domain_code: domainCode,
    limit: String(limit),
  })
  return getData<KnowledgeItemsResponse>(`/knowledge/items?${params.toString()}`)
}

export function searchKnowledge(query: string, domainCode = 'ai_app_dev', nResults = 5) {
  const params = new URLSearchParams({
    query,
    domain_code: domainCode,
    n_results: String(nResults),
  })
  return getData<KnowledgeSearchResponse>(`/knowledge/retrieval-preview?${params.toString()}`)
}

export function createKnowledgeItem(
  payload: KnowledgeItemCreateRequest,
  options: MutationOptions = {},
) {
  return postData<KnowledgeItemCreateResponse>('/knowledge/items', payload, options)
}

export function updateKnowledgeItem(
  knowledgeId: string,
  payload: KnowledgeItemUpdateRequest,
  options: MutationOptions = {},
) {
  return patchData<KnowledgeItemCreateResponse>(`/knowledge/items/${knowledgeId}`, payload, options)
}

export function rebuildKnowledgeIndex(options: MutationOptions = {}) {
  return postData<KnowledgeIndexResult>('/knowledge/reindex?domain_code=ai_app_dev', {}, options)
}

export function getCandidateIndexStatus(domainCode = 'ai_app_dev') {
  return getData<CandidateIndexStatus>(`/knowledge/reindex/status?domain_code=${domainCode}`)
}
