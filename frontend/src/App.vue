<template>
  <router-view v-if="$route.meta.guest" />
  <AppLayout v-else />
</template>

<script setup lang="ts">
import AppLayout from '@/components/Layout/AppLayout.vue'
</script>
