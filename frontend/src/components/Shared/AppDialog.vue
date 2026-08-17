<template>
  <dialog ref="dialogRef" class="export-dialog" :aria-labelledby="titleId" @click.self="close" @close="restoreFocus">
    <div class="export-head">
      <h2 :id="titleId">{{ title }}</h2>
      <p v-if="subtitle" class="sub">{{ subtitle }}</p>
    </div>
    <div class="export-body">
      <slot />
    </div>
    <div v-if="$slots.footer" class="export-foot">
      <slot name="footer" />
    </div>
  </dialog>
</template>

<script setup lang="ts">
import { nextTick, ref } from 'vue'

defineProps<{
  title: string
  subtitle?: string
}>()

const dialogRef = ref<HTMLDialogElement | null>(null)
const titleId = `dialog-title-${Math.random().toString(36).slice(2, 9)}`
let triggerElement: HTMLElement | null = null

async function open() {
  triggerElement = document.activeElement as HTMLElement | null
  dialogRef.value?.showModal()
  await nextTick()
  dialogRef.value?.querySelector<HTMLElement>('[autofocus], button, input, select, textarea, [href], [tabindex]:not([tabindex="-1"])')?.focus()
}
function close() {
  dialogRef.value?.close()
}
function restoreFocus() { triggerElement?.focus(); triggerElement = null }

defineExpose({ open, close })
</script>
