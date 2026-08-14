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
        <template v-for="item in group.items" :key="item.page">
          <template v-if="item.children">
            <button
              class="nav-btn"
              :class="{ active: isGroupActive(item) }"
              @click="toggleGroup(item.page)"
            >
              <span class="nav-icon">{{ item.icon }}</span>
              <span>{{ item.label }}</span>
              <span class="nav-caret">{{ isExpanded(item.page) ? '▲' : '▼' }}</span>
            </button>
            <div v-show="isExpanded(item.page)" class="nav-children">
              <button
                v-for="child in item.children"
                :key="child.page"
                class="nav-btn"
                :class="{ active: route.path === child.route }"
                @click="router.push(child.route)"
              >
                <span class="nav-icon">{{ child.icon }}</span>
                <span>{{ child.label }}</span>
              </button>
            </div>
          </template>
          <button
            v-else
            class="nav-btn"
            :class="{ active: route.path === item.route }"
            @click="router.push(item.route)"
          >
            <span class="nav-icon">{{ item.icon }}</span>
            <span>{{ item.label }}</span>
          </button>
        </template>
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
import { computed, ref } from 'vue'
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
  children?: NavItem[]
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
      {
        page: 'learn',
        label: '学习',
        icon: '◉',
        route: '/diagnostic',
        children: [
          { page: 'diagnostic', label: '诊断与画像', icon: '◎', route: '/diagnostic' },
          { page: 'resources', label: '生成资源', icon: '▤', route: '/resources' },
        ],
      },
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
      items: group.items.filter(() => role === 'admin'), // simplified: admin sees all
    }))
    .filter((group) => group.items.length > 0)
})

// 可展开分组状态：默认展开「学习」
const expanded = ref<string | null>('learn')

function isExpanded(page: string) {
  return expanded.value === page
}

function toggleGroup(page: string) {
  expanded.value = isExpanded(page) ? null : page
}

function isGroupActive(item: NavItem) {
  return item.children?.some((child) => route.path === child.route) ?? false
}
</script>
