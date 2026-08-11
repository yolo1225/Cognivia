<template>
  <aside class="side">
    <div class="brand">
      <div class="mark">域</div>
      <div>
        <strong>云川智汇</strong>
        <small>{{ domainStore.currentDomainName }}</small>
      </div>
    </div>
    <nav class="nav">
      <template v-for="group in visibleNavGroups" :key="group.label">
        <div class="nav-label">{{ group.label }}</div>
        <button
          v-for="item in group.items"
          :key="item.page"
          :class="{ active: route.path === item.route }"
          @click="router.push(item.route)"
        >
          <span class="nav-icon">{{ item.icon }}</span>
          {{ item.label }}
        </button>
      </template>
    </nav>
    <div class="foot">
      <span class="dot"></span>
      服务正常
      <span style="margin-left: auto">MVP v0.1</span>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import { useDomainStore } from '@/stores/domainStore'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const domainStore = useDomainStore()

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
      { page: 'dashboard', label: '首页', icon: '⌂', route: '/dashboard' },
      { page: 'diagnostic', label: '诊断训练', icon: '◎', route: '/diagnostic' },
      { page: 'resources', label: '学习资源', icon: '▤', route: '/resources' },
      { page: 'report', label: '学习报告', icon: '⌁', route: '/report' },
      { page: 'metrics', label: '任务记录', icon: '▥', route: '/metrics' },
    ],
  },
  {
    label: '管理与质量',
    items: [
      { page: 'learners', label: '用户管理', icon: '♙', route: '/learners' },
      { page: 'domainHub', label: '领域管理', icon: '▦', route: '/domain-hub' },
      { page: 'review', label: '人工复核', icon: '✓', route: '/review' },
    ],
  },
]

const visibleNavGroups = computed(() => {
  const role = authStore.role
  return allNavGroups
    .map((group) => ({
      ...group,
      items: group.label === '管理与质量' && role !== 'admin' ? [] : group.items,
    }))
    .filter((group) => group.items.length > 0)
})
</script>
