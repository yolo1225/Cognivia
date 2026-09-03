<template>
  <aside ref="sidebarRoot" class="side" :class="{ collapsed }">
    <div class="brand">
      <img class="mark" src="/favicon.svg" alt="" />
      <div class="brand-copy">
        <strong>云川智汇</strong>
        <small>学习决策工作台</small>
      </div>
      <button
        class="sidebar-toggle"
        type="button"
        :aria-label="collapsed ? '展开左侧导航' : '收起左侧导航'"
        :title="collapsed ? '展开左侧导航' : '收起左侧导航'"
        @click="emit('toggle-collapse')"
      >
        <AppIcon :name="collapsed ? 'panel-expand' : 'panel-collapse'" />
      </button>
    </div>
    <nav class="nav">
      <template v-for="group in visibleNavGroups" :key="group.label">
        <div class="nav-label">{{ group.label }}</div>
        <button
          v-for="item in group.items"
          :key="item.page"
          type="button"
          :class="{ active: route.path === item.route }"
          :aria-current="route.path === item.route ? 'page' : undefined"
          :title="item.label"
          @click="router.push(item.route)"
        >
          <span class="nav-icon"><AppIcon :name="item.icon" /></span>
          <span class="nav-text">{{ item.label }}</span>
        </button>
      </template>
    </nav>
    <div class="foot">
      <button
        class="theme-toggle"
        type="button"
        :aria-label="darkMode ? '切换至浅色模式' : '切换至深色模式'"
        :title="darkMode ? '切换至浅色模式' : '切换至深色模式'"
        @click="emit('toggle-theme')"
      >
        <AppIcon :name="darkMode ? 'sun' : 'moon'" />
        <span class="theme-toggle-text">{{ darkMode ? '浅色模式' : '深色模式' }}</span>
      </button>
      <span class="foot-status"><span class="dot"></span><span class="foot-text">服务正常</span></span>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import { useLearnerStore } from '@/stores/learnerStore'
import { useProfileGateStore } from '@/stores/profileGateStore'
import AppIcon from '@/components/Shared/AppIcon.vue'

defineProps<{ collapsed: boolean; darkMode: boolean }>()
const emit = defineEmits<{
  (event: 'toggle-collapse'): void
  (event: 'toggle-theme'): void
}>()

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const learnerStore = useLearnerStore()
const profileGate = useProfileGateStore()
const sidebarRoot = ref<HTMLElement | null>(null)

interface NavItem {
  page: string
  label: string
  icon: string
  route: string
}

interface NavGroup {
  label: string
  items: NavItem[]
}

const allNavGroups: NavGroup[] = [
  {
    label: '学习体验',
    items: [
      { page: 'dashboard', label: '首页', icon: 'home', route: '/dashboard' },
      { page: 'resources', label: '学习资源', icon: 'resources', route: '/resources' },
      { page: 'mistakeReview', label: '错题巩固', icon: 'check', route: '/mistake-review' },
      { page: 'report', label: '学情画像', icon: 'report', route: '/report' },
      { page: 'metrics', label: '学习历程', icon: 'history', route: '/metrics' },
    ],
  },
  {
    label: '管理与质量',
    items: [
      { page: 'learners', label: '用户管理', icon: 'users', route: '/learners' },
      { page: 'domainHub', label: '领域管理', icon: 'domain', route: '/domain-hub' },
      { page: 'modelSettings', label: '模型配置', icon: 'settings', route: '/model-settings' },
    ],
  },
]

const visibleNavGroups = computed(() => {
  const role = authStore.role
  return allNavGroups
    .map((group) => ({
      ...group,
      items: group.label === '管理与质量' && role !== 'admin'
        ? []
        : group.label === '学习体验' && role === 'learner' && !profileGate.ready
          ? group.items.filter((item) => item.page === 'dashboard')
          : group.items,
    }))
    .filter((group) => group.items.length > 0)
})

function refreshProfileGate() {
  if (authStore.role === 'learner') void profileGate.refresh(learnerStore.selectedLearnerId || '')
}

async function ensureActiveNavVisible() {
  await nextTick()
  if (!window.matchMedia('(max-width: 760px)').matches) return
  sidebarRoot.value?.querySelector<HTMLElement>('.nav button.active')?.scrollIntoView({ inline: 'center', block: 'nearest' })
}

onMounted(() => { refreshProfileGate(); void ensureActiveNavVisible() })
watch(() => learnerStore.selectedLearnerId, refreshProfileGate)
watch(() => route.path, ensureActiveNavVisible)
</script>
