<template>
  <div v-if="toastVisible" class="toast" :class="`toast-${toastType}`" role="status" aria-live="polite" aria-atomic="true">
    <span class="toast-icon" aria-hidden="true">{{ toastIcon }}</span>
    <div class="toast-copy">
      <strong>{{ toastTitle }}</strong>
      <p>{{ toastMessage }}</p>
    </div>
    <button class="toast-close" type="button" aria-label="关闭通知" @click="closeToast">×</button>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useToast } from '@/composables/useToast'

const { toastMessage, toastType, toastVisible, closeToast } = useToast()
const icons = { info: 'ℹ', success: '✓', error: '✕' } as const
const titles = { info: '提示', success: '操作完成', error: '需要处理' } as const
const toastIcon = computed(() => icons[toastType.value])
const toastTitle = computed(() => titles[toastType.value])
</script>

<style scoped>
.toast {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}
.toast-icon {
  width: 24px;
  height: 24px;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  border-radius: 7px;
  font-weight: 700;
}
.toast-copy { min-width: 0; display: grid; gap: 2px; padding-top: 1px; }
.toast-copy strong { color: var(--ink); font-size: 12px; line-height: 1.4; }
.toast-copy p { margin: 0; color: var(--body); font-size: 12px; line-height: 1.55; overflow-wrap: anywhere; }
.toast-close { width: 24px; height: 24px; flex: 0 0 auto; border: 0; border-radius: 6px; background: transparent; color: var(--muted); font-size: 18px; line-height: 1; }
.toast-close:hover { background: var(--soft); color: var(--ink); }
.toast-success { --toast-accent: var(--green); }
.toast-success .toast-icon { background: var(--green2); color: var(--green); }
.toast-error { --toast-accent: var(--red); }
.toast-error .toast-icon { background: var(--red2); color: var(--red); }
.toast-info { --toast-accent: var(--info); }
.toast-info .toast-icon { background: var(--info2); color: var(--info); }
</style>
