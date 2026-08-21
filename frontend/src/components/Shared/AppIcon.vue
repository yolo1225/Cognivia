<template>
  <svg class="app-icon" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path v-for="(path, index) in paths" :key="index" :d="path" />
  </svg>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ name: string }>()

const icons: Record<string, string[]> = {
  home: ['M3 10.8 12 3l9 7.8', 'M5.5 9.5V21h13V9.5', 'M9.5 21v-6h5v6'],
  resources: ['M5 4.5h12a2 2 0 0 1 2 2V20H7a2 2 0 0 0-2 2V4.5Z', 'M7 20a2 2 0 0 0-2 2', 'M8.5 8h7', 'M8.5 12h7'],
  report: ['M4 19.5V10', 'M10 19.5V4.5', 'M16 19.5v-7', 'M22 19.5H2'],
  history: ['M3.5 12a8.5 8.5 0 1 0 2.5-6', 'M3.5 4.5V9H8', 'M12 7.5V12l3 2'],
  users: ['M16 20v-1.5a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4V20', 'M9 10.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z', 'M17 11a3 3 0 0 0 0-6', 'M22 20v-1.5a4 4 0 0 0-3-3.87'],
  domain: ['M4 4h6v6H4z', 'M14 4h6v6h-6z', 'M4 14h6v6H4z', 'M14 14h6v6h-6z'],
  settings: ['M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z', 'M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.12 2.12-.06-.06a1.7 1.7 0 0 0-1.88-.34 1.7 1.7 0 0 0-1.03 1.56V20.3h-3v-.08a1.7 1.7 0 0 0-1.03-1.56A1.7 1.7 0 0 0 8.8 19l-.06.06-2.12-2.12.06-.06A1.7 1.7 0 0 0 7.02 15a1.7 1.7 0 0 0-1.56-1.03H5.4v-3h.06A1.7 1.7 0 0 0 7.02 9.9a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.12-2.12.06.06a1.7 1.7 0 0 0 1.88.34 1.7 1.7 0 0 0 1.03-1.56V4.6h3v.08a1.7 1.7 0 0 0 1.03 1.56 1.7 1.7 0 0 0 1.88-.34l.06-.06 2.12 2.12-.06.06a1.7 1.7 0 0 0-.34 1.88 1.7 1.7 0 0 0 1.56 1.03h.08v3h-.08A1.7 1.7 0 0 0 19.4 15Z'],
  bell: ['M18 9.5a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9', 'M10 21h4'],
  empty: ['M4 7.5h16v11H4z', 'M8 7.5V5h8v2.5', 'M8 12h8', 'M10 15.5h4'],
  warning: ['M12 3 2.8 20h18.4L12 3Z', 'M12 9v5', 'M12 17.5h.01'],
  check: ['m5 12.5 4.2 4.2L19 7'],
}

const paths = computed(() => icons[props.name] || icons.empty)
</script>

<style scoped>
.app-icon { width: 1em; height: 1em; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
</style>
