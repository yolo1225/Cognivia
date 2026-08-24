<template>
  <div class="app" :class="{ 'sidebar-collapsed': sidebarCollapsed, 'theme-dark': darkMode }">
    <AppSidebar
      :collapsed="sidebarCollapsed"
      :dark-mode="darkMode"
      @toggle-collapse="toggleSidebar"
      @toggle-theme="toggleTheme"
    />
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
const routeOrder = ['/dashboard', '/resources', '/report', '/metrics', '/learners', '/domain-hub', '/model-settings']
const sidebarCollapsed = ref(readSidebarCollapsed())
const darkMode = ref(readDarkMode())

function readSidebarCollapsed() {
  try {
    return window.localStorage.getItem('cognivia.sidebar-collapsed') === 'true'
  } catch {
    return false
  }
}

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
  try {
    window.localStorage.setItem('cognivia.sidebar-collapsed', String(sidebarCollapsed.value))
  } catch {
    // Keep the current-session behavior when browser storage is unavailable.
  }
}

function readDarkMode() {
  try {
    return window.localStorage.getItem('cognivia.dark-mode') === 'true'
  } catch {
    return false
  }
}

function toggleTheme() {
  darkMode.value = !darkMode.value
  document.documentElement.classList.toggle('theme-dark', darkMode.value)
  try {
    window.localStorage.setItem('cognivia.dark-mode', String(darkMode.value))
  } catch {
    // Keep the current-session behavior when browser storage is unavailable.
  }
}

const removeAfterEach = router.afterEach((to, from) => {
  const toIndex = routeOrder.indexOf(to.path)
  const fromIndex = routeOrder.indexOf(from.path)
  transitionName.value = fromIndex === -1 || toIndex === -1 || toIndex >= fromIndex ? 'page-forward' : 'page-back'
})

onUnmounted(removeAfterEach)
</script>
