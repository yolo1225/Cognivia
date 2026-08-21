<template>
  <header class="rp-head page-header-unified">
    <div class="page-header-copy">
      <div class="page-title-line"><h1>{{ title }}</h1><slot name="status" /></div>
      <p v-if="description">{{ description }}</p>
      <slot name="meta" />
    </div>
    <div v-if="$slots.actions" class="rp-head-actions"><slot name="actions" /></div>
  </header>
</template>

<script setup lang="ts">
defineProps<{ title: string; description?: string }>()
</script>
