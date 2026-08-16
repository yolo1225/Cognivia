<template>
  <section class="knowledge-graph" aria-label="知识关系图谱">
    <div class="graph-toolbar">
      <label class="graph-search">
        <span>搜索知识点</span>
        <input v-model="searchQuery" type="search" placeholder="输入名称定位节点" @keydown.enter.prevent="selectSearchMatch" />
      </label>
      <div class="relation-filters" role="group" aria-label="关系类型筛选">
        <label v-for="type in relationTypes" :key="type" class="relation-filter">
          <input v-model="enabledTypes" type="checkbox" :value="type" />
          <i :style="{ backgroundColor: relationMeta[type].color }"></i>
          {{ relationMeta[type].label }}
        </label>
      </div>
      <div class="graph-actions">
        <button class="btn small" type="button" @click="fitGraph">适应视图</button>
        <button class="btn small" type="button" :disabled="!selectedId && !searchQuery" @click="clearSelection">重置选择</button>
      </div>
    </div>

    <div v-if="loading" class="graph-state" role="status">正在加载知识图谱...</div>
    <div v-else-if="error" class="graph-state error" role="alert">{{ error }}</div>
    <div v-else-if="items.length === 0" class="graph-state">当前领域尚无知识点，无法构建知识图谱。</div>
    <div v-else class="graph-layout">
      <div class="graph-stage">
        <div ref="chartRef" class="graph-canvas" aria-label="可缩放和拖拽的知识图谱" />
        <p class="graph-hint">{{ items.length }} 个知识点，{{ filteredRelations.length }} 条当前可见关系。点击节点查看其上下游关系。</p>
      </div>
      <aside class="node-detail" aria-live="polite">
        <template v-if="selectedItem">
          <span class="detail-label">已选知识点</span>
          <h3>{{ selectedItem.name }}</h3>
          <div class="detail-meta">
            <span>{{ selectedItem.category || '未分类' }}</span>
            <span>难度 {{ selectedItem.difficulty }}/5</span>
          </div>
          <p>{{ selectedItem.source_title || '未标注来源' }}</p>
          <div v-if="selectedItem.tags.length" class="detail-tags">
            <span v-for="tag in selectedItem.tags" :key="tag">{{ tag }}</span>
          </div>
          <div class="detail-relations">
            <strong>关联知识</strong>
            <ul v-if="selectedRelations.length">
              <li v-for="relation in selectedRelations" :key="`${relation.source_id}-${relation.target_id}-${relation.relation_type}`">
                <button type="button" @click="selectRelationTarget(relation)">
                  <span :style="{ color: relationMeta[relation.relation_type]?.color || relationMeta.related.color }">{{ relationMeta[relation.relation_type]?.label || '关联关系' }}</span>
                  {{ otherNodeName(relation) }}
                </button>
              </li>
            </ul>
            <p v-else>当前筛选条件下没有关联知识点。</p>
          </div>
        </template>
        <template v-else>
          <span class="detail-label">知识图谱</span>
          <h3>选择一个知识点</h3>
          <p>按分类识别节点，按边的颜色和线型区分关系类型。可通过搜索或图谱点击定位知识点。</p>
          <div class="category-legend">
            <span v-for="category in graphModel.categories" :key="category.name">
              <i :style="{ backgroundColor: category.itemStyle.color }"></i>{{ category.name }}
            </span>
          </div>
        </template>
      </aside>
    </div>

  </section>
</template>

<script setup lang="ts">
import * as echarts from 'echarts'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { KnowledgeItem, KnowledgeRelation } from '@/api/knowledge'
import {
  buildGraphModel,
  filterRelations,
  findKnowledgeItem,
  relationMeta,
  relationTypes,
} from './knowledgeGraph'

const props = withDefaults(defineProps<{
  items: KnowledgeItem[]
  relations: KnowledgeRelation[]
  loading?: boolean
  error?: string
}>(), {
  loading: false,
  error: '',
})

const chartRef = ref<HTMLDivElement | null>(null)
const selectedId = ref<string | null>(null)
const searchQuery = ref('')
const enabledTypes = ref<string[]>([...relationTypes])
let chart: echarts.ECharts | null = null
let resizeObserver: ResizeObserver | null = null

const filteredRelations = computed(() => filterRelations(props.relations, enabledTypes.value))
const graphModel = computed(() => buildGraphModel(props.items, filteredRelations.value, selectedId.value, searchQuery.value))
const selectedItem = computed(() => props.items.find((item) => item.knowledge_id === selectedId.value) ?? null)
const selectedRelations = computed(() => filteredRelations.value.filter((relation) => relation.source_id === selectedId.value || relation.target_id === selectedId.value))

function renderGraph() {
  if (!chartRef.value || props.loading || props.error || props.items.length === 0) return
  chart ??= echarts.init(chartRef.value)
  chart.off('click')
  chart.on('click', (params) => {
    const nodeData = params.data as { id?: unknown }
    if (params.dataType === 'node' && typeof nodeData.id === 'string') selectNode(nodeData.id)
  })
  chart.setOption({
    animationDurationUpdate: 220,
    tooltip: {
      trigger: 'item',
      formatter: (params: { dataType?: string; data?: { name?: string; value?: string | number } }) => {
        if (params.dataType === 'edge') return String(params.data?.value || '')
        return `${params.data?.name || ''}<br />难度 ${params.data?.value || '-'} / 5`
      },
    },
    series: [{
      type: 'graph',
      layout: 'force',
      roam: true,
      draggable: true,
      focusNodeAdjacency: false,
      categories: graphModel.value.categories,
      data: graphModel.value.nodes,
      links: graphModel.value.links,
      label: { position: 'right' },
      lineStyle: { curveness: 0.08 },
      edgeSymbol: ['none', 'arrow'],
      edgeSymbolSize: 8,
      force: { repulsion: 340, edgeLength: [70, 155], gravity: 0.08 },
    }],
  }, { notMerge: true })
}

