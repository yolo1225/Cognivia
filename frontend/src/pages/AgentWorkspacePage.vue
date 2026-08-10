<template>
  <section class="page">
    <div class="head"><div><h1>Agent 协同工作台</h1><p class="sub">实时查看多智能体协作流程，展示每个节点的职责和运行状态。</p></div>
      <div class="actions">
        <button class="btn" @click="loadTask">刷新任务</button>
        <button class="btn primary" v-if="taskResult" @click="router.push('/resources')">查看本次资源</button>
      </div>
    </div>

    <div v-if="!taskResult && !loading" class="panel" style="text-align:center;padding:50px">
      <div class="upload-icon" style="margin:auto">⚙</div>
      <strong style="display:block;margin-top:14px">暂无活跃任务</strong>
      <p class="sub">前往首页点击"生成个性化资源"启动新的生成任务。</p>
      <button class="btn primary" style="margin-top:14px" @click="router.push('/dashboard')">前往首页</button>
    </div>

    <div v-if="loading && !taskResult" class="panel" style="text-align:center;padding:50px;color:var(--muted)">加载任务中...</div>

    <template v-if="taskResult">
      <div class="panel">
        <div class="panel-head"><h2>统一八节点工作流</h2><span class="status" :class="taskResult.status === 'completed' ? 'ok' : 'wait'">{{ taskResult.status }}</span></div>
        <div class="pipeline">
          <div v-for="(node,i) in pipelineNodes" :key="node" class="pipe-step" :class="{ done: i < activeStep, live: i === activeStep }">
            <div class="pipe-dot">{{ i < activeStep ? '✓' : i+1 }}</div>{{ node }}
          </div>
        </div>
      </div>

      <div class="panel">
        <div class="panel-head"><h2>任务详情</h2><span class="tag">{{ taskResult.task_id }}</span></div>
        <div class="task-detail-grid">
          <div><span>任务ID</span><strong>{{ taskResult.task_id }}</strong></div>
          <div><span>状态</span><strong>{{ taskResult.status }}</strong></div>
          <div><span>版本</span><strong>v{{ taskResult.profile_version || '-' }}</strong></div>
          <div><span>决策</span><strong>{{ taskResult.decision }}</strong></div>
        </div>

        <h3 v-if="taskResult.resources?.length" style="margin:18px 0 10px">生成资源</h3>
        <div class="task-artifacts">
          <div v-for="r in taskResult.resources" :key="r.resource_id" class="artifact">
            <div><strong>{{ r.title }}</strong><br><span>{{ r.resource_type }} · 难度 {{ r.difficulty }} · 审核：{{ r.review_status }}</span></div>
            <span class="status" :class="r.review_status === 'passed' ? 'ok' : 'wait'">{{ r.review_status }}</span>
          </div>
        </div>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useToast } from '@/composables/useToast'
import { getActiveGenerationTask, getGenerationTask, type GenerationTaskDetail } from '@/api/generation'

const route = useRoute()
const router = useRouter()
const { showToast } = useToast()

const taskResult = ref<GenerationTaskDetail | null>(null)
const loading = ref(false)
const pipelineNodes = ['准备任务', '分析画像', '检索知识', '生成资源', '审核验证', '完成决策']

const activeStep = computed(() => {
  if (!taskResult.value) return 0
  const progress = taskResult.value.progress || 0
  return Math.max(0, Math.min(Math.floor(progress / 100 * pipelineNodes.length), pipelineNodes.length - 1))
})

async function loadTask() {
  loading.value = true
  try {
    const taskId = route.query.task_id as string
    if (taskId) {
      taskResult.value = await getGenerationTask(taskId)
    } else {
      try { taskResult.value = await getActiveGenerationTask('learner_001') }
      catch { taskResult.value = null }
    }
  } catch { /* no active task */ }
  finally { loading.value = false }
}

onMounted(loadTask)
</script>
