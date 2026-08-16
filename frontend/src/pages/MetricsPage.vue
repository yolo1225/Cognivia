<template>
  <section class="page">
    <div class="head">
      <div><h1>任务记录</h1><p class="sub">查看个性化资源任务的业务进度、产物与审核结果。</p></div>
      <button class="btn" @click="router.push('/dashboard')">返回首页</button>
    </div>

    <div class="metrics">
      <div class="metric"><div><span>任务总数</span></div><strong>{{ tasks.length }}</strong><small>已完成 {{ completedCount }}</small></div>
      <div class="metric"><div><span>运行中</span></div><strong>{{ runningCount }}</strong><small>包含自动修订任务</small></div>
      <div class="metric"><div><span>难度匹配</span></div><strong>{{ percent('difficulty_match_accuracy') }}</strong><small>离线评测目标 ≥ 85%</small></div>
      <div class="metric"><div><span>核心覆盖</span></div><strong>{{ percent('core_knowledge_coverage') }}</strong><small>离线评测目标 ≥ 90%</small></div>
    </div>

    <div class="panel">
      <div class="panel-head">
        <h2>生成任务</h2>
        <div class="filterbar">
          <select v-model="statusFilter" class="field"><option value="">全部状态</option><option value="pending">待开始</option><option value="running">处理中</option><option value="revision_required">自动修订</option><option value="completed">已完成</option><option value="failed">失败</option></select>
          <button class="btn" :disabled="loading" @click="loadTasks()">{{ loading ? '加载中...' : '刷新' }}</button>
        </div>
      </div>
      <div v-if="errorMessage" class="error-state"><strong>任务加载失败</strong><p>{{ errorMessage }}</p><button class="btn" @click="loadTasks()">重新加载</button></div>
      <div v-else class="table-wrap">
        <table><thead><tr><th>任务</th><th>用户</th><th>状态</th><th>进度</th><th>创建时间</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-if="!loading && tasks.length === 0"><td colspan="6" class="empty-cell">暂无任务记录</td></tr>
            <tr v-for="task in tasks" :key="task.task_id" :class="{ selected: selected?.task_id === task.task_id }" class="task-record-row">
              <td><strong>{{ task.task_id }}</strong></td><td>{{ task.learner_id || '-' }}</td>
              <td><span class="status" :class="statusClass(task.status)">{{ statusLabel(task.status) }}</span></td>
              <td>{{ task.progress || 0 }}%</td><td>{{ formatDate(task.created_at) }}</td>
              <td><button class="btn text" @click="selectTask(task)">查看详情</button></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-if="selected" class="panel task-detail-panel">
      <div class="panel-head"><div><h2>任务详情</h2><p class="sub">{{ selected.task_id }}</p></div><span class="status" :class="statusClass(selected.status)">{{ statusLabel(selected.status) }}</span></div>
      <div class="progress" aria-label="任务业务进度">
        <div v-for="(step, index) in businessStages" :key="step.id" class="step" :class="stageClass(step.id, index)"><div class="step-dot">{{ stageIcon(step.id, index) }}</div>{{ step.label }}<span v-if="stageStatus(step.id) === 'failed'" class="stage-failed-label">（失败）</span></div>
      </div>
      <div v-if="failedRun && selected.status === 'failed'" class="task-failure">
        <div class="task-failure-copy">
          <strong>失败阶段：{{ stageLabel(failedRun) }}</strong>
          <span>{{ failureLabel(failedRun) }}</span>
          <small v-if="canRetry">将从 checkpoint 恢复，已完成的检索和资源生成不会重复执行。</small>
          <small v-if="retryError" class="retry-error">{{ retryError }}</small>
        </div>
        <button v-if="canRetry" class="btn small" :disabled="retrying" @click="retryFailedTask">
          {{ retrying ? '正在提交...' : '从失败阶段重试' }}
        </button>
      </div>
      <div class="task-detail-grid" style="margin-top:20px">
        <div><span>学习者</span><strong>{{ selected.learner_id || '-' }}</strong></div><div><span>最终决策</span><strong>{{ decisionLabel(selected.decision) }}</strong></div><div><span>画像版本</span><strong>v{{ selected.profile_version || '-' }}</strong></div><div><span>修订次数</span><strong>{{ selected.revision_count }}</strong></div>
      </div>
      <h3 style="margin:18px 0 10px">任务产物</h3>
      <div v-if="selected.resources.length" class="task-artifacts"><div v-for="resource in selected.resources" :key="resource.resource_id" class="artifact"><div><strong>{{ resource.title }}</strong><span>{{ resourceTypeLabel(resource.resource_type) }} · 难度 {{ resource.difficulty }}</span></div><button class="btn text" @click="router.push({ path: '/resources', query: { task_id: selected!.task_id, ...(selected!.learner_id ? { learner_id: selected!.learner_id } : {}) } })">查看资源</button></div></div>
      <div v-else class="empty-hint">任务尚未产生可查看资源。</div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getEvaluationSummary, type EvaluationSummary } from '@/api/evaluations'
