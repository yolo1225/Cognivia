<template>
  <section class="page report-page">
    <PageHeader title="学习报告" description="能力画像、学习资源与推荐路径，一份报告看清当前水平和下一步学习安排。">
      <template #actions>
        <span class="learner-tag">学习者 {{ learnerId || '-' }}</span>
        <button type="button" class="btn" :disabled="loading" :aria-busy="loading" @click="loadReport">{{ loading ? '正在刷新' : '刷新报告' }}</button>
      </template>
    </PageHeader>

    <PageState v-if="loading" type="loading" title="正在加载学习报告" />

    <div v-else-if="errorMessage" class="error-state"><strong>报告加载失败</strong><p>{{ errorMessage }}</p><button class="btn" @click="loadReport">重新加载</button></div>

    <div v-else-if="!report" class="card empty-state">
      <div class="empty-icon"><AppIcon name="report" /></div>
      <h2>尚未生成学习报告</h2>
      <p>请先在首页完成学习背景建档和首次能力诊断，系统将据此生成能力画像与学习路线。</p>
      <button class="btn primary" @click="router.push('/dashboard')">返回首页</button>
    </div>

    <template v-else>
      <!-- 画像身份卡 -->
      <header class="hero">
        <div class="hero-id">
          <span class="hero-kicker">个性化能力画像</span>
          <h2>{{ profileTypeLabel(report.profile_type) }}</h2>
          <p>基于诊断测评生成的能力画像，用于个性化资源生成与学习路径推荐。</p>
          <div class="hero-tags">
            <span v-for="d in directionList" :key="d" class="hero-tag">{{ d }}</span>
            <span class="hero-tag">{{ contextSnapshot.education_level || '未填写' }} · {{ contextSnapshot.major || '未填写专业' }}</span>
            <span v-if="contextSnapshot.experience_years != null" class="hero-tag">{{ contextSnapshot.experience_years }} 年经验</span>
          </div>
        </div>
        <div class="hero-stats">
          <div class="stat"><strong>{{ diagnosticTotalScore }}%</strong><span>诊断总得分</span><small>{{ diagnosticCorrectCount }}/{{ diagnosticAnswerCount }} 题完全答对</small></div>
          <div class="stat"><strong>{{ percentOrEmpty(progress?.mistake_consolidation?.consolidation_rate) }}</strong><span>错题巩固率</span></div>
          <div class="stat"><strong>{{ percentOrEmpty(progress?.path_progress?.completion_rate) }}</strong><span>路径完成率</span></div>
          <div class="stat"><strong>{{ resourceTotal }}</strong><span>已通过资源</span></div>
        </div>
      </header>

      <!-- 能力画像 -->
      <div class="report-grid">
        <section class="card">
          <div class="card-head">
            <div><h2>能力证据画像</h2><p class="section-note">只展示当前证据可支持的能力项；学习速度需多轮行为证据后另行判断</p></div>
            <div v-if="progress?.available" class="comparison-meta"><span class="version-pill">V{{ progress.baseline?.profile_version }} → V{{ progress.current?.profile_version }}</span><small>{{ formatDate(progress.period?.started_at) }} 至 {{ formatDate(progress.period?.updated_at) }}</small></div>
          </div>
          <div class="profile-body">
            <div class="radar-wrap"><RadarChart :values="abilityValues" :baseline-values="baselineAbilityValues" :indicators="abilityLabels" /></div>
            <div class="ability-list">
              <div v-for="item in abilityRows" :key="item.label" class="ability-row">
                <div class="ability-meta"><span>{{ item.label }}</span><strong>{{ item.value }} <small v-if="item.delta != null" :class="deltaTone(item.delta)">{{ signed(item.delta) }}</small></strong></div>
                <div class="ability-track"><i :style="{ width: `${item.value}%` }"></i></div>
              </div>
            </div>
          </div>
        </section>

      </div>

      <!-- 学习路径：放在能力画像后，优先回答“下一步学什么” -->
      <section class="card learning-path-section">
        <div class="card-head">
          <div><h2>推荐学习路径</h2><p class="section-note">基于当前能力画像和知识状态生成，先完成当前节点</p></div>
          <div class="path-head-meta"><span class="path-progress-text">已完成 {{ progress?.path_progress?.completed ?? 0 }} / {{ progress?.path_progress?.total ?? pathNodes.length }} 个节点</span><span class="status" :class="report.feedback_summary?.learning_path_needs_refresh ? 'wait' : 'ok'">{{ report.feedback_summary?.learning_path_needs_refresh ? '待刷新' : '当前版本' }}</span></div>
        </div>
        <div v-if="report.learning_path?.revision_summary" class="path-revision-summary"><strong>路线已调整</strong><p>{{ report.learning_path.revision_summary.message }}，请先完成新的当前节点。</p></div>
        <div v-for="proposal in report.learning_adjustments || []" :key="proposal.proposal_id" class="adjustment-summary">
          <div><strong>画像与路线已更新</strong><p>{{ proposal.decision === 'confirmed_mastery' ? '已确认掌握并推进到下一节点。' : '已确认需要补强，当前节点保持不变。' }}</p></div>
          <div class="path-actions"><button class="btn primary" :disabled="adjustmentSubmitting === proposal.proposal_id" @click="decideReportAdjustment(proposal.proposal_id, 'generate')">生成新资源</button><button class="btn" :disabled="adjustmentSubmitting === proposal.proposal_id" @click="decideReportAdjustment(proposal.proposal_id, 'skip')">暂不生成</button></div>
        </div>
        <div v-if="pathNodes.length" class="path-h">
          <div v-for="(node, index) in pathNodes" :key="node.path_node_id" class="path-h-step" :class="`node-${node.status}`">
            <span class="path-num">{{ index + 1 }}</span>
            <div class="path-node-copy">
              <div class="path-node-title"><h3>{{ node.title }}</h3><span class="node-status">{{ pathStatusLabel(node.status) }}</span></div>
              <p>{{ node.learning_objective }}</p>
              <p class="path-node-reason">{{ node.recommendation_reason }}</p>
              <div class="path-knowledge-list">
                <span v-for="knowledgeId in node.knowledge_ids" :key="knowledgeId" :class="{ focus: node.focus_knowledge_ids.includes(knowledgeId) }">
                  {{ knowledgeLabel(node, knowledgeId) }}<small v-if="node.focus_knowledge_ids.includes(knowledgeId)">重点</small>
                </span>
              </div>
              <p>单元验证 {{ Math.round(node.completion_condition.threshold * 100) }}%<template v-if="node.completion_condition.focus_threshold"> · 重点知识不低于 {{ Math.round(node.completion_condition.focus_threshold * 100) }}%</template></p>
              <div v-if="node.status === 'current'" class="path-actions"><button v-if="node.resource_state === 'ready'" class="btn primary" @click="openNodeResource(node)">继续当前学习</button><button v-else-if="node.resource_state === 'generating'" class="btn primary" @click="openNodeResource(node)">查看生成进度</button><button v-else class="btn primary" :disabled="creatingGeneration" @click="generateNodeResources(node)">{{ creatingGeneration ? '正在创建...' : node.resource_state === 'failed' ? '重新生成本节点资源' : '生成本节点资源' }}</button></div>
            </div>
          </div>
          <div class="ability-evidence"><span>诊断得分权重 {{ Math.round(Number(evidenceProfile.diagnostic_weight || 0) * 100) }}%</span><span>学习背景先验 {{ Math.round(Number(evidenceProfile.background_weight || 0) * 100) }}%</span><span>已测 {{ evidenceProfile.assessed_knowledge_count || 0 }} 个知识点</span><span>评分置信度 {{ Math.round(Number(evidenceProfile.mean_scoring_confidence || 0) * 100) }}%</span></div>
        </div>
        <div v-else-if="report.path_detail?.length" class="path-h"><div v-for="(stage, index) in report.path_detail" :key="index" class="path-h-step"><span class="path-num">{{ index + 1 }}</span><div><h3>{{ stage.name }}</h3><p>{{ stage.description || '根据当前画像推荐' }}</p></div></div></div>
        <div v-else class="empty-hint">尚未形成可展示的学习路径。</div>
      </section>

      <section class="card knowledge-progress-section">
        <div class="card-head">
          <div><h2>知识掌握</h2><p class="section-note">查看当前优先项，或回顾经正式证据确认的状态变化</p></div>
          <button type="button" class="btn" @click="router.push({ path: '/mistake-review', query: { learner_id: learnerId } })">进入错题巩固</button>
        </div>
        <div class="knowledge-toolbar">
          <div class="knowledge-tabs" role="tablist" aria-label="知识掌握视图">
            <button type="button" role="tab" :aria-selected="knowledgeView === 'weak'" :class="{ active: knowledgeView === 'weak' }" @click="knowledgeView = 'weak'">当前待加强 <span>{{ sortedWeakKnowledge.length }}</span></button>
            <button type="button" role="tab" :aria-selected="knowledgeView === 'changes'" :class="{ active: knowledgeView === 'changes' }" @click="knowledgeView = 'changes'">画像变化 <span>{{ knowledgeChangeTotal }}</span></button>
          </div>
          <span v-if="progress?.mistake_consolidation" class="consolidation-note">错题验证通过 {{ progress.mistake_consolidation.consolidated ?? 0 }} 道</span>
        </div>
        <div v-if="knowledgeView === 'weak'" class="knowledge-panel" role="tabpanel">
          <div v-if="displayedWeakKnowledge.length" class="weak-grid-compact">
            <article v-for="(item, index) in displayedWeakKnowledge" :key="item.knowledge_id" class="weak-row">
              <span class="weak-rank">{{ index + 1 }}</span><div><strong>{{ item.name }}</strong><small>{{ item.category }}</small></div><span class="severity-badge" :class="severityLevel(item.weakness_level)">{{ weaknessLabel(item.weakness_level) }}</span>
            </article>
          </div>
          <div v-else class="weak-empty"><span aria-hidden="true">✓</span><div><strong>当前没有已确认的薄弱知识点</strong><p>后续证据会持续更新这一结果。</p></div></div>
          <button v-if="sortedWeakKnowledge.length > 6" type="button" class="knowledge-more" @click="showAllWeakKnowledge = !showAllWeakKnowledge">{{ showAllWeakKnowledge ? '收起其余项目' : `查看其余 ${sortedWeakKnowledge.length - 6} 项` }}</button>
        </div>
        <div v-else class="knowledge-panel" role="tabpanel">
          <div v-if="knowledgeChangeTotal" class="change-columns">
            <section v-for="group in knowledgeGroups" :key="group.key" class="change-column" :class="`group-${group.key}`">
              <header><strong>{{ group.label }}</strong><span>{{ group.items.length }}</span></header>
              <ul><li v-for="item in group.items.slice(0, 4)" :key="item.knowledge_id"><span>{{ item.name }}</span><small v-if="item.before_level != null">{{ item.before_level }} → {{ item.after_level }}</small></li></ul>
              <small v-if="group.items.length > 4" class="more-count">还有 {{ group.items.length - 4 }} 项</small>
              <p v-if="!group.items.length">暂无变化</p>
            </section>
          </div>
          <div v-else class="knowledge-empty">尚无经正式证据确认的知识状态变化。</div>
        </div>
      </section>

      <section v-if="profileChanges.length" class="card profile-change-section">
        <div class="card-head">
          <div><h2>本次画像变化</h2><p class="section-note">由交互反馈与正式微验证共同确认</p></div>
        </div>
        <article v-for="change in profileChanges" :key="change.proposal_id" class="profile-change-row">
          <div class="change-version">
            <span>画像版本</span>
            <strong>V{{ change.profile_change_summary.original_profile_version }} → V{{ change.profile_change_summary.resulting_profile_version }}</strong>
          </div>
          <div class="change-main">
            <strong>{{ change.profile_change_summary.knowledge_name }}</strong>
            <p>{{ knowledgeStateLabel(change.profile_change_summary.before_state) }} → {{ knowledgeStateLabel(change.profile_change_summary.after_state) }}</p>
            <small v-if="change.profile_change_summary.removed_from_weak_knowledge">已从薄弱知识点移除</small>
            <small v-if="change.profile_change_summary.removed_from_blind_spots">已从知识盲点移除</small>
          </div>
          <div class="change-route">
            <span>{{ change.profile_change_summary.ability_summary }}</span>
            <small v-if="change.profile_change_summary.completed_node_id">已完成当前节点，路线推进至 {{ nodeTitle(change.profile_change_summary.current_node_id) }}</small>
            <small v-else>路线保持在当前节点</small>
          </div>
        </article>
      </section>

      <section v-if="learningHistory.length" class="card evidence-timeline">
        <div class="card-head"><div><h2>学习历程</h2><p class="section-note">记录诊断、导学反馈、掌握验证、路径推进与反馈驱动资源任务</p></div></div>
          <ol><li v-for="event in learningHistory" :key="event.event_id"><time>{{ formatDate(event.occurred_at) }}</time><div><strong>{{ event.title }}</strong><p>{{ event.reason || '已记录本次学习事件。' }}</p><small><template v-if="event.profile_version != null">画像 V{{ event.profile_version }}</template><template v-if="event.path_node_id"> · {{ nodeTitle(event.path_node_id) }}</template><template v-if="event.evidence_refs?.length"> · {{ formatEvidenceRefs(event.evidence_refs) }}</template></small></div></li></ol>
      </section>

      <!-- 最近资源 -->
      <section v-if="report.resource_summary?.recent?.length" class="card">
          <div class="card-head"><div><h2>最近资源</h2><p class="section-note">已通过自动质量校验的个性化学习资源</p></div></div>
        <div class="table-wrap recent-resource-table-wrap" tabindex="0" aria-label="最近资源列表">
          <table class="resource-table">
            <thead><tr><th>资源</th><th>类型</th><th>难度</th><th>质量状态</th><th>来源</th></tr></thead>
            <tbody>
              <tr v-for="r in report.resource_summary.recent" :key="r.resource_id">
                <td class="cell-title">{{ r.title }}</td>
                <td><span class="tag">{{ r.resource_type_label || r.resource_type }}</span></td>
                <td>{{ r.difficulty }}/5</td>
                <td><span class="status" :class="resourceQualityStatusTone(r.review_status)">{{ resourceQualityStatusLabel(r.review_status) }}</span></td>
                <td>{{ r.source_count }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getLearningReport, type LearningReport } from '@/api/reports'
