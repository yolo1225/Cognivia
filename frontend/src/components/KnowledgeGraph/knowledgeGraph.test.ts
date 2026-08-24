import { describe, expect, it } from 'vitest'
import type { KnowledgeItem, KnowledgeRelation } from '@/api/knowledge'
import { normalizeKnowledgeRelation } from '@/api/knowledge'
import { buildGraphModel, filterRelations, findKnowledgeItem, getNeighborIds, knowledgeNameLabel, relativeRelationLabel, resolveKnowledgeSelection } from './knowledgeGraph'

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

  it('normalizes import relation types before graph filtering', () => {
    const imported = [
      { ...relations[0], relation_type: 'next_step' },
      { ...relations[0], relation_type: 'depends_on' },
      { ...relations[1], relation_type: 'related_to' },
    ].map(normalizeKnowledgeRelation)
    expect(imported.map((relation) => relation.relation_type)).toEqual(['dependent', 'dependent', 'related'])
    expect(imported[1]).toMatchObject({ source_id: 'vector-search', target_id: 'rag-basics' })
    expect(filterRelations(imported, ['dependent', 'related'])).toHaveLength(3)
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

  it('keeps only selections that still exist in the current domain', () => {
    expect(resolveKnowledgeSelection(items, 'vector-search')).toBe('vector-search')
    expect(resolveKnowledgeSelection(items, 'removed-item')).toBeNull()
    expect(resolveKnowledgeSelection(items, null)).toBeNull()
  })

  it('removes repeated knowledge-base prefixes from display labels', () => {
    const prefixed = {
      ...items[0],
      name: 'AI 机器学习基础知识库 (ai_ml_basics) / 77. Bahdanau 注意力机制',
    }
    expect(knowledgeNameLabel(prefixed)).toBe('Bahdanau 注意力机制')
    expect(buildGraphModel([prefixed], [], prefixed.knowledge_id).nodes[0].name).toBe('Bahdanau 注意力机制')
  })

  it('labels directional relations from the selected node perspective', () => {
    expect(relativeRelationLabel(relations[0], 'rag-basics')).toBe('后继知识')
    expect(relativeRelationLabel(relations[0], 'vector-search')).toBe('前置知识')
    expect(relativeRelationLabel(relations[1], 'vector-search')).toBe('关联知识')
  })
})
