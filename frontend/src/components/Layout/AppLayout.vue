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
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import AppSidebar from './AppSidebar.vue'
import AppHeader from './AppHeader.vue'
import ToastOverlay from '@/components/Shared/ToastOverlay.vue'

const router = useRouter()
const transitionName = ref<'page-forward' | 'page-back'>('page-forward')

// 路由顺序，用于判断「前进 / 后退」方向，从而决定过渡方向
const routeOrder = [
  '/dashboard',
  '/diagnostic',
  '/resources',
  '/report',
  '/metrics',
  '/learners',
  '/domain-hub',
  '/knowledge',
  '/domain',
  '/review',
  '/agents',
]

router.beforeEach((to, from) => {
  const toIdx = routeOrder.indexOf(to.path)
  const fromIdx = routeOrder.indexOf(from.path)
  // 首次进入或未知路径时，默认按「前进」处理
  if (fromIdx === -1 || toIdx === -1) {
    transitionName.value = 'page-forward'
  } else {
    transitionName.value = toIdx >= fromIdx ? 'page-forward' : 'page-back'
  }
  return true
})
</script>
