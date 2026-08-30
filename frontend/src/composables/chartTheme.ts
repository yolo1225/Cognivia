import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

export type ChartTheme = {
  primary: string
  success: string
  warning: string
  danger: string
  neutral: string
  canvas: string
  surface: string
  surfaceMuted: string
  text: string
  muted: string
  line: string
  grid: string
  tooltip: string
  tooltipText: string
  pointBorder: string
  locked: string
  completedLink: string
  pendingLink: string
  categoryColors: string[]
}

export const lightChartTheme: ChartTheme = {
  primary: '#315fce', success: '#138560', warning: '#b96308', danger: '#c93636', neutral: '#7b8798',
  canvas: '#fbfcfe', surface: '#fafcff', surfaceMuted: '#f2f6fd', text: '#172231', muted: '#5e6f84',
  line: '#dfe6ef', grid: '#e4eaf2', tooltip: '#1b2737', tooltipText: '#f8fafc', pointBorder: '#ffffff',
  locked: '#f8fafc', completedLink: '#9ad8c3', pendingLink: '#cbd5e1',
  categoryColors: ['#315fce', '#138560', '#b96308', '#7c4d9e', '#007a8a', '#c44569'],
}

export const darkChartTheme: ChartTheme = {
  primary: '#7ca7ff', success: '#50c996', warning: '#f2b45e', danger: '#ff8585', neutral: '#9fb0c7',
  canvas: '#162233', surface: '#1b2a3d', surfaceMuted: '#21344a', text: '#edf3fb', muted: '#b7c5d6',
  line: '#40556d', grid: '#33475f', tooltip: '#0d1724', tooltipText: '#edf3fb', pointBorder: '#182231',
  locked: '#2a384a', completedLink: '#34765f', pendingLink: '#40556d',
  categoryColors: ['#7ca7ff', '#50c996', '#f2b45e', '#c6a4ef', '#66c7d4', '#f08ba7'],
}

function readVariable(name: string, fallback: string) {
  if (typeof window === 'undefined') return fallback
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
}

export function readChartTheme(): ChartTheme {
  return {
    primary: readVariable('--chart-primary', lightChartTheme.primary),
    success: readVariable('--chart-success', lightChartTheme.success),
    warning: readVariable('--chart-warning', lightChartTheme.warning),
    danger: readVariable('--chart-danger', lightChartTheme.danger),
    neutral: readVariable('--chart-neutral', lightChartTheme.neutral),
    canvas: readVariable('--chart-canvas', lightChartTheme.canvas),
    surface: readVariable('--chart-surface', lightChartTheme.surface),
    surfaceMuted: readVariable('--chart-surface-muted', lightChartTheme.surfaceMuted),
    text: readVariable('--chart-text', lightChartTheme.text),
    muted: readVariable('--chart-muted', lightChartTheme.muted),
    line: readVariable('--chart-line', lightChartTheme.line),
    grid: readVariable('--chart-grid', lightChartTheme.grid),
    tooltip: readVariable('--chart-tooltip', lightChartTheme.tooltip),
    tooltipText: readVariable('--chart-tooltip-text', lightChartTheme.tooltipText),
    pointBorder: readVariable('--chart-point-border', lightChartTheme.pointBorder),
    locked: readVariable('--chart-locked', lightChartTheme.locked),
    completedLink: readVariable('--chart-completed-link', lightChartTheme.completedLink),
    pendingLink: readVariable('--chart-pending-link', lightChartTheme.pendingLink),
    categoryColors: Array.from({ length: 6 }, (_, index) => readVariable(
      `--chart-category-${index + 1}`,
      lightChartTheme.categoryColors[index],
    )),
  }
}

export function useChartTheme() {
  const revision = ref(0)
  let observer: MutationObserver | null = null
  const refresh = () => { revision.value += 1 }
  const theme = computed(() => {
    revision.value
    return readChartTheme()
  })

  onMounted(() => {
    refresh()
    observer = new MutationObserver(refresh)
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
  })

  onBeforeUnmount(() => observer?.disconnect())
  return theme
}
