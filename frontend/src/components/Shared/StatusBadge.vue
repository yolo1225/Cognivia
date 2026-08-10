<template>
  <span class="status" :class="typeClass">{{ label }}</span>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  label: string
  type?: 'ok' | 'wait' | 'error' | 'default'
}>()

const typeClass = computed(() => {
  switch (props.type) {
    case 'ok':
      return 'ok'
    case 'wait':
      return 'wait'
    default:
      return ''
  }
})
</script>
