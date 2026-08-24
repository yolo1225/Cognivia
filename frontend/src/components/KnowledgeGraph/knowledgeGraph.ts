import type { KnowledgeItem, KnowledgeRelation } from '@/api/knowledge'

export const relationTypes = ['prerequisite', 'dependent', 'related'] as const
export type RelationType = (typeof relationTypes)[number]

export const relationMeta: Record<string, { label: string; color: string; lineType: 'solid' | 'dashed' | 'dotted' }> = {
  prerequisite: { label: '显式前置', color: '#315fce', lineType: 'solid' },
  dependent: { label: '教学顺序', color: '#138560', lineType: 'solid' },
  related: { label: '关联关系', color: '#b96308', lineType: 'dashed' },
}

const categoryColors = ['#315fce', '#138560', '#b96308', '#7c4d9e', '#007a8a', '#c44569']

export interface GraphNode {
  id: string
  name: string
  category: number
  value: number
  symbolSize: number
  itemStyle: { color: string; opacity?: number }
  label?: { show: boolean; color: string; fontWeight?: number }
}

export interface GraphLink {
  source: string
  target: string
  value: string
  lineStyle: { color: string; type: 'solid' | 'dashed' | 'dotted'; width: number; opacity?: number }
}

export interface GraphModel {
  categories: Array<{ name: string; itemStyle: { color: string } }>
  nodes: GraphNode[]
  links: GraphLink[]
}

export function filterRelations(relations: KnowledgeRelation[], enabledTypes: Iterable<string>) {
  const enabled = new Set(enabledTypes)
  return relations.filter((relation) => enabled.has(relation.relation_type))
}

export function findKnowledgeItem(items: KnowledgeItem[], query: string) {
  const normalized = query.trim().toLocaleLowerCase()
  if (!normalized) return null
  return items.find((item) => knowledgeNameLabel(item).toLocaleLowerCase().includes(normalized)) ?? null
}

export function relativeRelationLabel(
  relation: KnowledgeRelation,
  selectedId: string | null,
) {
  if (relation.relation_type === 'related') return '关联知识'
  return relation.source_id === selectedId ? '后继知识' : '前置知识'
}

export function knowledgeNameLabel(item: Pick<KnowledgeItem, 'name' | 'domain_code'>) {
  const sourcePrefix = /^.*?\([a-z][a-z0-9_-]*\)\s*[/／]\s*\d+\s*[.．、:-]?\s*/i
  return item.name.replace(sourcePrefix, '').trim() || item.name
}

export function resolveKnowledgeSelection(
  items: KnowledgeItem[],
  requestedId: string | null | undefined,
) {
  if (!requestedId) return null
  return items.some((item) => item.knowledge_id === requestedId) ? requestedId : null
}

export function getNeighborIds(relations: KnowledgeRelation[], knowledgeId: string | null) {
  if (!knowledgeId) return new Set<string>()
  const neighbors = new Set<string>([knowledgeId])
  for (const relation of relations) {
    if (relation.source_id === knowledgeId) neighbors.add(relation.target_id)
    if (relation.target_id === knowledgeId) neighbors.add(relation.source_id)
  }
  return neighbors
}

export function buildGraphModel(
  items: KnowledgeItem[],
  relations: KnowledgeRelation[],
  selectedId: string | null = null,
  searchQuery = '',
): GraphModel {
  const categories = [...new Set(items.map((item) => item.category || '未分类'))]
  const categoryIndex = new Map(categories.map((category, index) => [category, index]))
  const neighbors = getNeighborIds(relations, selectedId)
  const normalizedQuery = searchQuery.trim().toLocaleLowerCase()

  return {
    categories: categories.map((name, index) => ({
      name,
      itemStyle: { color: categoryColors[index % categoryColors.length] },
    })),
    nodes: items.map((item) => {
      const isSelected = item.knowledge_id === selectedId
      const isNeighbor = !selectedId || neighbors.has(item.knowledge_id)
      const displayName = knowledgeNameLabel(item)
      const isMatched = Boolean(normalizedQuery) && displayName.toLocaleLowerCase().includes(normalizedQuery)
      const category = categoryIndex.get(item.category || '未分类') ?? 0

      return {
        id: item.knowledge_id,
        name: displayName,
        category,
        value: item.difficulty,
        symbolSize: isSelected ? 46 : 28 + item.difficulty * 3,
        itemStyle: {
          color: categoryColors[category % categoryColors.length],
          opacity: isNeighbor ? 1 : 0.18,
        },
        label: {
          show: isSelected || isMatched,
          color: '#172231',
          fontWeight: isSelected ? 700 : undefined,
        },
      }
    }),
    links: relations.map((relation) => {
      const meta = relationMeta[relation.relation_type] ?? relationMeta.related
      const isConnected = !selectedId || relation.source_id === selectedId || relation.target_id === selectedId
      return {
        source: relation.source_id,
        target: relation.target_id,
        value: meta.label,
        lineStyle: {
          color: meta.color,
          type: meta.lineType,
          width: isConnected ? 2 : 1,
          opacity: isConnected ? 0.72 : 0.1,
        },
      }
    }),
  }
}
