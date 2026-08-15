<template>
  <section class="page">
    <div class="head">
      <div><h1>任务记录</h1><p class="sub">查看个性化资源任务的业务进度、产物与审核结果。</p></div>
      <button class="btn" @click="router.push('/dashboard')">返回首页</button>
    </div>

    <div class="metrics">
      <div class="metric"><div><span>任务总数</span></div><strong>{{ tasks.length }}</strong><small>已完成 {{ completedCount }}</small></div>
      <div class="metric"><div><span>运行中</span></div><strong>{{ runningCount }}</strong><small>包含等待审核任务</small></div>
      <div class="metric"><div><span>难度匹配</span></div><strong>{{ percent('difficulty_match_accuracy') }}</strong><small>离线评测目标 ≥ 85%</small></div>
      <div class="metric"><div><span>核心覆盖</span></div><strong>{{ percent('core_knowledge_coverage') }}</strong><small>离线评测目标 ≥ 90%</small></div>
    </div>

    <div class="panel">
      <div class="panel-head">
        <h2>生成任务</h2>
        <div class="filterbar">
          <select v-model="statusFilter" class="field" @change="loadTasks"><option value="">全部状态</option><option value="pending">待开始</option><option value="running">处理中</option><option value="waiting_human">等待复核</option><option value="completed">已完成</option><option value="failed">失败</option></select>
          <button class="btn" :disabled="loading" @click="loadTasks">{{ loading ? '加载中...' : '刷新' }}</button>
        </div>
      </div>
      <div v-if="errorMessage" class="error-state"><strong>任务加载失败</strong><p>{{ errorMessage }}</p><button class="btn" @click="loadTasks">重新加载</button></div>
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
        <div v-for="(step, index) in businessStages" :key="step" class="step" :class="{ done: index < selectedStage, current: index === selectedStage }"><div class="step-dot">{{ index < selectedStage ? '✓' : index + 1 }}</div>{{ step }}</div>
      </div>
      <div class="task-detail-grid" style="margin-top:20px">
        <div><span>学习者</span><strong>{{ selected.learner_id || '-' }}</strong></div><div><span>最终决策</span><strong>{{ decisionLabel(selected.decision) }}</strong></div><div><span>画像版本</span><strong>v{{ selected.profile_version || '-' }}</strong></div><div><span>修订次数</span><strong>{{ selected.revision_count }}</strong></div>
      </div>
      <h3 style="margin:18px 0 10px">任务产物</h3>
      <div v-if="selected.resources.length" class="task-artifacts"><div v-for="resource in selected.resources" :key="resource.resource_id" class="artifact"><div><strong>{{ resource.title }}</strong><span>{{ resourceTypeLabel(resource.resource_type) }} · 难度 {{ resource.difficulty }}</span></div><button class="btn text" @click="router.push({ path: '/resources', query: { task_id: selected!.task_id } })">查看资源</button></div></div>
      <div v-else class="empty-hint">任务尚未产生可查看资源。</div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getEvaluationSummary, type EvaluationSummary } from '@/api/evaluations'
import { getGenerationTask, listGenerationTasks, type GenerationTaskDetail } from '@/api/generation'
import { formatBeijingDateTime } from '@/utils/dateTime'

const route = useRoute(); const router = useRouter()
const tasks = ref<GenerationTaskDetail[]>([]); const selected = ref<GenerationTaskDetail | null>(null)
const loading = ref(false); const errorMessage = ref(''); const statusFilter = ref(''); const evalSummary = ref<EvaluationSummary | null>(null)
const businessStages = ['准备任务', '分析画像', '检索知识', '生成资源', '审核验证', '完成决策']
const completedCount = computed(() => tasks.value.filter(t => t.status === 'completed').length)
const runningCount = computed(() => tasks.value.filter(t => ['pending','running','waiting_human'].includes(t.status)).length)
const selectedStage = computed(() => Math.max(0, Math.min(Math.floor((selected.value?.progress || 0) / 100 * businessStages.length), businessStages.length - 1)))

async function loadTasks() { loading.value = true; errorMessage.value = ''; try { tasks.value = await listGenerationTasks({ status: statusFilter.value || undefined }); const id = String(route.query.task_id || ''); if (id) selected.value = await getGenerationTask(id); else if (selected.value) selected.value = tasks.value.find(t => t.task_id === selected.value?.task_id) || null } catch { errorMessage.value = '无法读取任务数据，请确认后端服务可用。' } finally { loading.value = false } }
async function selectTask(task: GenerationTaskDetail) { selected.value = await getGenerationTask(task.task_id); router.replace({ query: { ...route.query, task_id: task.task_id } }) }
function statusLabel(v: string) { return ({ pending:'待开始',running:'处理中',waiting_human:'等待人工复核',completed:'已完成',failed:'失败',revision_required:'需要修订' } as Record<string,string>)[v] || v }
function statusClass(v: string) { return v === 'completed' ? 'ok' : 'wait' }
function decisionLabel(v: string) { return ({ pending:'待决定',completed:'已完成',manual_review_required:'需要人工复核',revision_required:'需要修订',failed:'失败',no_change:'无需变更',rejected:'已驳回' } as Record<string,string>)[v] || v }
function resourceTypeLabel(v: string) { return ({ lecture:'个性化讲义',practice_guide:'实操指南',graded_quiz:'分阶测试' } as Record<string,string>)[v] || v }
const formatDate = formatBeijingDateTime
function percent(key: 'difficulty_match_accuracy'|'core_knowledge_coverage') { const ratio = evalSummary.value?.metrics[key]?.ratio; return ratio == null ? '-' : `${(ratio*100).toFixed(1)}%` }
onMounted(async () => { await Promise.allSettled([loadTasks(), getEvaluationSummary('live').then(v => { evalSummary.value = v })]) })
</script>
