import { describe, expect, it } from 'vitest'
import type { KnowledgeItem, KnowledgeRelation } from '@/api/knowledge'
import { buildGraphModel, filterRelations, findKnowledgeItem, getNeighborIds } from './knowledgeGraph'

const items: KnowledgeItem[] = [
  {
    knowledge_id: 'rag-basics', domain_code: 'ai_app_dev', name: 'RAG 基础', category: 'RAG', difficulty: 2,
    tags: ['检索'], content: '', source_title: '课程资料', source_url: null, license_note: '', needs_reembedding: false,
  },
  {
    knowledge_id: 'vector-search', domain_code: 'ai_app_dev', name: '向量检索', category: 'RAG', difficulty: 3,
    tags: ['向量'], content: '', source_title: '课程资料', source_url: null, license_note: '', needs_reembedding: false,
  },
  {
    knowledge_id: 'prompt-design', domain_code: 'ai_app_dev', name: '提示词设计', category: 'Prompt', difficulty: 2,
    tags: [], content: '', source_title: '课程资料', source_url: null, license_note: '', needs_reembedding: false,
  },
]

const relations: KnowledgeRelation[] = [
  { source_id: 'rag-basics', source_name: 'RAG 基础', target_id: 'vector-search', target_name: '向量检索', relation_type: 'prerequisite' },
  { source_id: 'vector-search', source_name: '向量检索', target_id: 'prompt-design', target_name: '提示词设计', relation_type: 'related' },
]

describe('knowledge graph data', () => {
  it('keeps isolated knowledge items as graph nodes', () => {
    const model = buildGraphModel(items, relations)

    expect(model.nodes).toHaveLength(3)
    expect(model.nodes.find((node) => node.id === 'prompt-design')).toBeDefined()
    expect(model.links).toHaveLength(2)
  })

  it('filters relations by enabled type', () => {
    expect(filterRelations(relations, ['prerequisite'])).toEqual([relations[0]])
    expect(filterRelations(relations, [])).toEqual([])
  })

  it('locates knowledge by a partial search query', () => {
    expect(findKnowledgeItem(items, '向量')?.knowledge_id).toBe('vector-search')
    expect(findKnowledgeItem(items, '不存在')).toBeNull()
  })

  it('identifies and highlights selected-node neighbors', () => {
    const neighborIds = getNeighborIds(relations, 'vector-search')
    const model = buildGraphModel(items, relations, 'vector-search')

    expect(neighborIds).toEqual(new Set(['vector-search', 'rag-basics', 'prompt-design']))
    expect(model.nodes.find((node) => node.id === 'vector-search')?.symbolSize).toBe(46)
  })
})
