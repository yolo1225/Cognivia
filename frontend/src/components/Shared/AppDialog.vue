<template>
  <dialog ref="dialogRef" class="export-dialog" @click.self="close">
    <div class="export-head">
      <h2>{{ title }}</h2>
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
import { ref } from 'vue'

defineProps<{
  title: string
  subtitle?: string
}>()

const dialogRef = ref<HTMLDialogElement | null>(null)

function open() {
  dialogRef.value?.showModal()
}
function close() {
  dialogRef.value?.close()
}

defineExpose({ open, close })
</script>
