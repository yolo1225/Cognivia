<template>
  <div
    ref="chartRef"
    class="resource-difficulty-match-chart"
    role="img"
    aria-label="资源难度与审核难度适配度对照图"
  />
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import type { ResourceDifficultyMatchDatum } from './resourceDifficultyMatch'
import { useChartTheme } from '@/composables/chartTheme'

const props = defineProps<{ data: ResourceDifficultyMatchDatum[] }>()

const chartRef = ref<HTMLElement | null>(null)
const chartTheme = useChartTheme()
let chart: echarts.ECharts | null = null
let resizeObserver: ResizeObserver | null = null

function renderChart() {
  if (!chartRef.value || !props.data.length) return
  chart ??= echarts.init(chartRef.value)
  const theme = chartTheme.value
  chart.setOption({
    animationDuration: 260,
    color: [theme.primary, theme.success],
    grid: { top: 32, right: 46, bottom: 52, left: 36, containLabel: false },
    tooltip: {
      trigger: 'axis',
      backgroundColor: theme.tooltip,
      borderWidth: 0,
      textStyle: { color: theme.tooltipText, fontSize: 12 },
      formatter: (params: Array<{ dataIndex: number }>) => {
        const item = props.data[params[0]?.dataIndex ?? 0]
        return item
          ? `${item.title}<br/>资源难度：${item.difficulty} / 5<br/>审核难度适配：${item.difficultyMatchScore}%`
          : ''
      },
    },
    xAxis: {
      type: 'category',
      data: props.data.map(item => item.label),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: theme.line } },
      axisLabel: { color: theme.muted, fontSize: 10, interval: 0, width: 86, overflow: 'truncate', lineHeight: 14 },
    },
    yAxis: [
      {
        type: 'value', min: 0, max: 5, interval: 1, name: '难度', nameTextStyle: { color: theme.muted, fontSize: 10 },
        axisLabel: { color: theme.muted, fontSize: 10 }, axisLine: { show: false }, axisTick: { show: false },
        splitLine: { lineStyle: { color: theme.grid } },
      },
      {
        type: 'value', min: 0, max: 100, interval: 25, name: '适配度', nameTextStyle: { color: theme.muted, fontSize: 10 },
        axisLabel: { color: theme.muted, fontSize: 10, formatter: '{value}%' }, axisLine: { show: false }, axisTick: { show: false },
        splitLine: { show: false },
      },
    ],
    series: [
      { name: '资源难度', type: 'bar', yAxisIndex: 0, data: props.data.map(item => item.difficulty), barMaxWidth: 28, itemStyle: { borderRadius: [4, 4, 0, 0] } },
      {
        name: '难度适配', type: 'line', yAxisIndex: 1, data: props.data.map(item => item.difficultyMatchScore),
        symbol: 'circle', symbolSize: 7, lineStyle: { width: 2 }, itemStyle: { borderColor: theme.pointBorder, borderWidth: 1.5 },
        markLine: { silent: true, symbol: 'none', lineStyle: { color: theme.warning, type: 'dashed', width: 1 }, label: { color: theme.warning, fontSize: 10, formatter: '目标 85%' }, data: [{ yAxis: 85 }] },
      },
    ],
  }, true)
}

onMounted(() => {
  renderChart()
  if (chartRef.value) {
    resizeObserver = new ResizeObserver(() => chart?.resize())
    resizeObserver.observe(chartRef.value)
  }
})

watch(() => [props.data, chartTheme.value], renderChart, { deep: true })

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  chart?.dispose()
  chart = null
})
</script>

<style scoped>
.resource-difficulty-match-chart { width: 100%; height: 260px; }
</style>