import type { LearningPathNode } from '@/api/learningPaths'
import { decideLearningAdjustmentResource } from '@/api/learningAdjustments'
import { useToast } from '@/composables/useToast'
import { resourceQualityStatusLabel, resourceQualityStatusTone } from '@/utils/resourceQualityStatus'
import { createGenerationTask } from '@/api/generation'
import RadarChart from '@/components/Charts/RadarChart.vue'
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
const knowledgeView = ref<'weak' | 'changes'>('weak')
const showAllWeakKnowledge = ref(false)

const abilityLabels = ['理论掌握', '实操应用', '场景解决']
const DIRECTION_LABELS: Record<string, string> = {
  llm_application: '大模型应用开发',
  prompt_engineering: 'Prompt 工程',
  rag_knowledge_base: 'RAG 知识库构建',
  agent_orchestration: 'Agent 编排',
}

const progress = computed(() => report.value?.progress_comparison)
const learningHistory = computed(() => report.value?.learning_history || [])
const abilityValues = computed(() => (report.value?.radar || []).slice(0, 3))
const baselineAbilityValues = computed(() => progress.value?.baseline?.radar?.slice(0, 3))
const evidenceProfile = computed<Record<string, any>>(() => report.value?.ability_profile?.evidence_profile || {})
const abilityRows = computed(() => abilityLabels.map((label, index) => ({
  label,
  value: Math.max(0, Math.min(100, Number(report.value?.radar?.[index] || 0))),
  delta: progress.value?.ability_changes?.[index]?.delta,
})))
const sortedWeakKnowledge = computed(() => [...(report.value?.weak_knowledge || [])].sort((a, b) => b.weakness_level - a.weakness_level))
const displayedWeakKnowledge = computed(() => showAllWeakKnowledge.value ? sortedWeakKnowledge.value : sortedWeakKnowledge.value.slice(0, 6))
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
const resourceTotal = computed(() => report.value?.resource_summary?.total || 0)
const pathNodes = computed<LearningPathNode[]>(() => report.value?.learning_path?.nodes || [])
function formatEvidenceRefs(refs: unknown[]) { return `已记录 ${refs.length} 条正式证据` }
const profileChanges = computed(() => report.value?.profile_changes || [])
const knowledgeGroups = computed(() => {
  const changes = progress.value?.knowledge_changes
  return [
    { key: 'consolidated', label: '确认掌握', items: changes?.consolidated || [] },
    { key: 'improving', label: '正在提升', items: changes?.improving || [] },
    { key: 'new_weakness', label: '新增待加强', items: changes?.new_weakness || [] },
  ]
})
const knowledgeChangeTotal = computed(() => knowledgeGroups.value.reduce((total, group) => total + group.items.length, 0))

