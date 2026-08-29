<template>
  <div class="learning-path-graph" aria-label="学习路径图谱">
    <div ref="chartRef" class="path-chart" role="img" aria-label="按推荐顺序排列的学习路径节点图谱" />
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import type { LearningPathNode } from '@/api/learningPaths'
import { useChartTheme } from '@/composables/chartTheme'

const props = defineProps<{
  nodes: LearningPathNode[]
  selectedId?: string | null
}>()

const emit = defineEmits<{ select: [nodeId: string] }>()
const chartRef = ref<HTMLElement | null>(null)
const chartTheme = useChartTheme()
let chart: echarts.ECharts | null = null
let resizeObserver: ResizeObserver | null = null

const STATUS_LABELS: Record<LearningPathNode['status'], string> = {
  completed: '已完成',
  current: '当前学习',
  locked: '待解锁',
  skipped: '已跳过',
}

function wrapLabel(value: string) {
  const chars = Array.from(value)
  const lines: string[] = []
  for (let index = 0; index < chars.length; index += 8) lines.push(chars.slice(index, index + 8).join(''))
  return lines.slice(0, 2).join('\n')
}

function renderChart() {
  if (!chartRef.value) return
  chart ??= echarts.init(chartRef.value)
  const theme = chartTheme.value
  const statusColors: Record<LearningPathNode['status'], string> = {
    completed: theme.success,
    current: theme.primary,
    locked: theme.muted,
    skipped: theme.warning,
  }
  const nodes = props.nodes
  const data = nodes.map((node, index) => {
    const color = statusColors[node.status]
    const selected = node.path_node_id === props.selectedId
    return {
      id: node.path_node_id,
      name: node.title,
      x: index * 160,
      y: 74,
      value: node.path_order,
      symbolSize: node.status === 'current' ? 62 : 50,
      draggable: false,
      itemStyle: {
        color: node.status === 'locked' ? theme.locked : color,
        borderColor: color,
        borderWidth: selected ? 4 : node.status === 'current' ? 3 : 2,
        shadowBlur: selected ? 12 : 0,
        shadowColor: `${color}55`,
      },
      label: {
        show: true,
        position: 'bottom',
        distance: 8,
        align: 'center',
        formatter: `{order|${String(node.path_order).padStart(2, '0')}}\n{title|${wrapLabel(node.title)}}\n{state|${STATUS_LABELS[node.status]}}`,
        rich: {
          order: { color, fontSize: 10, fontWeight: 700, lineHeight: 14 },
          title: { color: theme.text, fontSize: 12, fontWeight: 700, lineHeight: 16 },
          state: { color: theme.muted, fontSize: 10, lineHeight: 14 },
        },
      },
    }
  })
  const links = nodes.slice(0, -1).map((node, index) => ({
    source: node.path_node_id,
    target: nodes[index + 1].path_node_id,
    lineStyle: {
      color: node.status === 'completed' ? theme.completedLink : theme.pendingLink,
      width: 2,
      curveness: 0,
    },
  }))
  chart.setOption({
    animationDuration: 320,
    animationDurationUpdate: 180,
    tooltip: {
      trigger: 'item',
      backgroundColor: theme.tooltip,
      borderWidth: 0,
      textStyle: { color: theme.tooltipText, fontSize: 12 },
      formatter: (params: { dataType?: string; data?: { id?: string } }) => {
        if (params.dataType !== 'node') return ''
        const node = nodes.find(item => item.path_node_id === params.data?.id)
        return node ? `${node.title}<br/>${STATUS_LABELS[node.status]} · 第 ${node.path_order} 节` : ''
      },
    },
    series: [{
      type: 'graph',
      layout: 'none',
      roam: nodes.length > 5,
      cursor: 'pointer',
      edgeSymbol: ['none', 'arrow'],
      edgeSymbolSize: 7,
      data,
      links,
      lineStyle: { opacity: 1 },
      emphasis: { focus: 'adjacency', scale: true },
      select: { disabled: true },
    }],
  }, true)
}

onMounted(() => {
  renderChart()
  chart?.on('click', (params) => {
    const nodeId = (params.data as { id?: unknown } | undefined)?.id
    if (params.dataType === 'node' && typeof nodeId === 'string') emit('select', nodeId)
  })
  if (chartRef.value) {
    resizeObserver = new ResizeObserver(() => chart?.resize())
    resizeObserver.observe(chartRef.value)
  }
})

watch(() => [props.nodes, props.selectedId, chartTheme.value], renderChart, { deep: true })

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  chart?.dispose()
  chart = null
})
</script>

<style scoped>
.learning-path-graph { position: relative; min-width: 0; overflow: hidden; border: 1px solid var(--chart-line); border-radius: 8px; background: var(--chart-canvas); }
.path-chart { height: 244px; min-width: 0; }
@media (max-width: 640px) { .path-chart { height: 280px; } }
</style>
