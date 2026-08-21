<template><div class="metric-strip"><div v-for="item in items" :key="item.label" class="metric-strip-item"><span>{{ item.label }}</span><strong>{{ item.value }}</strong><small v-if="item.description">{{ item.description }}</small></div></div></template>
<script setup lang="ts">defineProps<{ items: Array<{ label: string; value: string | number; description?: string }> }>()</script>
