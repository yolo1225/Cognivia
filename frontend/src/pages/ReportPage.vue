<template>
  <section class="page report-page">
    <PageHeader title="学情画像" description="从能力结构、学习重点和个性化路线了解当前学习状态。">
      <template #actions>
        <span class="learner-tag">学习者 {{ learnerId || '-' }}</span>
        <button type="button" class="btn" :disabled="loading" :aria-busy="loading" @click="() => loadReport()">{{ loading ? '正在刷新' : '刷新报告' }}</button>
      </template>
    </PageHeader>

    <PageState v-if="loading" type="loading" title="正在加载学情画像" />

    <div v-else-if="errorMessage" class="error-state"><strong>画像加载失败</strong><p>{{ errorMessage }}</p><button class="btn" @click="() => loadReport()">重新加载</button></div>

    <div v-else-if="!report" class="card empty-state">
      <div class="empty-icon"><AppIcon name="report" /></div>
      <h2>尚未形成学情画像</h2>
      <p>请先在首页完成学习背景建档和首次能力诊断，系统将据此生成能力画像与学习路线。</p>
      <button class="btn primary" @click="router.push('/dashboard')">返回首页</button>
    </div>

    <template v-else>
      <header class="profile-overview">
        <div class="overview-copy">
          <span class="section-kicker">当前学情</span>
          <h2>{{ profileTypeLabel(report.profile_type) }}</h2>
          <p>基于诊断结果形成，后续学习和作答会持续更新。</p>
          <div class="overview-tags"><span v-for="direction in directionList" :key="direction">{{ direction }}</span><span>{{ contextSnapshot.education_level || '学习背景待补充' }}</span></div>
          <small>画像 {{ profileVersionLabel }} · {{ formatDate(profileUpdatedAt) }} 更新</small>
        </div>
        <div class="overview-stats" aria-label="学情摘要">
          <div><span>诊断表现</span><strong>{{ diagnosticTotalScore }}%</strong><small>{{ diagnosticCorrectCount }}/{{ diagnosticAnswerCount }} 题答对</small></div>
          <div><span>待加强</span><strong>{{ sortedWeakKnowledge.length }}</strong><small>项重点知识</small></div>
          <div><span>路线进度</span><strong>{{ percentOrEmpty(progress?.path_progress?.completion_rate) }}</strong><small>已完成 {{ completedPathNodeCount }}/{{ pathNodes.length }} 节</small></div>
        </div>
        <aside v-if="currentTask" class="overview-action" :class="`action-${currentTask.tone}`">
          <span>{{ currentTask.eyebrow }}</span><strong>{{ currentTask.title }}</strong><p>{{ currentTask.description }}</p>
          <button type="button" class="btn primary" :disabled="currentTask.disabled" @click="runCurrentTask">{{ currentTask.button }}</button>
        </aside>
      </header>

      <section class="card ability-section">
        <div class="card-head"><div><h2>能力结构</h2><p class="section-note">展示当前诊断与学习证据支持的能力判断。</p></div><span v-if="progress?.available" class="version-pill">较首次诊断</span></div>
        <div class="ability-profile-body">
          <div class="radar-wrap"><RadarChart :values="abilityValues" :baseline-values="baselineAbilityValues" :indicators="abilityLabels" /></div>
          <div class="ability-insights">
            <article v-for="insight in abilityInsights" :key="insight.label" :class="`insight-${insight.tone}`"><span>{{ insight.label }}</span><strong>{{ insight.value }}</strong><p>{{ insight.description }}</p></article>
          </div>
        </div>
        <div v-if="resourceDifficultyMatchData.length" class="resource-match-panel">
          <div class="resource-match-copy">
            <div><h3>资源难度匹配</h3><p>以资源实际难度和审核确认的适配度呈现本轮学习内容匹配情况。</p></div>
            <span>目标适配度 ≥ 85%</span>
          </div>
          <ResourceDifficultyMatchChart :data="resourceDifficultyMatchData" />
        </div>
      </section>

      <section class="card knowledge-progress-section">
        <div class="card-head"><div><h2>知识盲区与学习重点 <span class="knowledge-count">{{ sortedWeakKnowledge.length }}</span></h2><p class="section-note">基于诊断确认的待补强知识，按优先级排列并已纳入学习路线。</p></div><button v-if="blockingMistakeCount" type="button" class="btn" @click="openMistakeReview">进入错题巩固</button></div>
        <div v-if="sortedWeakKnowledge.length" class="weak-grid-compact">
          <article v-for="(item, index) in sortedWeakKnowledge" :key="item.knowledge_id" class="weak-row"><span class="weak-rank">{{ index + 1 }}</span><div><strong>{{ item.name }}</strong><small>{{ item.category }}</small></div><span class="severity-badge" :class="severityLevel(item.weakness_level)">{{ weaknessLabel(item.weakness_level) }}</span></article>
        </div>
        <div v-else class="weak-empty"><span aria-hidden="true">✓</span><div><strong>当前没有已确认的薄弱知识点</strong><p>继续完成当前路线，新的证据会更新画像。</p></div></div>
      </section>

      <section class="card learning-path-section">
        <div class="card-head"><div><h2>个性化学习路线</h2><p class="section-note">根据能力结构和重点知识安排学习顺序。</p></div><span class="path-progress-text">已完成 {{ completedPathNodeCount }} / {{ pathNodes.length }} 节</span></div>
        <div v-if="pathNodes.length" class="path-visualization">
          <LearningPathGraph :nodes="pathNodes" :selected-id="selectedPathNode?.path_node_id" @select="selectPathNode" />
          <article v-if="selectedPathNode" class="path-node-detail" :class="`node-${selectedPathNode.status}`"><header><div><span class="path-detail-kicker">第 {{ selectedPathNode.path_order }} 节 · {{ pathStatusLabel(selectedPathNode.status) }}</span><h3>{{ selectedPathNode.title }}</h3></div><span class="node-status">{{ selectedPathNode.status === 'current' ? '当前节点' : pathStatusLabel(selectedPathNode.status) }}</span></header><p>{{ selectedPathNode.learning_objective }}</p><div class="path-knowledge-list"><span v-for="knowledgeId in selectedPathNode.focus_knowledge_ids" :key="knowledgeId" class="focus">{{ knowledgeLabel(selectedPathNode, knowledgeId) }}</span></div><footer><span>完成条件：单元验证 {{ Math.round(selectedPathNode.completion_condition.threshold * 100) }}%<template v-if="selectedPathNode.completion_condition.focus_threshold">，重点知识不低于 {{ Math.round(selectedPathNode.completion_condition.focus_threshold * 100) }}%</template></span><button v-if="selectedPathNode.status === 'current' && !currentTask" type="button" class="btn primary" :disabled="creatingGeneration" @click="runNodeAction(selectedPathNode)">{{ nodeActionLabel(selectedPathNode) }}</button></footer></article>
        </div>
        <div v-else-if="report.path_detail?.length" class="path-h"><div v-for="(stage, index) in report.path_detail" :key="index" class="path-h-step"><span class="path-num">{{ index + 1 }}</span><div><h3>{{ stage.name }}</h3><p>{{ stage.description || '根据当前画像推荐' }}</p></div></div></div>
        <div v-else class="empty-hint">尚未形成可展示的学习路线。</div>
      </section>

      <section v-if="profileChanges.length" class="card profile-change-section">
        <div class="card-head"><div><h2>画像更新记录</h2><p class="section-note">仅记录由正式学习证据确认的变化。</p></div></div>
        <article v-for="change in displayedProfileChanges" :key="change.proposal_id" class="profile-change-row"><div class="change-main"><strong>{{ change.profile_change_summary.knowledge_name }}</strong><p>{{ profileChangeLabel(change) }}</p><small>画像 V{{ change.profile_change_summary.original_profile_version }} → V{{ change.profile_change_summary.resulting_profile_version }} · {{ formatDate(change.updated_at || change.created_at) }}</small></div><div class="change-route"><span>{{ change.profile_change_summary.ability_summary }}</span><small v-if="change.profile_change_summary.completed_node_id">已完成 {{ nodeTitle(change.profile_change_summary.completed_node_id) }}，{{ adjustmentPackageImpact(change) }}</small><small v-else>学习路线保持在当前节点</small></div></article>
      </section>

      <section v-if="recentResources.length" class="card recent-resources-section"><div class="card-head"><div><h2>最近学习资源</h2><p class="section-note">继续查看已为当前画像准备的学习内容。</p></div></div><div class="recent-resource-list"><article v-for="resource in recentResources" :key="resource.resource_id"><span class="resource-type">{{ resource.resource_type_label || resource.resource_type }}</span><strong>{{ resource.title }}</strong><button type="button" class="btn" @click="openRecentResource(resource.generation_task_id)">查看资源</button></article></div></section>

    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getLearningReport, type LearningReport } from '@/api/reports'
