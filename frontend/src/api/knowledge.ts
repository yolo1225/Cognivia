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

export interface QuestionBankItem {
  question_id: string
  domain_code: string
  knowledge_id: string
  knowledge_name: string
  related_knowledge_ids: string[]
  question_slot: number | null
  question_bank_uses: Array<
    'diagnosis' | 'graded_quiz' | 'mastery_validation' | 'mistake_consolidation'
  >
  reserve_role: 'consolidation' | 'mastery_transfer' | null
  assessment_focus: string | null
  quiz_level: 'foundation' | 'improvement' | 'challenge'
  question_type: 'single_choice' | 'short_answer'
  stem: string
  options: string[]
  answer: number | string
  explanation: string
  source_ref_ids: string[]
  source_quote: string | null
  evidence_quotes: Array<{ source_ref_id: string; quote: string }>
  difficulty: number
  status: 'active' | 'disabled'
  certification_status: 'pending' | 'certified' | 'rejected' | 'stale'
  certification_rule_version: string | null
  certified_at: string | null
  certification_summary: {
    deterministic_passed: boolean | null
    failed_fields: string[]
    source_content_hash: string | null
  }
  disabled_at: string | null
  disabled_reason: string | null
}

export interface QuestionBankResponse {
  domain_code: string
  items: QuestionBankItem[]
  total: number
  coverage: {
    total_items: number
    ready_items: number
    missing_knowledge_ids: string[]
    missing_quiz_knowledge_ids: string[]
    missing_mastery_reserve_knowledge_ids: string[]
    counts_by_knowledge: Record<
      string,
      {
        single_choice: number
        short_answer: number
        total: number
        graded_quiz: number
        mastery_reserve: number
      }
    >
  }
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

const relationTypeAliases: Record<string, string> = {
  prerequisite: 'prerequisite',
  next_step: 'dependent',
  depends_on: 'dependent',
  dependent: 'dependent',
  related_to: 'related',
  related: 'related',
}

export function normalizeKnowledgeRelation(relation: KnowledgeRelation): KnowledgeRelation {
  if (relation.relation_type === 'depends_on') {
    return {
      ...relation,
      source_id: relation.target_id,
      source_name: relation.target_name,
      target_id: relation.source_id,
      target_name: relation.source_name,
      relation_type: 'dependent',
    }
  }
  return {
    ...relation,
    relation_type: relationTypeAliases[relation.relation_type] ?? relation.relation_type,
  }
}

export function listKnowledgeItems(domainCode: string, limit = 100) {
  const params = new URLSearchParams({
    domain_code: domainCode,
    limit: String(limit),
  })
  return getData<KnowledgeItemsResponse>(`/knowledge/items?${params.toString()}`)
}

export function listQuestionBank(
  domainCode: string,
  status?: 'active' | 'disabled',
  certificationStatus?: QuestionBankItem['certification_status'],
) {
  const params = new URLSearchParams({ domain_code: domainCode, limit: '500' })
  if (status) params.set('status', status)
  if (certificationStatus) params.set('certification_status', certificationStatus)
  return getData<QuestionBankResponse>(`/knowledge/questions?${params.toString()}`)
}

export function disableQuestion(questionId: string, reason: string) {
  return postData<{ question: QuestionBankItem }>(
    `/knowledge/questions/${encodeURIComponent(questionId)}/disable`,
    { reason },
  )
}

export async function listKnowledgeRelations(domainCode: string) {
  const relations = await getData<KnowledgeRelation[]>(`/knowledge/relations?domain_code=${encodeURIComponent(domainCode)}`)
  return relations.map(normalizeKnowledgeRelation)
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
