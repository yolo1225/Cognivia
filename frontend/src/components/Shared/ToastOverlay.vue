<template>
  <div class="toast" :class="[`toast-${toastType}`, { show: toastVisible }]">
    <span class="toast-icon">{{ toastIcon }}</span>
    <span>{{ toastMessage }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useToast } from '@/composables/useToast'

const { toastMessage, toastType, toastVisible } = useToast()
const icons = { info: 'ℹ', success: '✓', error: '✕' } as const
const toastIcon = computed(() => icons[toastType.value])
</script>

<style scoped>
.toast {
  display: flex;
  align-items: center;
  gap: 8px;
}
.toast-icon {
  flex: 0 0 auto;
  font-weight: 700;
}
.toast-success {
  background: var(--green);
}
.toast-error {
  background: var(--red);
}
.toast-info {
  background: #172231;
}
</style>