import type { LearningPathNode } from '@/api/learningPaths'
import { decideLearningAdjustmentResource, type LearningAdjustmentSummary } from '@/api/learningAdjustments'
import { useToast } from '@/composables/useToast'
import { generationFailureCopy } from '@/utils/generationFailure'
import { createGenerationTask } from '@/api/generation'
import RadarChart from '@/components/Charts/RadarChart.vue'
import LearningPathGraph from '@/components/Charts/LearningPathGraph.vue'
import ResourceDifficultyMatchChart from '@/components/Charts/ResourceDifficultyMatchChart.vue'
import { toResourceDifficultyMatchData } from '@/components/Charts/resourceDifficultyMatch'
import AppIcon from '@/components/Shared/AppIcon.vue'
import PageHeader from '@/components/Shared/PageHeader.vue'
import PageState from '@/components/Shared/PageState.vue'
import { useAuthStore } from '@/stores/authStore'
import { useDomainStore } from '@/stores/domainStore'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const domainStore = useDomainStore()
const { showToast } = useToast()
const taskId = computed(() => String(route.query.task_id || '').trim())
const isAdminTaskContext = computed(() => authStore.role === 'admin' && Boolean(taskId.value))
const learnerId = computed(() => {
  const source = isAdminTaskContext.value
    ? route.query.learner_id
    : authStore.user?.learner_id
  const normalized = String(source || '').trim()
  return ['null', 'undefined'].includes(normalized.toLowerCase()) ? '' : normalized
})
const report = ref<LearningReport | null>(null)
const loading = ref(false)
const errorMessage = ref('')
const creatingGeneration = ref(false)
const adjustmentSubmitting = ref('')
let reportRefreshTimer: number | null = null

const abilityDimensions = [
  { key: 'theory', label: '理论掌握' },
  { key: 'practice', label: '实操应用' },
  { key: 'problem_solving', label: '场景解决' },
  { key: 'knowledge_breadth', label: '知识广度' },
  { key: 'learning_speed', label: '学习速度' },
] as const
const DIRECTION_LABELS: Record<string, string> = {
  llm_application: '大模型应用开发',
  prompt_engineering: 'Prompt 工程',
  rag_knowledge_base: 'RAG 知识库构建',
  agent_orchestration: 'Agent 编排',
}

const progress = computed(() => report.value?.progress_comparison)
const radarDimensions = computed(() => abilityDimensions
  .map((dimension, index) => ({ ...dimension, index }))
  .filter(dimension => !dimensionIsUnassessed(dimension.key)))
