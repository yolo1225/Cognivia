<template>
  <aside class="drawer" :class="{ open: modelValue }">
    <div class="drawer-head">
      <button class="close" @click="$emit('update:modelValue', false)">&times;</button>
      <h2>{{ title }}</h2>
      <p v-if="subtitle" class="sub">{{ subtitle }}</p>
    </div>
    <div class="drawer-body">
      <slot />
    </div>
    <div v-if="$slots.footer" class="drawer-foot">
      <slot name="footer" />
    </div>
  </aside>
</template>

<script setup lang="ts">
defineProps<{
  modelValue: boolean
  title: string
  subtitle?: string
}>()

defineEmits<{
  'update:modelValue': [value: boolean]
}>()
</script>
