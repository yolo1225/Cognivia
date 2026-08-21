import { getData, patchData, postData } from '@/api/client'

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
  distance: number
  preview: string
}

export interface KnowledgeSearchResponse {
  domain_code: string
  query: string
  matches: KnowledgeSearchMatch[]
  total: number
  embedding_model: string
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

export interface RebuildIndexStartResult {
  job_id: number
  status: 'running'
  domain_code: string
}

export interface RebuildIndexStatus {
  job_id: number | null
  status: 'idle' | 'running' | 'success' | 'failed' | 'interrupted'
  running: boolean
  domain_code: string
  started_at: string | null
  finished_at: string | null
  message: string
  result: {
    status?: string
    mode?: string
    indexed_items?: number
    indexed_chunks?: number
    reused_chunks?: number
    reembedded_items?: number
    embedding_model?: string
    duration_ms?: number
  } | null
}

export interface KnowledgeRelation {
  source_id: string
  source_name: string
  target_id: string
  target_name: string
  relation_type: string
}

export function listKnowledgeItems(domainCode: string, limit = 100) {
  const params = new URLSearchParams({
    domain_code: domainCode,
    limit: String(limit),
  })
  return getData<KnowledgeItemsResponse>(`/knowledge/items?${params.toString()}`)
}

export function listKnowledgeRelations(domainCode: string) {
  return getData<KnowledgeRelation[]>(`/knowledge/relations?domain_code=${encodeURIComponent(domainCode)}`)
}

export function searchKnowledge(query: string, domainCode: string, nResults = 5) {
  const params = new URLSearchParams({
    query,
    domain_code: domainCode,
    n_results: String(nResults),
  })
  return getData<KnowledgeSearchResponse>(`/knowledge/search?${params.toString()}`)
}

export function createKnowledgeItem(payload: KnowledgeItemCreateRequest) {
  return postData<KnowledgeItemCreateResponse>('/knowledge/items', payload)
}

export function updateKnowledgeItem(knowledgeId: string, payload: KnowledgeItemUpdateRequest) {
  return patchData<KnowledgeItemCreateResponse>(`/knowledge/items/${knowledgeId}`, payload)
}

export function rebuildKnowledgeIndex(domainCode: string) {
  return postData<RebuildIndexStartResult>(`/knowledge/rebuild-index?domain_code=${encodeURIComponent(domainCode)}`)
}

export function getRebuildIndexStatus(domainCode: string) {
  return getData<RebuildIndexStatus>(`/knowledge/rebuild-index/status?domain_code=${encodeURIComponent(domainCode)}`)
}