function signed(value?: number | null) { const number = Number(value || 0); return `${number > 0 ? '+' : ''}${number.toFixed(1)}` }
function deltaTone(value?: number | null) { return Number(value || 0) > 0 ? 'delta-up' : Number(value || 0) < 0 ? 'delta-down' : 'delta-flat' }
function percentOrEmpty(value?: number | null) { return value == null ? '暂无' : `${Math.round(value)}%` }
function formatDate(value?: string | null) { return value ? new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: 'numeric', day: 'numeric' }).format(new Date(value)) : '待确认' }
function governanceLabel(status: string) { return ({ pending: '等待独立证据', conflicted: '证据冲突', consumed: '已被画像消费', no_change: '画像保持不变', rejected: '证据未采用' } as Record<string, string>)[status] || status }

function pathStatusLabel(status: LearningPathNode['status']) {
  return ({ locked: '未解锁', current: '当前学习', completed: '已完成', skipped: '已跳过' } as const)[status]
}

function knowledgeStateLabel(state: string) {
  return ({
    unmastered: '未掌握',
    confused: '易混淆',
    partial_mastery: '部分掌握',
    known: '已掌握',
    not_weak: '非薄弱项',
  } as Record<string, string>)[state] || state
}

function nodeTitle(nodeId?: string | null) {
  if (!nodeId) return '路线完成'
  return pathNodes.value.find(node => node.path_node_id === nodeId)?.title || nodeId
}
function knowledgeLabel(node: LearningPathNode, knowledgeId: string) {
  return node.knowledge_items?.find(item => item.knowledge_id === knowledgeId)?.name || knowledgeId
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

async function loadReport() {
  if (!learnerId.value) {
    report.value = null
    errorMessage.value = '当前账号未关联有效学习者，请重新登录或联系管理员。'
    return
  }
  loading.value = true
  errorMessage.value = ''
  try {
    const data = await getLearningReport(learnerId.value, taskId.value || undefined)
    report.value = data.profile_ready ? data : null
    if (report.value?.domain_code) await domainStore.initialize(report.value.domain_code)
  } catch { report.value = null; errorMessage.value = '无法读取学习报告，请确认后端服务可用。' }
  finally { loading.value = false }
}

watch(() => [route.query.learner_id, route.query.task_id], () => {
  loadReport()
})
onMounted(() => {
  loadReport()
  window.addEventListener('focus', loadReport)
})
onBeforeUnmount(() => window.removeEventListener('focus', loadReport))
</script>

<style scoped>
.report-page { gap: 20px; max-width: 1080px; margin: 0 auto; }
.path-node-reason { color: var(--text-secondary); }
.path-knowledge-list { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0; }
.path-knowledge-list > span { border: 1px solid var(--line); border-radius: 6px; padding: 4px 7px; background: var(--panel-muted); font-size: 12px; }
.path-knowledge-list > span.focus { border-color: var(--warning); background: var(--warning-soft); }
.path-knowledge-list small { margin-left: 5px; color: var(--warning-strong); }

/* 通用卡片 */
.card { border: 1px solid var(--line); border-radius: 16px; background: var(--panel); padding: 24px 26px; box-shadow: 0 1px 2px rgb(16 24 40 / .03); }
.card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 18px; }
.card-head h2 { color: var(--ink); font-size: 17px; }
.section-note { margin-top: 4px; color: var(--muted); font-size: 12px; line-height: 1.5; }
.empty-state { display: grid; justify-items: center; gap: 8px; padding: 48px 32px; text-align: center; }
.empty-icon { font-size: 40px; }
.empty-state h2 { color: var(--ink); font-size: 18px; }
.empty-state p { max-width: 420px; color: var(--muted); font-size: 13px; line-height: 1.7; }
.empty-state .btn { margin-top: 12px; }

