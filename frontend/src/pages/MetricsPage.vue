<template>
  <section class="page journey-page">
    <PageHeader title="学习历程" description="你的每次反馈如何驱动系统更新资源——一条可追溯的学习演进记录。">
      <template #actions>
        <span v-if="domainStore.currentDomainName" class="domain-tag">当前领域：{{ domainStore.currentDomainName }}</span>
        <select v-model="statusFilter" class="field">
          <option value="">全部状态</option>
          <option value="completed">已完成</option>
          <option value="running">处理中</option>
          <option value="failed">失败</option>
        </select>
        <button class="btn" :disabled="loading" @click="loadTasks()">{{ loading ? '加载中...' : '刷新' }}</button>
        <button class="btn" @click="router.push('/dashboard')">返回首页</button>
      </template>
    </PageHeader>

    <header class="journey-hero">
      <div class="hero-stat"><strong>{{ tasks.length }}</strong><span>学习事件</span></div>
      <div class="hero-stat"><strong>{{ feedbackCount }}</strong><span>反馈驱动</span></div>
      <div class="hero-stat"><strong>{{ resourceCount }}</strong><span>累计资源</span></div>
      <div class="hero-stat"><strong>{{ completedCount }}</strong><span>已完成</span></div>
    </header>

    <PageState v-if="loading" type="loading" title="正在加载学习历程" />

    <div v-else-if="errorMessage" class="error-state"><strong>学习历程加载失败</strong><p>{{ errorMessage }}</p><button class="btn" @click="loadTasks()">重新加载</button></div>

    <div v-else-if="tasks.length === 0" class="card empty-state">
      <div class="empty-icon"><AppIcon name="history" /></div>
      <h2>还没有学习记录</h2>
      <p>完成诊断测评并生成第一份学习包后，这里会记录你每次学习与反馈的演进过程。</p>
      <button class="btn primary" @click="router.push('/dashboard')">返回首页</button>
    </div>

    <div v-else class="timeline">
      <div v-for="task in tasks" :key="task.task_id" class="timeline-item">
        <div class="timeline-rail">
          <span class="timeline-dot" :class="eventTone(task)">{{ eventIcon(task) }}</span>
        </div>
        <div class="timeline-card" :class="[eventTone(task), { expanded: expandedId === task.task_id }]" @click="toggleTask(task)">
          <div class="event-head">
            <div class="event-title">
              <strong>{{ eventTitle(task) }}</strong>
              <span class="event-time">{{ formatDate(task.created_at) }}</span>
            </div>
            <span class="status" :class="statusClass(task.status)">{{ statusLabel(task.status) }}</span>
          </div>
          <div class="event-meta">
            <span v-if="task.source_resource" class="event-chip">基于「{{ task.source_resource.title }}」v{{ task.source_resource.version }}</span>
            <span class="event-chip">{{ task.resources.length }} 份资源</span>
            <span v-if="task.revision_count" class="event-chip">修订 {{ task.revision_count }} 次</span>
          </div>

          <div v-if="expandedId === task.task_id" class="event-detail" @click.stop>
            <div v-if="selected?.status === 'failed'" class="task-failure">
              <div class="task-failure-copy">
                <strong>本次学习任务未完成</strong>
                <span>{{ selected.failure_reason || '任务执行失败，请稍后重试。' }}</span>
                <small v-if="canRetry">将从已保存状态恢复，不重复已完成的工作。</small>
                <small v-if="retryError" class="retry-error">{{ retryError }}</small>
              </div>
              <button v-if="canRetry" class="btn small" :disabled="retrying" @click="retryFailedTask">{{ retrying ? '正在提交...' : '从失败阶段重试' }}</button>
            </div>

            <div class="detail-head">
              <h3>本次产物</h3>
              <button class="btn text" @click="router.push({ path: '/resources', query: { task_id: task.task_id, ...(task.learner_id ? { learner_id: task.learner_id } : {}) } })">查看资源</button>
            </div>
            <div v-if="task.resources.length" class="task-artifacts">
              <div v-for="resource in task.resources" :key="resource.resource_id" class="artifact">
                <div><strong>{{ resource.title }}</strong><span>{{ resourceTypeLabel(resource.resource_type) }} · 难度 {{ resource.difficulty }} · v{{ resource.version }}<template v-if="resource.membership_type === 'inherited'"> · 继承上一学习包</template><template v-else-if="task.event_type === 'knowledge_refresh'"> · 本次更新</template></span></div>
                <span class="status" :class="resourceQualityStatusTone(resource.review_status)">{{ resourceQualityStatusLabel(resource.review_status) }}</span>
              </div>
            </div>
            <div v-else class="empty-hint">任务尚未产生可查看资源。</div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getGenerationTask, listGenerationTasks, retryGenerationTask, type GenerationTaskDetail } from '@/api/generation'
