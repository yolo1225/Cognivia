<template>
  <span class="status" :class="typeClass">{{ label }}</span>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  label: string
  type?: 'ok' | 'wait' | 'error' | 'default' | 'success' | 'info' | 'warning' | 'danger' | 'neutral'
}>()

const typeClass = computed(() => {
  switch (props.type) {
    case 'ok':
    case 'success':
      return 'ok'
    case 'wait':
    case 'warning':
      return 'wait'
    case 'error':
    case 'danger':
      return 'error'
    case 'info':
      return 'info'
    default:
      return 'neutral'
  }
})
</script>