const abilityLabels = computed(() => radarDimensions.value.map(dimension => dimension.label))
const abilityValues = computed(() => radarDimensions.value.map(dimension => Number(report.value?.radar?.[dimension.index] || 0)))
const baselineAbilityValues = computed(() => progress.value?.baseline?.radar
  ? radarDimensions.value.map(dimension => Number(progress.value?.baseline?.radar?.[dimension.index] || 0))
  : undefined)
const abilityRows = computed(() => abilityDimensions.map((dimension, index) => ({
  label: dimension.label,
  value: Math.max(0, Math.min(100, Number(report.value?.radar?.[index] || 0))),
  delta: progress.value?.ability_changes?.[index]?.delta,
  unassessed: dimensionIsUnassessed(dimension.key),
})))
const sortedWeakKnowledge = computed(() => [...(report.value?.weak_knowledge || [])].sort((a, b) => b.weakness_level - a.weakness_level))
const contextSnapshot = computed<Record<string, unknown>>(() => report.value?.context_snapshot || {})
const directionList = computed(() => {
  const tags = (Array.isArray(contextSnapshot.value.direction_tags) ? contextSnapshot.value.direction_tags : report.value?.direction_tags) || []
  const directions = domainStore.domains.find(item => item.domain_code === report.value?.domain_code)?.learning_directions || []
  return [...new Set(tags.map(value => {
    const code = String(value)
    return directions.find(item => item.value === code)?.label || DIRECTION_LABELS[code] || '专项学习方向'
  }))]
})
const diagnosticTotalScore = computed(() => Math.round(Number(report.value?.diagnostic_summary?.total_score || 0)))
const diagnosticCorrectCount = computed(() => Number(report.value?.diagnostic_summary?.correct_count || 0))
const diagnosticAnswerCount = computed(() => Number(report.value?.diagnostic_summary?.answer_count || 0))
const pathNodes = computed<LearningPathNode[]>(() => report.value?.learning_path?.nodes || [])
const currentPathNode = computed(() => pathNodes.value.find(node => node.status === 'current') || null)
const completedPathNodeCount = computed(() => pathNodes.value.filter(node => node.status === 'completed').length)
const blockingMistakeCount = computed(() => Number(report.value?.node_gate?.blocking_mistake_count || 0))
const selectedPathNodeId = ref('')
const selectedPathNode = computed(() => (
  pathNodes.value.find(node => node.path_node_id === selectedPathNodeId.value)
  || pathNodes.value.find(node => node.status === 'current')
  || pathNodes.value[0]
  || null
))
const profileChanges = computed(() => [...(report.value?.profile_changes || [])].sort((left, right) => (
  new Date(right.updated_at || right.created_at || 0).getTime() - new Date(left.updated_at || left.created_at || 0).getTime()
)))
const displayedProfileChanges = computed(() => profileChanges.value.slice(0, 4))
const recentResources = computed(() => (report.value?.resource_summary?.recent || []).slice(0, 3))
const resourceDifficultyMatchData = computed(() => toResourceDifficultyMatchData(
  report.value?.resource_summary?.recent || [],
))
const profileVersionLabel = computed(() => progress.value?.current?.profile_version ? `V${progress.value.current.profile_version}` : '版本待确认')
const profileUpdatedAt = computed(() => progress.value?.period?.updated_at)
const activeAdjustment = computed(() => (report.value?.learning_adjustments || []).find(proposal => (
  proposal.status === 'resource_pending'
  || proposal.recovery_available
  || ['pending', 'retry_pending', 'running', 'revision_required', 'failed'].includes(proposal.generation_task?.status || '')
)) || null)
const hasActiveAdjustmentGeneration = computed(() => (report.value?.learning_adjustments || []).some(
  proposal => ['pending', 'retry_pending', 'running', 'revision_required'].includes(
    proposal.generation_task?.status || '',
  ),
))

const abilityInsights = computed(() => {
  const assessed = abilityRows.value.filter(item => !item.unassessed)
  const strongest = [...assessed].sort((left, right) => right.value - left.value)[0]
  const weakest = [...assessed].sort((left, right) => left.value - right.value)[0]
  const observations = [] as Array<{ label: string; value: string; description: string; tone: 'strength' | 'focus' | 'observe' }>
  if (strongest) observations.push({ label: '当前优势', value: strongest.label, description: '这一能力在本轮诊断中表现相对稳定。', tone: 'strength' })
  if (sortedWeakKnowledge.value[0]) observations.push({ label: '优先提升', value: sortedWeakKnowledge.value[0].name, description: '已纳入当前学习路线，建议优先完成相关学习内容。', tone: 'focus' })
  else if (weakest) observations.push({ label: '持续练习', value: weakest.label, description: '通过当前路线的练习继续巩固这项能力。', tone: 'focus' })
  const pending = abilityRows.value.filter(item => item.unassessed).map(item => item.label)
  observations.push({
    label: '持续观察',
    value: pending.length ? pending.join('、') : '学习进展',
    description: pending.length ? '随着后续学习和作答，系统会逐步补充判断。' : '后续学习证据会持续校准当前画像。',
    tone: 'observe',
  })
  return observations.slice(0, 3)
})

type CurrentTask = {
  tone: 'mistake' | 'resource' | 'route'
  eyebrow: string
  title: string
  description: string
  button: string
  disabled: boolean
  action: 'mistake' | 'adjustment_generate' | 'adjustment_view' | 'node_resource' | 'node_generate'
  proposal?: LearningAdjustmentSummary
  node?: LearningPathNode
}

