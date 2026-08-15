<template>
  <section class="page">
    <div class="head">
      <div><h1>首页</h1></div>
      <div class="actions">
        <button class="btn" @click="router.push('/diagnostic')">诊断训练</button>
        <button class="btn primary" :disabled="creating" @click="handleCreateTask">
          {{ creating ? '正在创建...' : '生成个性化资源' }}
        </button>
      </div>
    </div>

    <div class="metrics">
      <div class="metric"><div><span>领域知识点</span></div><strong>{{ knowledgeTotal }}</strong><small>来源完整，可用于检索</small></div>
      <div class="metric"><div><span>诊断题</span></div><strong>{{ questionCount }}</strong><small>当前题库数量</small></div>
      <div class="metric"><div><span>我的已发布资源</span></div><strong>{{ resourceCount }}</strong><small>当前账号可学习资源</small></div>
      <div class="metric"><div><span>评测案例</span></div><strong>{{ evalCaseCount }}</strong><small>最近运行：{{ evalDate }}</small></div>
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
        <p class="sub">资源正在生成并执行自动质量审核，完成后将在资源页展示三项质量数据。</p>
      </div>
      <div class="hero-side">
        <span>当前任务</span>
        <strong>{{ activeTask.task_id }}</strong>
        <p>决策：{{ activeTask.decision }} · 版本：v{{ activeTask.profile_version || '-' }}</p>
        <button class="btn" @click="openTask(activeTask.task_id)">查看进度</button>
      </div>
    </div>

    <div v-else class="panel" style="text-align:center;padding:50px;color:var(--muted)">
      <div style="font-size:32px;margin-bottom:10px">⚙</div>
      <strong style="display:block;color:var(--ink)">尚未创建生成任务</strong>
      <p class="sub">点击"生成个性化资源"开始。系统将分析学习者画像 → 检索知识 → 生成资源 → 审核验证。</p>
    </div>

    <div class="panel">
      <div class="panel-head"><h2>最近任务</h2></div>
      <table>
        <thead><tr><th>任务</th><th>学习者</th><th>状态</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-if="recentTasks.length === 0"><td colspan="4" style="text-align:center;color:var(--muted)">暂无任务记录</td></tr>
          <tr v-for="task in recentTasks" :key="task.task_id">
            <td>{{ task.task_id }}</td>
            <td>{{ task.learner_id || '-' }}</td>
            <td><span class="status" :class="task.status === 'completed' ? 'ok' : 'wait'">{{ task.status }}</span></td>
            <td><button class="btn text" @click="openTask(task.task_id)">查看详情</button></td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from '@/composables/useToast'
import { getDomainStats } from '@/api/domains'
import { createGenerationTask, getActiveGenerationTask, listGenerationTasks, type GenerationTaskDetail } from '@/api/generation'
import { getEvaluationSummary } from '@/api/evaluations'
import { listResources } from '@/api/resources'
import { formatBeijingDate } from '@/utils/dateTime'
import { useLearnerStore } from '@/stores/learnerStore'

const router = useRouter()
const learnerStore = useLearnerStore()
const { showToast } = useToast()

const creating = ref(false)
const knowledgeTotal = ref(0)
const questionCount = ref(0)
const resourceCount = ref(0)
const evalCaseCount = ref(0)
const evalDate = ref('-')
const activeTask = ref<GenerationTaskDetail | null>(null)
const recentTasks = ref<GenerationTaskDetail[]>([])

const currentLearnerId = computed(() => learnerStore.selectedLearnerId || '')

onMounted(async () => {
  try {
    const learnerId = currentLearnerId.value
    const [items, task, evalSummary, recent] = await Promise.allSettled([
      getDomainStats('ai_app_dev'),
      learnerId ? getActiveGenerationTask(learnerId) : Promise.resolve(null),
      getEvaluationSummary('live'),
      learnerId ? listGenerationTasks({ learnerId, limit: 5 }) : Promise.resolve([]),
    ])
    if (items.status === 'fulfilled') {
      knowledgeTotal.value = items.value.knowledge_items
      questionCount.value = items.value.diagnostic_questions
    }
    if (learnerId) {
      const resources = await listResources({ learnerId, domainCode: 'ai_app_dev' })
      resourceCount.value = resources.length
    }
    if (task.status === 'fulfilled' && task.value) activeTask.value = task.value
    if (evalSummary.status === 'fulfilled') { evalCaseCount.value = evalSummary.value.case_count; evalDate.value = formatBeijingDate(evalSummary.value.evaluated_at) }
    if (recent.status === 'fulfilled') recentTasks.value = recent.value
  } catch { /* empty state */ }
})

async function handleCreateTask() {
  if (!currentLearnerId.value) {
    showToast('当前账号未关联学习者')
    return
  }
  creating.value = true
  try {
    const result = await createGenerationTask('', currentLearnerId.value, '个性化学习资源生成')
    showToast(`已创建任务 ${result.task_id}`)
    router.push({ path: '/resources', query: { task_id: result.task_id, learner_id: currentLearnerId.value } })
  } catch { showToast('创建失败，请检查后端服务') }
  finally { creating.value = false }
}

function openTask(taskId: string) {
  router.push({ path: '/resources', query: { task_id: taskId, learner_id: currentLearnerId.value } })
}
</script>
