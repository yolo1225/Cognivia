<template>
  <div ref="chartRef" class="chart" />
</template>

<script setup lang="ts">
import * as echarts from 'echarts'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useChartTheme } from '@/composables/chartTheme'

const props = defineProps<{
  values: number[]
  baselineValues?: number[]
  indicators?: string[]
}>()

const chartRef = ref<HTMLDivElement | null>(null)
const chartTheme = useChartTheme()
let chart: echarts.ECharts | null = null

function renderChart() {
  if (!chartRef.value) return
  chart ??= echarts.init(chartRef.value)
  const theme = chartTheme.value
  chart.setOption({
    color: [theme.primary, theme.neutral],
    tooltip: {
      trigger: 'item',
      backgroundColor: theme.tooltip,
      borderWidth: 0,
      textStyle: { color: theme.tooltipText, fontSize: 12 },
    },
    radar: {
      radius: '66%',
      splitNumber: 4,
      indicator: (props.indicators || ['理论基础', '实操能力', '问题解决', '知识广度', '学习速度'])
        .map(name => ({ name, max: 100 })),
      axisName: { color: theme.muted, fontSize: 12, fontWeight: 600 },
      splitLine: { lineStyle: { color: theme.grid } },
      splitArea: { areaStyle: { color: [theme.surface, theme.surfaceMuted] } },
      axisLine: { lineStyle: { color: theme.line } },
    },
    series: [
      {
        type: 'radar',
        data: [
          { value: props.values, name: '当前画像', areaStyle: { color: `${theme.primary}29` }, lineStyle: { width: 2, color: theme.primary }, itemStyle: { color: theme.primary, borderColor: theme.pointBorder, borderWidth: 1.5 } },
          ...(props.baselineValues?.length ? [{ value: props.baselineValues, name: '首次诊断', areaStyle: { color: `${theme.neutral}12` }, lineStyle: { width: 2, type: 'dashed' as const, color: theme.neutral }, itemStyle: { color: theme.neutral } }] : []),
        ],
        areaStyle: {
          color: `${theme.primary}26`,
        },
        lineStyle: { width: 2, color: theme.primary },
        itemStyle: { color: theme.primary, borderColor: theme.pointBorder, borderWidth: 1.5 },
        symbol: 'circle',
        symbolSize: 5,
      },
    ],
  })
}

function resizeChart() {
  chart?.resize()
}

onMounted(() => {
  renderChart()
  window.addEventListener('resize', resizeChart)
})
watch(() => [props.values, props.baselineValues, props.indicators, chartTheme.value], renderChart, { deep: true })
onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeChart)
  chart?.dispose()
})
</script>

<style scoped>
.chart {
  width: 100%;
  min-height: 320px;
}
</style>
