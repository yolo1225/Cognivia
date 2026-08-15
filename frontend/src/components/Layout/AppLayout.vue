<template>
  <div class="app">
    <AppSidebar />
    <main class="main">
      <AppHeader />
      <div class="content">
        <router-view v-slot="{ Component, route }">
          <transition :name="transitionName" mode="out-in">
            <component :is="Component" :key="route.path" />
          </transition>
        </router-view>
      </div>
    </main>
    <ToastOverlay />
  </div>
</template>

<script setup lang="ts">
import { onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import AppSidebar from './AppSidebar.vue'
import AppHeader from './AppHeader.vue'
import ToastOverlay from '@/components/Shared/ToastOverlay.vue'

const router = useRouter()
const transitionName = ref<'page-forward' | 'page-back'>('page-forward')
const routeOrder = ['/dashboard', '/diagnostic', '/resources', '/report', '/metrics', '/learners', '/domain-hub']

const removeAfterEach = router.afterEach((to, from) => {
  const toIndex = routeOrder.indexOf(to.path)
  const fromIndex = routeOrder.indexOf(from.path)
  transitionName.value = fromIndex === -1 || toIndex === -1 || toIndex >= fromIndex ? 'page-forward' : 'page-back'
})

onUnmounted(removeAfterEach)
</script>