/* Hero 身份卡 */
.hero { display: flex; align-items: center; justify-content: space-between; gap: 24px; border: 1px solid #e2e8f2; border-radius: 16px; padding: 26px 28px; background: linear-gradient(135deg, #eef3ff 0%, #f8fafc 55%, #eef8f3 100%); }
.hero-kicker { color: var(--blue); font-size: 12px; font-weight: 750; }
.hero-id h2 { margin-top: 6px; color: var(--ink); font-size: 24px; }
.hero-id p { margin-top: 6px; color: var(--muted); font-size: 13px; line-height: 1.7; }
.hero-tags { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 14px; }
.hero-tag { border: 1px solid #dbe4f0; border-radius: 999px; background: rgb(255 255 255 / .7); color: var(--body); padding: 5px 11px; font-size: 12px; }
.hero-stats { display: grid; grid-template-columns: repeat(2, minmax(96px, 1fr)); gap: 8px; flex: 0 0 252px; }
.hero-stats .stat { min-width: 0; display: grid; gap: 4px; border: 1px solid rgb(255 255 255 / .8); border-radius: 10px; background: rgb(255 255 255 / .75); padding: 13px 14px; text-align: center; }
.hero-stats strong { color: var(--ink); font-size: 24px; line-height: 1; }
.hero-stats span { color: var(--muted); font-size: 11px; }

/* 能力对比与知识变化 */
.version-pill { border: 1px solid #cddaff; border-radius: 999px; background: var(--blue2); color: #244eae; padding: 5px 10px; font-size: 12px; font-weight: 750; }
.comparison-meta { display: grid; justify-items: end; gap: 5px; }.comparison-meta small { color: var(--muted); font-size: 10px; }.delta-up { color: var(--green) !important; }.delta-down { color: var(--red) !important; }.delta-flat { color: var(--muted) !important; }.ability-meta strong small { margin-left: 5px; font-size: 11px; }
.knowledge-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin: -2px 0 14px; border-bottom: 1px solid var(--line); }
.knowledge-tabs { display: flex; gap: 22px; }
.knowledge-tabs button { min-height: 39px; display: inline-flex; align-items: center; gap: 7px; border: 0; border-bottom: 2px solid transparent; background: transparent; color: var(--muted); padding: 0 2px; font-size: 12px; font-weight: 680; }
.knowledge-tabs button:hover { color: var(--ink); }.knowledge-tabs button.active { border-bottom-color: var(--blue); color: var(--blue); }
.knowledge-tabs button span { min-width: 20px; border-radius: 999px; background: var(--soft); color: inherit; padding: 1px 6px; font-size: 10px; text-align: center; }
.consolidation-note { color: var(--green); font-size: 11px; font-weight: 650; }
.knowledge-panel { min-height: 128px; }
.weak-grid-compact { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 24px; }
.weak-row { display: grid; grid-template-columns: 24px minmax(0, 1fr) auto; align-items: center; gap: 9px; min-width: 0; border-bottom: 1px solid var(--line); padding: 9px 1px; }.weak-row > div { min-width: 0; display: grid; gap: 1px; }.weak-row strong { overflow: hidden; color: var(--ink); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }.weak-row small { color: var(--muted); font-size: 10px; }
.knowledge-more { width: 100%; min-height: 32px; margin-top: 8px; border: 0; border-radius: 7px; background: var(--soft); color: var(--blue); font-size: 11px; font-weight: 680; }.knowledge-more:hover { background: var(--blue2); }
.change-columns { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.change-column { min-width: 0; border-radius: 9px; background: var(--soft); padding: 12px; }.change-column header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }.change-column header strong { font-size: 12px; }.change-column header span { color: var(--muted); font-size: 11px; }.change-column ul { display: grid; gap: 4px; margin: 9px 0 0; padding: 0; list-style: none; }.change-column li { display: flex; justify-content: space-between; gap: 7px; color: var(--body); font-size: 11px; }.change-column li span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.change-column li small,.more-count,.change-column > p { flex-shrink: 0; color: var(--muted); font-size: 10px; }.more-count { display: block; margin-top: 6px; }.change-column > p { margin-top: 9px; }
.change-column.group-consolidated header strong { color: var(--green); }.change-column.group-improving header strong { color: var(--blue); }.change-column.group-new_weakness header strong { color: var(--red); }
.knowledge-empty { display: grid; min-height: 128px; place-items: center; color: var(--muted); font-size: 12px; text-align: center; }
.evidence-timeline ol { display: grid; gap: 0; margin: 0; padding: 0; list-style: none; }.evidence-timeline li { display: grid; grid-template-columns: 108px 18px minmax(0, 1fr); gap: 10px; padding: 0 0 18px; }.evidence-timeline li::before { content: ''; grid-column: 2; grid-row: 1; width: 10px; height: 10px; margin-top: 5px; border: 3px solid var(--blue); border-radius: 50%; background: var(--panel); }.evidence-timeline li:not(:last-child)::after { content: ''; grid-column: 2; grid-row: 1; width: 1px; height: calc(100% + 8px); margin: 15px 0 0 5px; background: var(--line); }.evidence-timeline time { grid-column: 1; grid-row: 1; color: var(--muted); font-size: 11px; }.evidence-timeline li > div { grid-column: 3; grid-row: 1; min-width: 0; }.evidence-timeline strong { font-size: 13px; }.evidence-timeline p { margin-top: 3px; color: var(--body); font-size: 12px; }.evidence-timeline small { display: block; margin-top: 4px; color: var(--muted); font-size: 10px; overflow-wrap: anywhere; }

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
.ability-track i { display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg, #6a8bc0, var(--blue)); }

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
.weak-empty p { margin-top: 4px; color: #3f735f; font-size: 11px; }

/* 学习路径 */
.path-head-meta { display: flex; align-items: center; gap: 10px; }.path-progress-text { color: var(--muted); font-size: 11px; }
.learning-path-section .card-head { margin-bottom: 16px; }
.path-h { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px; }
.path-h-step { display: flex; align-items: flex-start; gap: 11px; border: 1px solid #edf1f6; border-radius: 12px; background: var(--soft); padding: 14px 15px; }
.path-node-copy { min-width: 0; flex: 1; }
.path-node-title { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.node-status { flex-shrink: 0; border-radius: 6px; padding: 3px 7px; background: var(--panel); color: var(--muted); font-size: 10px; }
.node-current { border-color: #8fa9dc; background: var(--blue2); }
.node-current .path-node-title h3 { color: #244eae; }
.node-current .node-status { color: var(--blue); }
.node-completed { border-color: #cfe7d8; background: var(--green2); }
.node-completed .path-num { background: var(--green); }
.node-completed .node-status { color: var(--green); }
.node-locked { opacity: .72; }
.path-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.path-revision-summary { margin-bottom: 14px; border: 1px solid #efd29f; border-radius: 8px; background: var(--amber2); padding: 11px 13px; }
.path-revision-summary strong { color: var(--ink); font-size: 13px; }
.path-revision-summary p { margin-top: 3px; color: var(--body); font-size: 12px; line-height: 1.5; }
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
.resource-table td { padding: 11px 12px; border-bottom: 1px solid #edf0f4; color: var(--body); }
.resource-table tr:last-child td { border-bottom: 0; }
.cell-title { color: var(--ink); font-weight: 600; }

@media (max-width: 900px) {
  .profile-body { grid-template-columns: 1fr; }
  .change-columns { grid-template-columns: 1fr; }
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
  .path-h { grid-template-columns: 1fr; }
  .knowledge-toolbar { align-items: flex-start; flex-direction: column-reverse; gap: 2px; }
  .knowledge-tabs { width: 100%; gap: 10px; }.knowledge-tabs button { flex: 1; justify-content: center; }
  .weak-grid-compact { grid-template-columns: 1fr; }
  .evidence-timeline li { grid-template-columns: 74px 14px minmax(0, 1fr); gap: 7px; }
}
.ability-evidence { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 16px; border-top: 1px solid var(--line); padding-top: 13px; }
.ability-evidence span { border-radius: 999px; background: var(--soft); color: var(--muted); padding: 5px 9px; font-size: 10px; }
</style>