const currentTask = computed<CurrentTask | null>(() => {
  if (blockingMistakeCount.value) return {
    tone: 'mistake', eyebrow: '当前优先任务', title: `先完成 ${blockingMistakeCount.value} 道错题巩固`,
    description: '这些错题与当前学习节点直接相关，完成后才能继续推进路线。', button: '开始错题巩固', disabled: false, action: 'mistake',
  }
  const proposal = activeAdjustment.value
  if (proposal) {
    if (proposal.status === 'resource_pending' || proposal.recovery_available || proposal.generation_task?.status === 'failed') return {
      tone: 'resource', eyebrow: '当前学习安排', title: proposal.resource_recommendation.mode === 'remedial' ? '补充当前节点学习内容' : '准备下一节点学习内容',
      description: '画像已更新，确认后将生成与当前状态匹配的学习资源。', button: adjustmentGenerateLabel(proposal, Boolean(proposal.recovery_available || proposal.generation_task?.status === 'failed')),
      disabled: adjustmentSubmitting.value === proposal.proposal_id, action: 'adjustment_generate', proposal,
    }
    if (proposal.generation_task?.task_id) return {
      tone: 'resource', eyebrow: '当前学习安排', title: '学习内容正在准备',
      description: '资源生成与质量校验完成后，可直接进入学习。', button: adjustmentTaskAction(proposal), disabled: false, action: 'adjustment_view', proposal,
    }
  }
  const node = currentPathNode.value
  if (!node) return null
  if (node.resource_state === 'ready') return { tone: 'route', eyebrow: '当前学习节点', title: node.title, description: node.learning_objective, button: '继续当前学习', disabled: false, action: 'node_resource', node }
  if (node.resource_state === 'generating') return { tone: 'resource', eyebrow: '当前学习节点', title: '学习内容正在准备', description: `正在为「${node.title}」生成学习内容。`, button: '查看生成进度', disabled: false, action: 'node_resource', node }
  return { tone: 'route', eyebrow: '当前学习节点', title: node.title, description: node.learning_objective, button: node.resource_state === 'failed' ? '重新生成学习内容' : '生成学习内容', disabled: creatingGeneration.value, action: 'node_generate', node }
})

function percentOrEmpty(value?: number | null) { return value == null ? '暂无' : `${Math.round(value)}%` }
function formatDate(value?: string | null) { return value ? new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: 'numeric', day: 'numeric' }).format(new Date(value)) : '待确认' }

function pathStatusLabel(status: LearningPathNode['status']) {
  return ({ locked: '未解锁', current: '当前学习', completed: '已完成', skipped: '已跳过' } as const)[status]
}

function knowledgeStateLabel(state: string) {
  return ({
    unassessed: '未评估',
    unmastered: '未掌握',
    confused: '易混淆',
    partial_mastery: '部分掌握',
    known: '已掌握',
    not_weak: '非薄弱项',
  } as Record<string, string>)[state] || state
}

function adjustmentTaskAction(proposal: LearningAdjustmentSummary) {
  if (proposal.generation_task?.status !== 'completed') return '查看生成进度'
  return proposal.resource_recommendation.mode === 'remedial' ? '查看补救资源' : '查看下一节点资源'
}

function adjustmentGenerateLabel(proposal: LearningAdjustmentSummary, retry = false) {
  const label = proposal.resource_recommendation.mode === 'remedial' ? '补救资源' : '下一节点学习包'
  return `${retry ? '重新生成' : '生成'}${label}`
}

function profileChangeLabel(change: NonNullable<LearningReport['profile_changes']>[number]) {
  const summary = change.profile_change_summary
  const target = knowledgeStateLabel(summary.after_state)
  if (summary.before_state === 'unassessed' && summary.after_state === 'partial_mastery') {
    return `新增正式证据 · 初步掌握（${target}）`
  }
  return `${knowledgeStateLabel(summary.before_state)} → ${target}`
}

function adjustmentPackageImpact(change: NonNullable<LearningReport['profile_changes']>[number]) {
  const task = change.generation_task
  if (!task) return '下一节点学习包待确认'
  if (task.status === 'failed' || task.decision === 'no_change') return '下一节点学习包待重新生成'
  if (task.status !== 'completed') return '下一节点学习包生成中'
  return '下一节点学习包已完成'
}

function dimensionIsUnassessed(dimension: typeof abilityDimensions[number]['key']) {
  const status = report.value?.dimension_status?.[dimension]
  if (status === 'unassessed' || status === 'insufficient_evidence' || status === 'insufficient_longitudinal_evidence') return true
  return dimension === 'learning_speed' && status !== 'assessed'
}

function nodeTitle(nodeId?: string | null) {
  if (!nodeId) return '路线完成'
  return pathNodes.value.find(node => node.path_node_id === nodeId)?.title || nodeId
}
function knowledgeLabel(node: LearningPathNode, knowledgeId: string) {
  return node.knowledge_items?.find(item => item.knowledge_id === knowledgeId)?.name || knowledgeId
}
function selectPathNode(nodeId: string) { selectedPathNodeId.value = nodeId }

function openMistakeReview() {
  router.push({ path: '/mistake-review', query: learnerId.value ? { learner_id: learnerId.value } : {} })
}

function nodeActionLabel(node: LearningPathNode) {
  if (node.resource_state === 'ready') return '继续当前学习'
  if (node.resource_state === 'generating') return '查看生成进度'
  return node.resource_state === 'failed' ? '重新生成学习内容' : '生成学习内容'
}

function runNodeAction(node: LearningPathNode) {
  if (node.resource_state === 'ready' || node.resource_state === 'generating') openNodeResource(node)
  else void generateNodeResources(node)
}

function openRecentResource(taskId?: string | null) {
  router.push({ path: '/resources', query: { ...(learnerId.value ? { learner_id: learnerId.value } : {}), ...(taskId ? { task_id: taskId } : {}) } })
}