function selectNode(knowledgeId: string) {
  selectedId.value = knowledgeId
  nextTick(renderGraph)
}

function selectSearchMatch() {
  const match = findKnowledgeItem(props.items, searchQuery.value)
  if (match) selectNode(match.knowledge_id)
}

function selectRelationTarget(relation: KnowledgeRelation) {
  selectNode(relation.source_id === selectedId.value ? relation.target_id : relation.source_id)
}

function otherNodeName(relation: KnowledgeRelation) {
  return relation.source_id === selectedId.value ? relation.target_name : relation.source_name
}

function clearSelection() {
  selectedId.value = null
  searchQuery.value = ''
  nextTick(renderGraph)
}

function fitGraph() {
  chart?.dispatchAction({ type: 'restore' })
  chart?.resize()
}

watch([graphModel, () => props.loading, () => props.error], () => nextTick(renderGraph), { deep: true })
watch(searchQuery, (query) => {
  if (!query.trim()) return
  const match = findKnowledgeItem(props.items, query)
  if (match) selectedId.value = match.knowledge_id
})

onMounted(() => {
  renderGraph()
  if (chartRef.value) {
    resizeObserver = new ResizeObserver(() => chart?.resize())
    resizeObserver.observe(chartRef.value)
  }
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  chart?.dispose()
})
</script>

<style scoped>
.knowledge-graph { display: grid; gap: 14px; }
.graph-toolbar { display: flex; flex-wrap: wrap; align-items: end; gap: 12px; padding: 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--soft); }
.graph-search { display: grid; gap: 5px; min-width: min(250px, 100%); color: var(--muted); font-size: 11px; font-weight: 700; }
.graph-search input { min-height: 34px; border: 1px solid var(--line); border-radius: 6px; background: #fff; color: var(--ink); padding: 6px 9px; font: inherit; font-size: 12px; }
.relation-filters { display: flex; flex-wrap: wrap; gap: 8px; padding-bottom: 8px; }
.relation-filter { display: inline-flex; align-items: center; gap: 5px; color: #405067; font-size: 12px; white-space: nowrap; }
.relation-filter input { margin: 0; accent-color: var(--blue); }
.relation-filter i, .category-legend i { width: 8px; height: 8px; border-radius: 50%; }
.graph-actions { display: flex; gap: 8px; margin-left: auto; }
.graph-layout { display: grid; grid-template-columns: minmax(0, 1fr) 270px; gap: 14px; align-items: stretch; }
.graph-stage { min-width: 0; }
.graph-canvas { min-height: 500px; border: 1px solid var(--line); border-radius: 8px; background: #fbfcfe; }
.graph-hint { margin: 8px 0 0; color: var(--muted); font-size: 11px; line-height: 1.5; }
.graph-state { display: grid; min-height: 260px; place-items: center; border: 1px dashed var(--line); border-radius: 8px; background: var(--soft); color: var(--muted); font-size: 13px; text-align: center; }
.graph-state.error { border-color: #edc9c9; background: #fffafa; color: var(--red); }
.node-detail { display: grid; align-content: start; gap: 10px; padding: 16px; border: 1px solid var(--line); border-radius: 8px; background: #fff; }
.detail-label { color: var(--muted); font-size: 11px; font-weight: 700; }
.node-detail h3 { font-size: 15px; line-height: 1.45; overflow-wrap: anywhere; }
.node-detail p { color: var(--muted); font-size: 12px; line-height: 1.65; }
.detail-meta, .detail-tags, .category-legend { display: flex; flex-wrap: wrap; gap: 6px; }
.detail-meta span, .detail-tags span { border: 1px solid var(--line); border-radius: 5px; background: var(--soft); padding: 4px 6px; color: #405067; font-size: 11px; }
.detail-relations { display: grid; gap: 7px; margin-top: 4px; padding-top: 12px; border-top: 1px solid var(--line); }
.detail-relations strong { font-size: 12px; }
.detail-relations ul { display: grid; gap: 5px; padding: 0; margin: 0; list-style: none; }
.detail-relations button { border: 0; background: transparent; color: var(--blue); padding: 0; font: inherit; text-align: left; cursor: pointer; }
.detail-relations button:hover { text-decoration: underline; }
.detail-relations button span { display: block; margin-bottom: 2px; font-size: 10px; font-weight: 700; }
.category-legend { padding-top: 6px; }
.category-legend span { display: inline-flex; align-items: center; gap: 5px; color: #405067; font-size: 11px; }
@media (max-width: 900px) { .graph-layout { grid-template-columns: 1fr; } .graph-canvas { min-height: 420px; } .graph-actions { margin-left: 0; } }
@media (max-width: 560px) { .graph-toolbar { align-items: stretch; } .graph-search { width: 100%; } .relation-filters { padding-bottom: 0; } .graph-actions { width: 100%; } .graph-actions .btn { flex: 1; } .graph-canvas { min-height: 360px; } }
</style>
