<template>
  <header class="top">
    <div>
      <strong class="workspace-name">个性化实训工作区</strong>
      <span class="sep"></span>
      <span class="crumb">{{ pageLabel }}</span>
    </div>
    <div ref="accountMenu" class="context account-menu">
      <button class="top-avatar" type="button" :title="`${authStore.userId}，打开账户菜单`" :aria-expanded="menuOpen" aria-haspopup="menu" @click="menuOpen = !menuOpen">
        {{ authStore.userId.charAt(0) }}
      </button>
      <div v-if="menuOpen" class="account-dropdown" role="menu" @keydown.esc="menuOpen = false">
        <div class="account-summary">
          <strong>{{ authStore.userId }}</strong>
          <span>{{ authStore.role === 'admin' ? '管理员' : '学习者' }}</span>
        </div>
        <button type="button" role="menuitem" class="logout" @click="logout">退出登录</button>
      </div>
    </div>
  </header>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'

const route = useRoute()
const authStore = useAuthStore()
const router = useRouter()
const menuOpen = ref(false)
const accountMenu = ref<HTMLElement | null>(null)

function closeOnOutsideClick(event: MouseEvent) {
  if (accountMenu.value && !accountMenu.value.contains(event.target as Node)) menuOpen.value = false
}

onMounted(() => document.addEventListener('click', closeOnOutsideClick))
onBeforeUnmount(() => document.removeEventListener('click', closeOnOutsideClick))

async function logout(){ menuOpen.value = false; await authStore.logout(); await router.push('/login') }

const labels: Record<string, string> = {
  '/dashboard': '首页',
  '/resources': '学习资源',
  '/report': '学习报告',
  '/metrics': '任务记录',
  '/learners': '用户管理',
  '/domain-hub': '领域管理',
  '/review': '人工复核',
}

const pageLabel = computed(() => labels[route.path] || '工作区')
</script>

<style scoped>
.account-menu { position: relative; }
.account-dropdown { position: absolute; top: calc(100% + 10px); right: 0; z-index: 10; width: 190px; overflow: hidden; border: 1px solid var(--line); border-radius: 10px; background: #fff; box-shadow: 0 5px 8px rgb(22 35 55 / .12); }
.account-summary { display: grid; gap: 3px; padding: 13px 14px; border-bottom: 1px solid var(--line); }
.account-summary strong { overflow: hidden; color: var(--ink); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.account-summary span { color: var(--muted); font-size: 11px; }
.logout { width: 100%; border: 0; background: #fff; color: #405067; padding: 11px 14px; text-align: left; font-size: 13px; }
.logout:hover { background: #f4f7fb; color: var(--red); }
</style>