function runCurrentTask() {
  const task = currentTask.value
  if (!task || task.disabled) return
  if (task.action === 'mistake') { openMistakeReview(); return }
  if (task.action === 'adjustment_generate' && task.proposal) { void decideReportAdjustment(task.proposal.proposal_id, 'generate'); return }
  if (task.action === 'adjustment_view' && task.proposal?.generation_task?.task_id) { openRecentResource(task.proposal.generation_task.task_id); return }
  if (task.node) runNodeAction(task.node)
}

async function decideReportAdjustment(proposalId: string, decision: 'generate' | 'skip') {
  if (adjustmentSubmitting.value) return
  adjustmentSubmitting.value = proposalId
  try {
    const result = await decideLearningAdjustmentResource(proposalId, decision)
    if (result.task_id) {
      await router.push({ path: '/resources', query: { task_id: result.task_id, ...(learnerId.value ? { learner_id: learnerId.value } : {}) } })
    } else {
      await loadReport()
      showToast('已暂不生成，画像与路线调整保持生效。', 'info')
    }
  } catch { showToast('资源选择保存失败，路线可能已更新。', 'error') }
  finally { adjustmentSubmitting.value = '' }
}

function openNodeResource(node: LearningPathNode) {
  router.push({ path: '/resources', query: node.resource_task_id ? { task_id: node.resource_task_id } : {} })
}

async function generateNodeResources(node: LearningPathNode) {
  const pathId = report.value?.learning_path?.path_id
  if (!pathId || !report.value?.profile_id || !learnerId.value) return
  creatingGeneration.value = true
  try {
    const task = await createGenerationTask(
      report.value.domain_code,
      report.value.profile_id,
      learnerId.value,
      `学习路径第 ${node.path_order} 节：${node.title}`,
      { pathId, nodeId: node.path_node_id },
    )
    router.push({ path: '/resources', query: { learner_id: learnerId.value, task_id: task.task_id } })
  } catch (error: unknown) { showToast(nodeGenerationErrorMessage(error), 'error') }
  finally { creatingGeneration.value = false }
}

function nodeGenerationErrorMessage(error: unknown) {
  const detail = (error as { response?: { data?: { error?: { code?: string; message?: string } } } })
    ?.response?.data?.error
  if (detail?.code === 'GRADED_QUIZ_QUESTION_BANK_NOT_READY') {
    return '当前学习单元的正式认证题不足 3 道，暂不能生成分级测验。'
  }
  if (detail?.message?.includes('DOMAIN_GENERATION_NOT_READY:question_source_binding_invalid')) {
    return '领域题目来源校验未通过，系统已阻止生成以保证内容可追溯。'
  }
  if (detail?.code === 'http_409' && detail.message === 'PATH_NODE_CHANGED') {
    return '学习路线已更新，请刷新报告后按新的当前节点生成资源。'
  }
  return detail?.message || '创建节点学习包失败，请稍后重试。'
}

function profileTypeLabel(type?: string) {
  return ({ beginner: '基础起步型学习者', intermediate: '进阶提升型学习者', advanced: '综合应用型学习者', practice_oriented: '实操导向型学习者' } as Record<string, string>)[type || ''] || type || '画像待确认'
}

function weaknessLabel(level: number) {
  if (level >= 4) return '优先补强'
  if (level === 3) return '重点巩固'
  return '持续练习'
}

function severityLevel(level: number) {
  if (level >= 4) return 'high'
  if (level === 3) return 'mid'
  return 'low'
}

function clearReportRefreshTimer() {
  if (reportRefreshTimer !== null) window.clearTimeout(reportRefreshTimer)
  reportRefreshTimer = null
}

function scheduleReportRefresh() {
  clearReportRefreshTimer()
  if (!hasActiveAdjustmentGeneration.value) return
  reportRefreshTimer = window.setTimeout(() => {
    void loadReport(true)
  }, 2000)
}

async function loadReport(silent = false) {
  if (!learnerId.value) {
    clearReportRefreshTimer()
    report.value = null
    errorMessage.value = '当前账号未关联有效学习者，请重新登录或联系管理员。'
    return
  }
  if (!silent) {
    loading.value = true
    errorMessage.value = ''
  }
  try {
    const data = await getLearningReport(learnerId.value, taskId.value || undefined)
    report.value = data.profile_ready ? data : null
    if (report.value?.domain_code) await domainStore.initialize(report.value.domain_code)
    scheduleReportRefresh()
  } catch {
    if (!silent) {
      report.value = null
      errorMessage.value = '无法读取学情画像，请确认后端服务可用。'
    }
  } finally {
    if (!silent) loading.value = false
  }
}

function refreshOnFocus() {
  void loadReport()
}

watch(() => [route.query.learner_id, route.query.task_id], () => {
  void loadReport()
})
onMounted(() => {
  void loadReport()
  window.addEventListener('focus', refreshOnFocus)
})
onBeforeUnmount(() => {
  clearReportRefreshTimer()
  window.removeEventListener('focus', refreshOnFocus)
})
</script>

<style scoped>
.report-page { gap: 20px; max-width: 1080px; margin: 0 auto; }
.path-node-reason { color: var(--text-secondary); }
.path-knowledge-list { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0; }
.path-knowledge-list > span { border: 1px solid var(--line); border-radius: 6px; padding: 4px 7px; background: var(--panel-muted); font-size: 12px; }
.path-knowledge-list > span.focus { border-color: var(--warning); background: var(--warning-soft); }
.path-knowledge-list small { margin-left: 5px; color: var(--warning-strong); }

