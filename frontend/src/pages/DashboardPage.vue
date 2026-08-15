<template>
  <section class="dashboard">
    <header class="dashboard-head">
      <div>
        <h1>学习中心</h1>
        <p>从一次测评开始，获取适合你的学习材料。</p>
      </div>
    </header>

    <section v-if="loading" class="learning-stage loading-stage" aria-busy="true" aria-label="正在加载学习状态">
      <div class="loading-line wide"></div>
      <div class="loading-line"></div>
      <div class="loading-line short"></div>
    </section>

    <section v-else-if="loadError" class="learning-stage stage-error" role="alert">
      <div class="stage-copy">
        <span class="stage-label">暂时无法加载</span>
        <h2>学习状态未能读取</h2>
        <p>{{ loadError }}</p>
        <div class="stage-actions"><button class="btn primary" type="button" @click="loadDashboard">重新加载</button></div>
      </div>
    </section>

    <section v-else class="learning-stage" :class="`state-${dashboardState.kind}`">
      <div class="stage-copy">
        <template v-if="dashboardState.kind === 'assessment'">
          <span class="stage-label">从这里开始</span>
          <h2>开始测评</h2>
          <p>完成 10 道题后，系统会准备适合你的学习材料。</p>
          <div class="assessment-facts" aria-label="测评信息"><span>10 道题</span><span>约 10 分钟</span></div>
          <div class="stage-actions"><button class="btn primary stage-primary" type="button" @click="router.push('/diagnostic')">开始测评</button></div>
        </template>

        <template v-else-if="dashboardState.kind === 'preparing'">
          <span class="stage-label">正在处理</span>
          <h2>{{ dashboardState.feedbackTriggered ? '正在调整学习内容' : '正在准备学习内容' }}</h2>
          <p>{{ dashboardState.feedbackTriggered ? '系统正在根据你的反馈调整学习内容。' : '系统正在生成并审核学习材料，完成后会出现在学习资源中。' }}</p>
          <div class="task-progress" :aria-valuenow="progressValue" aria-valuemin="0" aria-valuemax="100" role="progressbar">
            <span><i :style="{ width: `${progressValue}%` }"></i></span>
            <strong v-if="dashboardState.task.progress != null">{{ progressValue }}%</strong>
          </div>
          <div class="stage-actions"><button class="btn primary" type="button" @click="openResources(dashboardState.task.task_id)">查看资源</button></div>
        </template>

        <template v-else-if="dashboardState.kind === 'resource'">
          <span class="stage-label">学习材料已准备好</span>
          <h2>{{ dashboardState.resource.title }}</h2>
          <p>你可以从这份材料开始，系统会在学习过程中根据反馈提供后续支持。</p>
          <div class="resource-meta">
            <span>{{ resourceTypeLabel(dashboardState.resource.resource_type) }}</span>
            <span>难度 {{ dashboardState.resource.difficulty }}/5</span>
            <span>已审核</span>
          </div>
          <div class="stage-actions">
            <button class="btn primary" type="button" @click="openResources()">开始学习</button>
            <button class="btn" type="button" @click="openResources()">查看全部资源</button>
          </div>
        </template>

        <template v-else>
          <span class="stage-label">暂时未完成</span>
          <h2>学习内容还没有准备好</h2>
          <p>{{ dashboardState.task.failure_reason || '本次生成未达到发布标准，请重新生成学习材料。' }}</p>
          <div class="stage-actions"><button class="btn primary" type="button" :disabled="retrying" @click="retryTask(dashboardState.task.task_id)">{{ retrying ? '正在重新生成...' : '重新生成' }}</button></div>
        </template>
      </div>

      <div class="stage-visual" aria-hidden="true">
        <div class="visual-mark"></div>
        <span>{{ visualLabel }}</span>
      </div>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getActiveGenerationTask, listGenerationTasks, retryGenerationTask, type GenerationTaskDetail } from '@/api/generation'
import { listResources, type ResourceSummary } from '@/api/resources'
import { useLearnerStore } from '@/stores/learnerStore'
import { getDashboardState } from './dashboardState'

const router = useRouter()
const learnerStore = useLearnerStore()
const loading = ref(true)
const retrying = ref(false)
const loadError = ref('')
const activeTask = ref<GenerationTaskDetail | null>(null)
const recentTasks = ref<GenerationTaskDetail[]>([])
const resources = ref<ResourceSummary[]>([])

const currentLearnerId = computed(() => learnerStore.selectedLearnerId || '')
const dashboardState = computed(() => getDashboardState(activeTask.value, resources.value, recentTasks.value))
const progressValue = computed(() => Math.min(100, Math.max(0, dashboardState.value.kind === 'preparing' ? dashboardState.value.task.progress ?? 0 : 0)))
const visualLabel = computed(() => ({
  assessment: '准备就绪',
  preparing: '正在处理',
  resource: '可以开始',
  failed: '需要重试',
})[dashboardState.value.kind])