import { getAgentRuns, getGenerationTask, listGenerationTasks, retryGenerationTask, type AgentRun, type GenerationTaskDetail } from '@/api/generation'
import { formatBeijingDateTime } from '@/utils/dateTime'

const route = useRoute(); const router = useRouter()
const tasks = ref<GenerationTaskDetail[]>([]); const selected = ref<GenerationTaskDetail | null>(null)
const loading = ref(false); const errorMessage = ref(''); const retryError = ref(''); const retrying = ref(false); const statusFilter = ref(''); const evalSummary = ref<EvaluationSummary | null>(null)
const businessStages = [
  { id: 'prepare_task', label: '准备任务' },
  { id: 'analyze_profile', label: '分析画像' },
  { id: 'retrieve_knowledge', label: '检索知识' },
  { id: 'generate_resource', label: '生成资源' },
  { id: 'review_resource', label: '审核验证' },
  { id: 'finalize_task', label: '完成决策' },
]
const activeStatuses = ['pending', 'retry_pending', 'running', 'revision_required']
const agentRuns = ref<AgentRun[]>([])
let pollTimer: number | null = null
const completedCount = computed(() => tasks.value.filter(t => t.status === 'completed').length)
const runningCount = computed(() => tasks.value.filter(t => activeStatuses.includes(t.status)).length)
const selectedStage = computed(() => Math.max(0, Math.min(Math.floor((selected.value?.progress || 0) / 100 * businessStages.length), businessStages.length - 1)))
const failedRun = computed(() => [...agentRuns.value].reverse().find(run => run.status === 'failed'))
const canRetry = computed(() => selected.value?.status === 'failed' && failedRun.value?.output_summary?.recoverable === true)