import { getLearnerProfile } from '@/api/learners'
import { formatBeijingDateTime } from '@/utils/dateTime'
import AppIcon from '@/components/Shared/AppIcon.vue'
import PageHeader from '@/components/Shared/PageHeader.vue'
import PageState from '@/components/Shared/PageState.vue'
import { resourceQualityStatusLabel, resourceQualityStatusTone } from '@/utils/resourceQualityStatus'
import { useAuthStore } from '@/stores/authStore'
import { useDomainStore } from '@/stores/domainStore'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const domainStore = useDomainStore()
const tasks = ref<GenerationTaskDetail[]>([])
const selected = ref<GenerationTaskDetail | null>(null)
const expandedId = ref('')
const loading = ref(false)
const errorMessage = ref('')
const retryError = ref('')
const retrying = ref(false)
const statusFilter = ref('')
const activeStatuses = ['pending', 'retry_pending', 'running', 'revision_required']
let pollTimer: number | null = null

const completedCount = computed(() => tasks.value.filter(t => t.status === 'completed').length)
const feedbackCount = computed(() => tasks.value.filter(t => t.trigger_type === 'resource_feedback').length)
const resourceCount = computed(() => tasks.value.reduce((sum, t) => sum + (t.resources?.length || 0), 0))
const canRetry = computed(() => selected.value?.status === 'failed')

const FEEDBACK_LABELS: Record<string, string> = { too_hard: '内容太难', too_easy: '内容太简单', confusing: '解释不清楚', incorrect: '内容可能有误', helpful: '对我有帮助' }
const ACTION_LABELS: Record<string, string> = { remedial_explanation: '生成补救解释', challenge_task: '生成挑战任务', revision_required: '修订了资源', regenerate: '修订了资源', review: '复核了资源', challenge: '生成挑战任务', explain: '生成补救解释', profile_update: '更新了画像' }

function eventTitle(task: GenerationTaskDetail): string {
  if (task.event_type === 'knowledge_refresh') {
    const generated = task.resources.filter(resource => resource.membership_type !== 'inherited').length
    const inherited = task.resources.filter(resource => resource.membership_type === 'inherited').length
    return `知识更新 → 生成 ${generated} 份、继承 ${inherited} 份资源`
  }
  if (task.trigger_type === 'resource_feedback' && task.source_feedback) {
    const fb = FEEDBACK_LABELS[task.source_feedback.feedback_type] || task.source_feedback.feedback_type
    const action = ACTION_LABELS[task.source_feedback.triggered_action] || task.source_feedback.triggered_action || '调整了学习内容'
    return `你反馈「${fb}」→ 系统${action}`
  }
  if (task.trigger_type === 'initial_generation') return '创建你的个性化学习包'
  return '学习任务'
}
function eventIcon(task: GenerationTaskDetail): string {
  return task.event_type === 'knowledge_refresh' || task.trigger_type === 'resource_feedback' ? '↻' : '✦'
}
function eventTone(task: GenerationTaskDetail): string {
  if (task.event_type === 'knowledge_refresh') return 'tone-revise'
  if (task.trigger_type !== 'resource_feedback') return 'tone-gen'
  const action = task.source_feedback?.triggered_action
  if (action === 'revision_required' || action === 'regenerate' || action === 'review') return 'tone-revise'
  return 'tone-feedback'
}