async function loadDashboard() {
  const learnerId = currentLearnerId.value
  loading.value = true
  loadError.value = ''
  try {
    const [active, publishedResources, tasks] = await Promise.all([
      learnerId ? getActiveGenerationTask(learnerId) : Promise.resolve(null),
      learnerId ? listResources({ learnerId, domainCode: 'ai_app_dev' }) : Promise.resolve([]),
      learnerId ? listGenerationTasks({ learnerId, limit: 10 }) : Promise.resolve([]),
    ])
    activeTask.value = active
    resources.value = publishedResources
    recentTasks.value = tasks
  } catch {
    loadError.value = '请检查网络连接后重试。'
  } finally {
    loading.value = false
  }
}

function openResources(taskId?: string | null) {
  router.push({
    path: '/resources',
    query: {
      learner_id: currentLearnerId.value,
      ...(taskId ? { task_id: taskId } : {}),
    },
  })
}

async function retryTask(taskId: string) {
  retrying.value = true
  try {
    const task = await retryGenerationTask(taskId)
    activeTask.value = task
    openResources(task.task_id)
  } catch {
    loadError.value = '重新生成失败，请稍后再试。'
  } finally {
    retrying.value = false
  }
}

function resourceTypeLabel(type: string) {
  return ({ lecture: '讲义', practice_guide: '实操指南', graded_quiz: '测试题' } as Record<string, string>)[type] || type
}

onMounted(loadDashboard)
</script>

<style scoped>
.dashboard { display: grid; gap: 20px; max-width: 1080px; }
.dashboard-head { padding: 10px 2px 2px; }
.dashboard-head h1 { margin: 0; color: var(--ink); font-size: 28px; line-height: 1.25; }
.dashboard-head p { margin: 8px 0 0; color: var(--muted); font-size: 14px; line-height: 1.7; }
.learning-stage { position: relative; display: grid; grid-template-columns: minmax(0, 1fr) 230px; min-height: 360px; overflow: hidden; border: 1px solid var(--line); border-radius: 10px; background: #fff; }
.stage-copy { display: grid; align-content: center; justify-items: start; gap: 14px; padding: 48px 54px; }
.stage-label { color: var(--blue); font-size: 12px; font-weight: 750; }
.stage-copy h2 { max-width: 620px; margin: 0; color: var(--ink); font-size: 30px; line-height: 1.3; text-wrap: balance; }
.stage-copy > p { max-width: 560px; margin: 0; color: var(--muted); font-size: 14px; line-height: 1.75; text-wrap: pretty; }
.stage-actions { display: flex; flex-wrap: wrap; gap: 9px; margin-top: 8px; }
.stage-actions .btn { min-width: 112px; }
.stage-primary { min-height: 42px; padding-inline: 18px; }
.assessment-facts, .resource-meta { display: flex; flex-wrap: wrap; gap: 8px; }
.assessment-facts span, .resource-meta span { border: 1px solid var(--line); border-radius: 6px; background: var(--soft); padding: 5px 8px; color: #405067; font-size: 12px; }
.stage-visual { display: grid; place-content: center; gap: 12px; border-left: 1px solid var(--line); background: #f4f7fb; color: #405067; font-size: 12px; font-weight: 700; text-align: center; }
.visual-mark { width: 48px; height: 48px; margin: auto; border: 10px solid #dce7ff; border-top-color: var(--blue); border-radius: 50%; }
.state-assessment .stage-visual { background: #eef3ff; color: #27457f; }
.state-assessment .visual-mark { border-color: #cbd9ff; border-top-color: #315fce; }
.state-resource .stage-visual { background: #eef8f3; color: #176346; }
.state-resource .visual-mark { border-color: #c8e9d9; border-top-color: var(--green); }
.state-failed .stage-visual { background: #fff7ed; color: #8b4c0b; }
.state-failed .visual-mark { border-color: #fde0bb; border-top-color: var(--amber); }
.task-progress { display: grid; grid-template-columns: minmax(180px, 340px) auto; align-items: center; gap: 10px; width: 100%; margin-top: 2px; }
.task-progress > span { display: block; height: 7px; overflow: hidden; border-radius: 5px; background: #dce4ee; }
.task-progress i { display: block; height: 100%; border-radius: inherit; background: var(--blue); transition: width .22s ease-out; }
.task-progress strong { color: #405067; font-size: 12px; }
.stage-error { display: block; min-height: 280px; border-color: #edc9c9; background: #fffafa; }
.stage-error .stage-label { color: var(--red); }
.loading-stage { display: grid; align-content: center; gap: 14px; padding: 48px 54px; }
.loading-line { width: min(420px, 76%); height: 14px; border-radius: 5px; background: #e9eef5; }
.loading-line.wide { width: min(520px, 92%); height: 32px; }
.loading-line.short { width: 132px; height: 40px; margin-top: 10px; background: #dce7ff; }
@media (max-width: 760px) { .learning-stage { grid-template-columns: 1fr; min-height: 0; } .stage-copy { padding: 34px 26px; } .stage-copy h2 { font-size: 25px; } .stage-visual { min-height: 96px; border-top: 1px solid var(--line); border-left: 0; } .visual-mark { width: 32px; height: 32px; border-width: 7px; } .task-progress { grid-template-columns: minmax(0, 1fr) auto; } }
@media (max-width: 480px) { .dashboard { gap: 16px; } .dashboard-head h1 { font-size: 25px; } .stage-copy { padding: 28px 20px; } .stage-actions { display: grid; width: 100%; } .stage-actions .btn { width: 100%; min-height: 44px; } }
</style>
