<template>
  <Teleport to="body">
    <button v-if="modelValue" class="drawer-backdrop" aria-label="关闭侧边面板" @click="$emit('update:modelValue', false)" />
  <aside ref="drawerRef" class="drawer" :class="{ open: modelValue }" role="dialog" aria-modal="true" :aria-hidden="!modelValue" :aria-labelledby="titleId" @keydown="onKeydown">
    <div class="drawer-head">
      <button class="close" aria-label="关闭侧边面板" @click="$emit('update:modelValue', false)">&times;</button>
      <h2 :id="titleId">{{ title }}</h2>
      <p v-if="subtitle" class="sub">{{ subtitle }}</p>
    </div>
    <div class="drawer-body">
      <slot />
    </div>
    <div v-if="$slots.footer" class="drawer-foot">
      <slot name="footer" />
    </div>
  </aside>
  </Teleport>
</template>

<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const drawerRef = ref<HTMLElement | null>(null)
const titleId = `drawer-title-${Math.random().toString(36).slice(2, 9)}`
let triggerElement: HTMLElement | null = null

const props = defineProps<{ modelValue: boolean; title: string; subtitle?: string }>()
watch(() => props.modelValue, async (open) => {
  if (open) {
    triggerElement = document.activeElement as HTMLElement | null
    await nextTick()
    drawerRef.value?.querySelector<HTMLElement>('button, input, select, textarea, [href], [tabindex]:not([tabindex="-1"])')?.focus()
  } else if (triggerElement) {
    triggerElement.focus()
    triggerElement = null
  }
})

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') { emit('update:modelValue', false); return }
  if (event.key !== 'Tab' || !drawerRef.value) return
  const focusable = [...drawerRef.value.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [href], [tabindex]:not([tabindex="-1"])')]
  if (!focusable.length) return
  const first = focusable[0], last = focusable[focusable.length - 1]
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
}
</script>

<style scoped>
.drawer-backdrop {
  position: fixed;
  inset: 0;
  z-index: 19;
  border: 0;
  background: rgb(20 31 48 / .34);
  padding: 0;
}

@media (prefers-reduced-motion: reduce) {
  .drawer { transition-duration: .01ms; }
}
</style>
