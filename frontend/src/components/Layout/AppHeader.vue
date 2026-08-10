<template>
  <header class="top">
    <div>
      <strong>个性化实训工作区</strong>
      <span class="sep"></span>
      <span class="crumb">{{ pageLabel }}</span>
    </div>
    <div class="context">
      <button class="top-avatar" :title="authStore.userId">
        {{ authStore.userId.charAt(0) }}
      </button>
    </div>
  </header>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'

const route = useRoute()
const authStore = useAuthStore()

const labels: Record<string, string> = {
  '/my-learning': '我的学习',
  '/dashboard': '首页',
  '/diagnostic': '诊断与画像',
  '/resources': '学习资源',
  '/report': '学习报告',
  '/metrics': '任务记录',
  '/learners': '用户管理',
  '/domain-hub': '领域管理',
  '/domain': '领域配置',
  '/knowledge': '知识库管理',
  '/review': '人工复核',
  '/agents': 'Agent 协同工作台',
}

const pageLabel = computed(() => labels[route.path] || '工作区')
</script>
