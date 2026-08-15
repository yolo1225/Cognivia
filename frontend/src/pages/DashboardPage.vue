<template>
  <section class="page">
    <div class="head">
      <div><h1>首页</h1></div>
    </div>

    <div v-if="activeTask" class="panel hero">
      <div class="hero-main">
        <div class="learner">
          <div class="avatar">{{ activeTask.learner_id?.charAt(0)?.toUpperCase() || '?' }}</div>
          <div class="learner-info">
            <strong>{{ activeTask.learner_id }} · 人工智能应用开发实训</strong>
            <small>任务 {{ activeTask.task_id }} · 状态：{{ activeTask.status }}</small>
          </div>
        </div>
        <div class="progress">
          <div class="step" v-for="(step, i) in pipelineSteps" :key="step" :class="{ done: i < activeStep, current: i === activeStep }">
            <div class="step-dot">{{ i < activeStep ? '✓' : i + 1 }}</div>{{ step }}
          </div>
        </div>
      </div>
      <div class="hero-side">
        <span>当前任务</span>
        <strong>{{ activeTask.task_id }}</strong>
        <p>决策：{{ activeTask.decision }} · 版本：v{{ activeTask.profile_version || '-' }}</p>
        <button class="btn" @click="router.push('/resources')">继续学习</button>
      </div>
    </div>

    <div v-else class="panel" style="text-align:center;padding:50px;color:var(--muted)">
      <div style="font-size:32px;margin-bottom:10px">⚙</div>
      <strong style="display:block;color:var(--ink)">尚未开始学习</strong>
      <p class="sub">先完成诊断测评，系统将根据答题情况生成画像，再为你生成个性化学习资源。</p>
      <button class="btn primary" style="margin-top:18px" @click="router.push('/diagnostic')">开始学习</button>
    </div>

  </section>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { getActiveGenerationTask, type GenerationTaskDetail } from '@/api/generation'

const router = useRouter()

const activeTask = ref<GenerationTaskDetail | null>(null)

const pipelineSteps = ['准备任务', '分析画像', '检索知识', '生成资源', '审核验证', '完成决策']

const activeStep = computed(() => {
  if (!activeTask.value) return 0
  return Math.max(0, Math.min(Math.floor((activeTask.value.progress || 0) / 100 * pipelineSteps.length), pipelineSteps.length - 1))
})

onMounted(async () => {
  try {
    const task = await getActiveGenerationTask('learner_001')
    if (task) {
      activeTask.value = task
    }
  } catch { /* empty state */ }
})
</script>