function stopPolling() { if (pollTimer !== null) { window.clearTimeout(pollTimer); pollTimer = null } }
function schedulePolling() { stopPolling(); if (tasks.value.some(t => activeStatuses.includes(t.status))) pollTimer = window.setTimeout(() => loadTasks({ silent: true }), 2000) }
function syncSelectedFromList() { if (!expandedId.value) return; const updated = tasks.value.find(t => t.task_id === expandedId.value); if (updated) selected.value = updated }
async function initializeDomainScope() {
  const learnerId = authStore.user?.learner_id
  if (!learnerId) throw new Error('LEARNER_NOT_ASSOCIATED')
  const profile = await getLearnerProfile(learnerId)
  await domainStore.initialize(profile.domain_code)
}
async function loadTasks(options: { silent?: boolean } = {}) {
  if (!options.silent) loading.value = true
  errorMessage.value = ''
  const learnerId = authStore.user?.learner_id || undefined
  const domainCode = domainStore.currentDomainCode
  if (!domainCode) {
    tasks.value = []
    selected.value = null
    expandedId.value = ''
    if (!options.silent) errorMessage.value = '当前学习领域未就绪，请先返回首页选择领域。'
    if (!options.silent) loading.value = false
    return
  }
  try { tasks.value = await listGenerationTasks({ learnerId, domainCode, status: statusFilter.value || undefined }) }
  catch { if (!options.silent) errorMessage.value = '无法读取学习历程，请确认后端服务可用。' }
  finally { if (!options.silent) loading.value = false; syncSelectedFromList(); schedulePolling() }
}
async function toggleTask(task: GenerationTaskDetail) {
  if (expandedId.value === task.task_id) { expandedId.value = ''; selected.value = null; return }
  expandedId.value = task.task_id
  selected.value = task
  selected.value = await getGenerationTask(task.task_id)
}
function statusLabel(v: string) { return ({ pending: '待开始', retry_pending: '等待恢复', running: '处理中', completed: '已完成', failed: '失败', revision_required: '自动修订中', no_change: '无需变更', rejected: '已驳回' } as Record<string, string>)[v] || v }
function statusClass(v: string) { return v === 'completed' ? 'ok' : 'wait' }
function resourceTypeLabel(v: string) { return ({ lecture: '个性化讲义', practice_guide: '实操指南', graded_quiz: '分阶测试' } as Record<string, string>)[v] || v }
async function retryFailedTask() { if (!selected.value || !canRetry.value) return; retrying.value = true; retryError.value = ''; try { const resumed = await retryGenerationTask(selected.value.task_id); selected.value = resumed; tasks.value = tasks.value.map(task => task.task_id === resumed.task_id ? resumed : task); schedulePolling() } catch (error: any) { retryError.value = error?.response?.data?.error?.message || error?.response?.data?.detail || '无法恢复该任务，请刷新后重试。' } finally { retrying.value = false } }
const formatDate = formatBeijingDateTime

watch(statusFilter, () => { stopPolling(); loadTasks() })
watch(() => domainStore.selectionVersion, () => { stopPolling(); expandedId.value = ''; selected.value = null; loadTasks() })
onMounted(async () => {
  try { await initializeDomainScope() }
  catch { errorMessage.value = '无法确定当前学习领域，请返回首页重新选择。' }
  await loadTasks()
  const id = String(route.query.task_id || '')
  if (id) { const item = tasks.value.find(t => t.task_id === id); if (item) await toggleTask(item) }
})
onBeforeUnmount(stopPolling)
</script>

<style scoped>
.journey-page { gap: 20px; max-width: 1080px; margin: 0 auto; }

.card { border: 1px solid var(--line); border-radius: 16px; background: var(--panel); padding: 24px 26px; box-shadow: 0 1px 2px rgb(16 24 40 / .03); }
.empty-state { display: grid; justify-items: center; gap: 8px; padding: 48px 32px; text-align: center; }
.empty-icon { font-size: 40px; }
.empty-state h2 { color: var(--ink); font-size: 18px; }
.empty-state p { max-width: 420px; color: var(--muted); font-size: 13px; line-height: 1.7; }
.empty-state .btn { margin-top: 12px; }

