<template>
  <div class="app">
    <AppSidebar />
    <main class="main">
      <AppHeader />
      <div class="content">
        <router-view />
      </div>
    </main>
    <ToastOverlay />
  </div>
</template>

<script setup lang="ts">
import AppSidebar from './AppSidebar.vue'
import AppHeader from './AppHeader.vue'
import ToastOverlay from '@/components/Shared/ToastOverlay.vue'
</script>