function stopPolling() { if (pollTimer !== null) { window.clearTimeout(pollTimer); pollTimer = null } }
function schedulePolling() { stopPolling(); if (runningCount.value > 0) pollTimer = window.setTimeout(() => loadTasks({ silent: true }), 2000) }
function syncSelectedFromList() { if (!selected.value) return; selected.value = tasks.value.find(t => t.task_id === selected.value?.task_id) || selected.value }
async function loadTaskRuns(taskId: string) { agentRuns.value = await getAgentRuns(taskId) }
async function loadTasks(options: { silent?: boolean } = {}) { if (!options.silent) loading.value = true; errorMessage.value = ''; try { tasks.value = await listGenerationTasks({ status: statusFilter.value || undefined }); const id = String(route.query.task_id || selected.value?.task_id || ''); if (id) { const listItem = tasks.value.find(t => t.task_id === id); selected.value = listItem || await getGenerationTask(id); await loadTaskRuns(id) } else syncSelectedFromList() } catch { if (!options.silent) errorMessage.value = '无法读取任务数据，请确认后端服务可用。' } finally { if (!options.silent) loading.value = false; schedulePolling() } }
async function selectTask(task: GenerationTaskDetail) { selected.value = task; agentRuns.value = []; router.replace({ query: { ...route.query, task_id: task.task_id } }); [selected.value, agentRuns.value] = await Promise.all([getGenerationTask(task.task_id), getAgentRuns(task.task_id)]); syncSelectedFromList() }
function stageStatus(stepId: string) { const runs = agentRuns.value.filter(run => String(run.input_summary?.step || run.output_summary?.step || '') === stepId); return runs.at(-1)?.status }
function runStep(run: AgentRun) { return String(run.input_summary?.step || run.output_summary?.step || '') }
function stageLabel(run: AgentRun) { return businessStages.find(stage => stage.id === runStep(run))?.label || run.agent_name }
function failureLabel(run: AgentRun) { const code = String(run.output_summary?.failure_code || run.error || ''); return ({ review_output_truncated:'审核模型输出被截断',review_structured_output_invalid:'审核模型返回结构无效',review_claim_set_mismatch:'审核 claim 集不完整',review_model_call_failed:'审核模型调用超时或暂时不可用',review_execution_failed:'审核执行失败' } as Record<string,string>)[code] || '任务执行失败' }
function stageClass(stepId: string, index: number) { const status = stageStatus(stepId); if (status) return { done: status === 'completed', current: status === 'running', failed: status === 'failed' }; return agentRuns.value.length ? {} : { done: index < selectedStage.value, current: index === selectedStage.value } }
function stageIcon(stepId: string, index: number) { const status = stageStatus(stepId); if (status === 'completed') return '✓'; if (status === 'failed') return '!'; return index + 1 }
function statusLabel(v: string) { return ({ pending:'待开始',retry_pending:'等待恢复',running:'处理中',completed:'已完成',failed:'失败',revision_required:'自动修订中',no_change:'无需变更',rejected:'已驳回' } as Record<string,string>)[v] || v }
function statusClass(v: string) { return v === 'completed' ? 'ok' : 'wait' }
function decisionLabel(v: string) { return ({ pending:'待决定',completed:'已完成',revision_required:'需要修订',failed:'失败',no_change:'无需变更',rejected:'已驳回' } as Record<string,string>)[v] || v }
function resourceTypeLabel(v: string) { return ({ lecture:'个性化讲义',practice_guide:'实操指南',graded_quiz:'分阶测试' } as Record<string,string>)[v] || v }
async function retryFailedTask() { if (!selected.value || !canRetry.value) return; retrying.value = true; retryError.value = ''; try { const resumed = await retryGenerationTask(selected.value.task_id); selected.value = resumed; tasks.value = tasks.value.map(task => task.task_id === resumed.task_id ? resumed : task); schedulePolling() } catch (error: any) { retryError.value = error?.response?.data?.error?.message || error?.response?.data?.detail || '无法恢复该任务，请刷新后重试。' } finally { retrying.value = false } }
const formatDate = formatBeijingDateTime
function percent(key: 'difficulty_match_accuracy'|'core_knowledge_coverage') { const ratio = evalSummary.value?.metrics[key]?.ratio; return ratio == null ? '-' : `${(ratio*100).toFixed(1)}%` }
watch(statusFilter, () => { stopPolling(); loadTasks() })
onMounted(async () => { await Promise.allSettled([loadTasks(), getEvaluationSummary('live').then(v => { evalSummary.value = v })]) })
onBeforeUnmount(stopPolling)
</script>

<style scoped>
.step.failed {
  color: #dc2626;
  font-weight: 700;
}

.step.failed .step-dot {
  color: #fff;
  background: #dc2626;
  border-color: #dc2626;
}

.stage-failed-label {
  color: #dc2626;
}

.task-failure {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  margin-top: 14px;
  padding: 10px 12px;
  color: #991b1b;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 6px;
}

.task-failure-copy {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.task-failure-copy span,
.task-failure-copy small {
  line-height: 1.5;
}

.task-failure-copy small {
  color: #7a4545;
}

.retry-error {
  color: #991b1b !important;
}

@media (max-width: 640px) {
  .task-failure {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