/* 通用卡片 */
.card { border: 1px solid var(--line); border-radius: 16px; background: var(--panel); padding: 24px 26px; box-shadow: var(--shadow-card); }
.card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 18px; }
.card-head h2 { color: var(--ink); font-size: 17px; }
.section-note { margin-top: 4px; color: var(--muted); font-size: 12px; line-height: 1.5; }
.empty-state { display: grid; justify-items: center; gap: 8px; padding: 48px 32px; text-align: center; }
.empty-icon { font-size: 40px; }
.empty-state h2 { color: var(--ink); font-size: 18px; }
.empty-state p { max-width: 420px; color: var(--muted); font-size: 13px; line-height: 1.7; }
.empty-state .btn { margin-top: 12px; }

/* Hero 身份卡 */
.hero { display: flex; align-items: center; justify-content: space-between; gap: 24px; border: 1px solid var(--line); border-radius: 16px; padding: 26px 28px; background: var(--surface-raised); }
.hero-kicker { color: var(--blue); font-size: 12px; font-weight: 750; }
.hero-id h2 { margin-top: 6px; color: var(--ink); font-size: 24px; }
.hero-id p { margin-top: 6px; color: var(--muted); font-size: 13px; line-height: 1.7; }
.hero-tags { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 14px; }
.hero-tag { border: 1px solid var(--line); border-radius: 999px; background: var(--surface-raised); color: var(--body); padding: 5px 11px; font-size: 12px; }
.profile-summary { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 12px; color: var(--body); font-size: 11px; }.profile-summary span { border-left: 1px solid var(--line); padding-left: 7px; }.profile-summary span:first-child { border-left: 0; padding-left: 0; }
.hero-stats { display: grid; grid-template-columns: repeat(2, minmax(96px, 1fr)); gap: 8px; flex: 0 0 252px; }
.hero-stats .stat { min-width: 0; display: grid; gap: 4px; border: 1px solid var(--line); border-radius: 10px; background: var(--surface-raised); padding: 13px 14px; text-align: center; }
.hero-stats strong { color: var(--ink); font-size: 24px; line-height: 1; }
.hero-stats span { color: var(--muted); font-size: 11px; }

/* 能力对比与知识变化 */
.version-pill { border: 1px solid var(--line-info); border-radius: 999px; background: var(--blue2); color: var(--text-info-strong); padding: 5px 10px; font-size: 12px; font-weight: 750; }
.comparison-meta { display: grid; justify-items: end; gap: 5px; }.comparison-meta small { color: var(--muted); font-size: 10px; }.delta-up { color: var(--green) !important; }.delta-down { color: var(--red) !important; }.delta-flat { color: var(--muted) !important; }.ability-meta strong small { margin-left: 5px; font-size: 11px; }
.weak-grid-compact { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 24px; }
.weak-row { display: grid; grid-template-columns: 24px minmax(0, 1fr) auto; align-items: center; gap: 9px; min-width: 0; border-bottom: 1px solid var(--line); padding: 9px 1px; }.weak-row > div { min-width: 0; display: grid; gap: 1px; }.weak-row strong { overflow: hidden; color: var(--ink); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }.weak-row small { color: var(--muted); font-size: 10px; }
.knowledge-count { display: inline-grid; min-width: 20px; place-items: center; border-radius: 999px; background: var(--blue2); color: var(--blue); padding: 2px 7px; font-size: 11px; vertical-align: 2px; }

/* 两列网格 */
.report-grid { display: grid; grid-template-columns: 1fr; gap: 20px; align-items: start; }

/* 能力画像 */
.profile-body { display: grid; grid-template-columns: minmax(300px, 1fr) minmax(240px, .85fr); gap: 24px; align-items: center; }
.radar-wrap { min-width: 0; }
.ability-list { display: grid; gap: 16px; }
.ability-meta { display: flex; justify-content: space-between; gap: 12px; font-size: 13px; }
.ability-meta span { color: var(--muted); }
.ability-meta strong { color: var(--ink); font-size: 14px; }
.ability-track { height: 8px; margin-top: 7px; border-radius: 999px; background: var(--track); overflow: hidden; }
.ability-track i { display: block; height: 100%; border-radius: inherit; background: var(--blue); }
.ability-track.pending { background: repeating-linear-gradient(135deg, var(--track), var(--track) 6px, var(--panel) 6px, var(--panel) 12px); }

/* 画像变化 */
.profile-change-section { display: grid; gap: 0; }
.profile-change-row { display: grid; grid-template-columns: 150px minmax(220px, 1fr) minmax(220px, 1fr); gap: 20px; align-items: center; border-top: 1px solid var(--line); padding: 15px 0; }
.profile-change-row:first-of-type { border-top: 0; padding-top: 0; }
.profile-change-row:last-child { padding-bottom: 0; }
.change-version, .change-main, .change-route { display: grid; gap: 4px; min-width: 0; }
.change-version span, .change-route span { color: var(--muted); font-size: 11px; }
.change-version strong, .change-main strong { color: var(--ink); font-size: 13.5px; }
.change-main p { color: var(--body); font-size: 12.5px; }
.change-main small, .change-route small { color: var(--green); font-size: 11.5px; line-height: 1.5; }

/* 薄弱知识点 */
.weak-rank { width: 26px; height: 26px; flex-shrink: 0; display: grid; place-items: center; border-radius: 8px; background: var(--panel); color: var(--muted); font-size: 12px; font-weight: 700; }
.severity-badge { border-radius: 6px; padding: 3px 8px; font-size: 11px; font-weight: 650; }
.severity-badge.high { background: var(--red2); color: var(--red); }.severity-badge.mid { background: var(--amber2); color: var(--amber); }.severity-badge.low { background: var(--green2); color: var(--green); }
.weak-empty { display: flex; align-items: center; gap: 12px; border-radius: 12px; background: var(--green2); padding: 16px; color: var(--green); }
.weak-empty > span { width: 30px; height: 30px; display: grid; place-items: center; border-radius: 50%; background: var(--panel); font-weight: 800; }
.weak-empty p { margin-top: 4px; color: var(--text-success-strong); font-size: 11px; }

