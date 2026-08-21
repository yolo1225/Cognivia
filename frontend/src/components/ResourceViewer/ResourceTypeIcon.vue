<template>
  <svg
    class="rt-icon"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.8"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <template v-if="type === 'lecture'">
      <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15H6.5A2.5 2.5 0 0 0 4 20.5v-15Z" />
      <path d="M4 18.5A2.5 2.5 0 0 1 6.5 16H20" />
      <path d="M8 7h8" />
      <path d="M8 10.5h5" />
    </template>
    <template v-else-if="type === 'practice_guide'">
      <rect x="3" y="4" width="18" height="16" rx="2.5" />
      <path d="m7.5 9 3 3-3 3" />
      <path d="M13 15h4" />
    </template>
    <template v-else-if="type === 'graded_quiz'">
      <rect x="5" y="4" width="14" height="16" rx="2.5" />
      <path d="M9 4a3 3 0 0 1 6 0" />
      <path d="m9 12.5 2 2 4-4" />
    </template>
    <template v-else>
      <path d="M4 5h16v14H4z" />
      <path d="M8 9h8" />
    </template>
  </svg>
</template>

<script setup lang="ts">
defineProps<{
  type: string
}>()
</script>

<style scoped>
.rt-icon {
  width: 1em;
  height: 1em;
  display: block;
}
</style>