.journey-hero { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; border: 1px solid #e2e8f2; border-radius: 16px; padding: 20px 22px; background: linear-gradient(135deg, #eef3ff 0%, #f8fafc 55%, #eef8f3 100%); }
.domain-tag { border: 1px solid var(--line); border-radius: 6px; background: var(--soft); color: var(--body); padding: 7px 9px; font-size: 12px; white-space: nowrap; }
.hero-stat { display: grid; gap: 4px; }
.hero-stat strong { color: var(--ink); font-size: 26px; line-height: 1; }
.hero-stat span { color: var(--muted); font-size: 12px; }

/* 时间线 */
.timeline { display: grid; gap: 0; }
.timeline-item { display: grid; grid-template-columns: 40px minmax(0, 1fr); gap: 14px; }
.timeline-rail { display: flex; justify-content: center; position: relative; }
.timeline-rail::before { content: ''; position: absolute; top: 0; bottom: -16px; left: 50%; width: 2px; background: var(--track); transform: translateX(-50%); }
.timeline-item:last-child .timeline-rail::before { display: none; }
.timeline-dot { position: relative; z-index: 1; width: 34px; height: 34px; display: grid; place-items: center; border-radius: 50%; background: var(--panel); border: 1px solid var(--line); color: var(--muted); font-size: 15px; font-weight: 700; }
.timeline-dot.tone-gen { background: var(--blue2); border-color: #cbd9f4; color: var(--blue); }
.timeline-dot.tone-feedback { background: var(--green2); border-color: #bfe4d2; color: var(--green); }
.timeline-dot.tone-revise { background: var(--amber2); border-color: #f0d2ac; color: var(--amber); }

.timeline-card { min-width: 0; margin-bottom: 16px; border: 1px solid var(--line); border-radius: 14px; background: var(--panel); padding: 16px 18px; cursor: pointer; box-shadow: 0 1px 2px rgb(16 24 40 / .03); transition: border-color .15s ease, box-shadow .15s ease; }
.timeline-card:hover { border-color: #c3cede; box-shadow: 0 6px 16px rgb(31 48 75 / .08); }
.timeline-card.expanded { border-color: #cbd9f4; box-shadow: 0 6px 18px rgb(31 48 75 / .08); }
.timeline-card.tone-gen { border-left: 3px solid var(--blue); }
.timeline-card.tone-feedback { border-left: 3px solid var(--green); }
.timeline-card.tone-revise { border-left: 3px solid var(--amber); }

.event-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.event-title { min-width: 0; display: grid; gap: 4px; }
.event-title strong { color: var(--ink); font-size: 14.5px; }
.event-time { color: var(--muted); font-size: 12px; }
.event-meta { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 10px; }
.event-chip { border-radius: 6px; background: var(--soft); color: var(--muted); padding: 3px 8px; font-size: 11px; }

/* 展开详情 */
.event-detail { margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--line); }
.progress { display: grid; grid-template-columns: repeat(6, 1fr); gap: 8px; }
.step { display: grid; justify-items: center; gap: 6px; color: var(--muted); font-size: 11px; text-align: center; }
.step-dot { width: 26px; height: 26px; display: grid; place-items: center; border-radius: 50%; border: 1px solid var(--line); background: var(--panel); color: var(--muted); font-size: 12px; font-weight: 700; }
.step.done .step-dot { background: var(--green); border-color: var(--green); color: #fff; }
.step.current .step-dot { background: var(--blue); border-color: var(--blue); color: #fff; }
.step.failed { color: #dc2626; font-weight: 700; }
.step.failed .step-dot { background: #dc2626; border-color: #dc2626; color: #fff; }
.stage-failed-label { color: #dc2626; }
.detail-head { display: flex; align-items: center; justify-content: space-between; margin: 18px 0 10px; }
.detail-head h3 { color: var(--ink); font-size: 14px; }
.task-artifacts { display: grid; gap: 8px; }
.artifact { display: flex; align-items: center; justify-content: space-between; gap: 12px; border: 1px solid #edf1f6; border-radius: 10px; padding: 11px 13px; }
.artifact > div { min-width: 0; display: grid; gap: 3px; }
.artifact strong { color: var(--ink); font-size: 13px; overflow-wrap: anywhere; }
.artifact span { color: var(--muted); font-size: 11.5px; }

.task-failure { display: flex; gap: 12px; align-items: center; justify-content: space-between; margin-top: 14px; padding: 10px 12px; color: #991b1b; background: var(--red2); border: 1px solid #fecaca; border-radius: 8px; }
.task-failure-copy { display: grid; gap: 4px; min-width: 0; }
.task-failure-copy span, .task-failure-copy small { line-height: 1.5; }
.task-failure-copy small { color: var(--red); }
.retry-error { color: #991b1b !important; }

@media (max-width: 700px) {
  .journey-hero { grid-template-columns: repeat(2, 1fr); }
  .progress { grid-template-columns: repeat(3, 1fr); }
}
@media (max-width: 560px) {
  .task-failure { flex-direction: column; align-items: stretch; }
}
</style>