/* 学习路径 */
.path-head-meta { display: flex; align-items: center; gap: 10px; }.path-progress-text { color: var(--muted); font-size: 11px; }
.learning-path-section .card-head { margin-bottom: 16px; }
.path-visualization { display: grid; gap: 12px; }
.path-node-detail { border: 1px solid var(--line); border-radius: 10px; background: var(--soft); padding: 16px 18px; }
.path-node-detail.node-current { border-color: var(--line-info); background: var(--blue2); }.path-node-detail.node-completed { border-color: var(--line-success); background: var(--green2); }
.path-node-detail header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }.path-detail-kicker { color: var(--blue); font-size: 11px; font-weight: 750; }.path-node-detail.node-completed .path-detail-kicker { color: var(--green); }
.path-node-detail h3 { margin: 4px 0 0; color: var(--ink); font-size: 17px; line-height: 1.4; }.path-node-detail > p { max-width: 760px; margin-top: 9px; color: var(--body); font-size: 13px; line-height: 1.7; }
.path-node-detail footer { display: flex; align-items: center; justify-content: space-between; gap: 14px; margin-top: 14px; color: var(--muted); font-size: 11px; line-height: 1.5; }.path-node-detail footer > span { min-width: 0; }
.path-h { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px; }
.path-h-step { display: flex; align-items: flex-start; gap: 11px; border: 1px solid var(--line-subtle); border-radius: 12px; background: var(--soft); padding: 14px 15px; }
.path-node-copy { min-width: 0; flex: 1; }
.path-node-title { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.node-status { flex-shrink: 0; border-radius: 6px; padding: 3px 7px; background: var(--panel); color: var(--muted); font-size: 10px; }
.node-current { border-color: var(--line-info); background: var(--blue2); }
.node-current .path-node-title h3 { color: var(--text-info-strong); }
.node-current .node-status { color: var(--blue); }
.node-completed { border-color: var(--line-success); background: var(--green2); }
.node-completed .path-num { background: var(--green); }
.node-completed .node-status { color: var(--green); }
.node-locked { opacity: .72; }
.path-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.path-revision-summary { margin-bottom: 14px; border: 1px solid var(--line-warning); border-radius: 8px; background: var(--amber2); padding: 11px 13px; }
.path-revision-summary strong { color: var(--ink); font-size: 13px; }
.path-revision-summary p { margin-top: 3px; color: var(--body); font-size: 12px; line-height: 1.5; }
.node-gate-summary { display: flex; flex-wrap: wrap; align-items: center; gap: 7px 14px; margin-bottom: 14px; border-left: 3px solid var(--blue); background: var(--blue2); padding: 11px 13px; color: var(--body); font-size: 12px; }
.node-gate-summary strong { color: var(--ink); font-size: 13px; }
.adjustment-summary { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 14px; border-left: 3px solid var(--green); background: var(--green2); padding: 11px 13px; }
.adjustment-summary strong { color: var(--ink); font-size: 13px; }
.adjustment-summary p { margin-top: 3px; color: var(--body); font-size: 12px; }
.adjustment-summary .path-actions { flex-shrink: 0; margin-top: 0; }
.path-num { width: 30px; height: 30px; flex-shrink: 0; display: grid; place-items: center; border-radius: 50%; background: var(--blue); color: #fff; font-size: 13px; font-weight: 700; }
.path-h-step h3 { color: var(--ink); font-size: 13.5px; }
.path-h-step p { margin-top: 4px; color: var(--muted); font-size: 12px; line-height: 1.6; }

/* 最近资源 */
.table-wrap { width: 100%; overflow-x: auto; }
.recent-resource-table-wrap { max-height: 272px; overflow: auto; overscroll-behavior: contain; }
.resource-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.resource-table th { position: sticky; top: 0; z-index: 1; background: var(--soft); padding: 9px 12px; text-align: left; color: var(--muted); font-size: 12px; font-weight: 700; border-bottom: 1px solid var(--line); }
.resource-table td { padding: 11px 12px; border-bottom: 1px solid var(--line-subtle); color: var(--body); }
.resource-table tr:last-child td { border-bottom: 0; }
.cell-title { color: var(--ink); font-weight: 600; }

@media (max-width: 900px) {
  .profile-body { grid-template-columns: 1fr; }
}
@media (max-width: 640px) {
  .recent-resource-table-wrap { max-height: 240px; }
  .profile-change-row { grid-template-columns: 1fr; gap: 10px; }
  .adjustment-summary { align-items: flex-start; flex-direction: column; }
  .hero { flex-direction: column; align-items: flex-start; }
  .hero-stats { width: 100%; flex-basis: auto; }
  .card-head { align-items: stretch; flex-direction: column; }
  .comparison-meta { justify-items: start; }
  .path-head-meta { align-items: flex-start; flex-direction: column; }
  .path-node-detail footer { align-items: flex-start; flex-direction: column; }
  .path-h { grid-template-columns: 1fr; }
  .weak-grid-compact { grid-template-columns: 1fr; }
}
.report-page { gap: 18px; }
.card { border-radius: 10px; padding: 22px 24px; box-shadow: none; }
.section-kicker { color: var(--blue); font-size: 11px; font-weight: 750; }

/* 画像总览 */
.profile-overview { display: grid; grid-template-columns: minmax(0, 1fr) minmax(260px, .9fr) minmax(230px, .78fr); gap: 0; overflow: hidden; border: 1px solid var(--line); border-radius: 10px; background: var(--panel); }
.overview-copy,.overview-stats,.overview-action { min-width: 0; padding: 23px 24px; }
.overview-copy h2 { margin-top: 5px; color: var(--ink); font-size: 23px; line-height: 1.35; }.overview-copy > p { margin-top: 6px; color: var(--muted); font-size: 13px; line-height: 1.65; }.overview-copy > small { display: block; margin-top: 12px; color: var(--muted); font-size: 11px; }
.overview-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }.overview-tags span { border-radius: 6px; background: var(--soft); color: var(--body); padding: 4px 7px; font-size: 11px; }
.overview-stats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; border-left: 1px solid var(--line); }.overview-stats div { display: grid; align-content: center; gap: 4px; min-width: 0; }.overview-stats span,.overview-stats small { color: var(--muted); font-size: 10px; }.overview-stats strong { color: var(--ink); font-size: 22px; line-height: 1.1; }.overview-stats small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.overview-action { display: grid; align-content: center; gap: 7px; border-left: 1px solid var(--line); background: var(--blue2); }.overview-action > span { color: var(--blue); font-size: 10px; font-weight: 750; }.overview-action strong { color: var(--ink); font-size: 15px; line-height: 1.4; }.overview-action p { color: var(--body); font-size: 11px; line-height: 1.55; }.overview-action .btn { justify-self: start; margin-top: 3px; }
.overview-action.action-mistake { background: var(--amber2); }.overview-action.action-mistake > span { color: var(--amber); }.overview-action.action-resource { background: var(--green2); }.overview-action.action-resource > span { color: var(--green); }

