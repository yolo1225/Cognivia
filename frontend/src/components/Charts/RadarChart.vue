<template>
  <div ref="chartRef" class="chart" />
</template>

<script setup lang="ts">
import * as echarts from 'echarts'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps<{
  values: number[]
  baselineValues?: number[]
  indicators?: string[]
}>()

const chartRef = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null

function renderChart() {
  if (!chartRef.value) return
  chart ??= echarts.init(chartRef.value)
  chart.setOption({
    color: ['#315fce', '#7b8798'],
    tooltip: {
      trigger: 'item',
      backgroundColor: '#1b2737',
      borderWidth: 0,
      textStyle: { color: '#f8fafc', fontSize: 12 },
    },
    radar: {
      radius: '66%',
      splitNumber: 4,
      indicator: (props.indicators || ['理论基础', '实操能力', '问题解决', '知识广度', '学习速度'])
        .map(name => ({ name, max: 100 })),
      axisName: { color: '#5e6f84', fontSize: 12, fontWeight: 600 },
      splitLine: { lineStyle: { color: '#e4eaf2' } },
      splitArea: { areaStyle: { color: ['#fafcff', '#f2f6fd'] } },
      axisLine: { lineStyle: { color: '#dfe6ef' } },
    },
    series: [
      {
        type: 'radar',
        data: [
          { value: props.values, name: '当前画像', areaStyle: { color: 'rgba(49, 95, 206, 0.16)' }, lineStyle: { width: 2, color: '#315fce' }, itemStyle: { color: '#315fce', borderColor: '#fff', borderWidth: 1.5 } },
          ...(props.baselineValues?.length ? [{ value: props.baselineValues, name: '首次诊断', areaStyle: { color: 'rgba(123, 135, 152, 0.03)' }, lineStyle: { width: 2, type: 'dashed' as const, color: '#7b8798' }, itemStyle: { color: '#7b8798' } }] : []),
        ],
        areaStyle: {
          color: {
            type: 'linear',
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(49, 95, 206, 0.30)' },
              { offset: 1, color: 'rgba(49, 95, 206, 0.06)' },
            ],
          },
        },
        lineStyle: { width: 2, color: '#315fce' },
        itemStyle: { color: '#315fce', borderColor: '#fff', borderWidth: 1.5 },
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
watch(() => [props.values, props.baselineValues, props.indicators], renderChart, { deep: true })
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
