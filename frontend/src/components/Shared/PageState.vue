<template>
  <section class="page-state" :class="`is-${type}`" :role="type === 'error' ? 'alert' : undefined" :aria-busy="type === 'loading'">
    <template v-if="type === 'loading'">
      <span class="sr-only" role="status" aria-live="polite">{{ title }}</span>
      <div class="page-state-skeleton" aria-hidden="true"><i /><i /><i /></div>
    </template>
    <template v-else>
      <span class="page-state-icon"><AppIcon :name="type === 'error' ? 'warning' : icon" /></span>
      <h2>{{ title }}</h2>
      <p v-if="description">{{ description }}</p>
      <div v-if="$slots.default" class="page-state-actions"><slot /></div>
    </template>
  </section>
</template>

<script setup lang="ts">
import AppIcon from './AppIcon.vue'
withDefaults(defineProps<{ type: 'loading' | 'empty' | 'error'; title?: string; description?: string; icon?: string }>(), { title: '正在加载', description: '', icon: 'empty' })
</script>