/* 能力结构 */
.ability-profile-body { display: grid; grid-template-columns: minmax(300px, .95fr) minmax(260px, 1fr); align-items: stretch; gap: 20px; }.ability-profile-body .radar-wrap { display: grid; align-items: center; min-height: 292px; }.ability-insights { display: grid; align-content: center; gap: 9px; }.ability-insights article { position: relative; display: grid; gap: 4px; border-left: 3px solid var(--blue); background: var(--soft); padding: 13px 14px; }.ability-insights article.insight-strength { border-left-color: var(--green); }.ability-insights article.insight-focus { border-left-color: var(--amber); }.ability-insights span { color: var(--muted); font-size: 10px; }.ability-insights strong { color: var(--ink); font-size: 14px; }.ability-insights p { color: var(--body); font-size: 11px; line-height: 1.55; }
.resource-match-panel { margin-top: 18px; border-top: 1px solid var(--line); padding-top: 16px; }.resource-match-copy { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; }.resource-match-copy h3 { color: var(--ink); font-size: 14px; }.resource-match-copy p { margin-top: 3px; color: var(--muted); font-size: 11px; line-height: 1.55; }.resource-match-copy > span { flex-shrink: 0; border-radius: 6px; background: var(--amber2); color: var(--amber); padding: 4px 7px; font-size: 10px; font-weight: 700; }

/* 当前重点与学习路线 */
.knowledge-progress-section .card-head { margin-bottom: 12px; }.weak-grid-compact { column-gap: 28px; }.weak-row { padding: 10px 1px; }.path-progress-text { border-radius: 6px; background: var(--soft); padding: 5px 8px; }.learning-path-section .card-head { margin-bottom: 14px; }.path-visualization { gap: 10px; }.path-node-detail { border-radius: 8px; padding: 15px 17px; }.path-node-detail footer .btn { flex-shrink: 0; margin-top: 0; }.path-node-detail > p { margin-top: 7px; }.path-knowledge-list { margin: 10px 0; }.path-h-step { border-radius: 8px; }

/* 画像更新与资源入口 */
.profile-change-row { grid-template-columns: minmax(0, 1fr) minmax(220px, .8fr); gap: 24px; padding: 13px 0; }.change-main small,.change-route small { color: var(--muted); }.recent-resource-list { display: grid; gap: 0; }.recent-resource-list article { display: grid; grid-template-columns: 92px minmax(0, 1fr) auto; align-items: center; gap: 12px; border-top: 1px solid var(--line); padding: 11px 0; }.recent-resource-list article:first-child { border-top: 0; padding-top: 0; }.recent-resource-list article:last-child { padding-bottom: 0; }.resource-type { width: fit-content; border-radius: 6px; background: var(--soft); color: var(--blue); padding: 4px 7px; font-size: 10px; font-weight: 700; }.recent-resource-list strong { overflow: hidden; color: var(--ink); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }

@media (max-width: 1020px) { .profile-overview { grid-template-columns: 1fr 1fr; }.overview-action { grid-column: 1 / -1; border-top: 1px solid var(--line); border-left: 0; }.overview-action .btn { justify-self: start; } }
@media (max-width: 720px) { .profile-overview,.ability-profile-body { grid-template-columns: 1fr; }.overview-stats { border-top: 1px solid var(--line); border-left: 0; }.overview-action { grid-column: auto; }.card { padding: 18px; }.ability-profile-body .radar-wrap { min-height: 250px; }.resource-match-copy { display: grid; gap: 8px; }.resource-match-copy > span { justify-self: start; }.profile-change-row { grid-template-columns: 1fr; gap: 9px; }.recent-resource-list article { grid-template-columns: minmax(0, 1fr) auto; }.resource-type { display: none; } }
@media (max-width: 480px) { .overview-copy,.overview-stats,.overview-action { padding: 18px; }.overview-stats strong { font-size: 20px; }.overview-action .btn { width: 100%; min-height: 40px; }.path-node-detail footer { align-items: stretch; }.path-node-detail footer .btn { width: 100%; }.card-head { gap: 10px; } }
</style>
