<template>
  <section class="page mistake-page">
    <PageHeader title="错题巩固" description="优先解决当前学习节点的阻断性错题，也可以提前巩固后续节点知识。">
      <template #meta><span v-if="learnerId" class="context-label">当前学习者：{{ learnerId }}</span></template>
      <template #actions><button type="button" class="btn" :disabled="loading" @click="() => loadAll()"><AppIcon name="history" />{{ loading ? '正在刷新' : '刷新记录' }}</button></template>
    </PageHeader>

    <PageState v-if="loading && !summary" type="loading" title="正在整理错题" />
    <PageState v-else-if="errorMessage" type="error" title="错题加载失败" :description="errorMessage"><button type="button" class="btn" @click="() => loadAll()">重新加载</button></PageState>

    <template v-else>
      <section class="priority-strip" :class="{ complete: !summary?.current_priority_count }" aria-label="当前节点错题任务">
        <div class="priority-copy">
          <span class="priority-kicker">当前学习节点</span>
          <h2>{{ summary?.current_node?.title || '学习路径尚未就绪' }}</h2>
          <p>{{ focusTip }}</p>
        </div>
        <div class="priority-count"><strong>{{ summary?.current_priority_count ?? 0 }}</strong><span>当前必做</span></div>
        <div class="progress-summary">
          <div><span>总体巩固进度</span><strong>{{ overallProgress }}%</strong></div>
          <div class="progress-track" role="progressbar" aria-label="错题巩固进度" :aria-valuenow="overallProgress" aria-valuemin="0" aria-valuemax="100"><i :style="{ width: `${overallProgress}%` }" /></div>
          <small>已巩固 {{ summary?.consolidated ?? 0 }} / {{ summary?.total ?? 0 }} 道</small>
        </div>
        <dl class="status-summary"><div><dt>待巩固</dt><dd>{{ summary?.pending ?? 0 }}</dd></div><div><dt>巩固中</dt><dd>{{ summary?.in_progress ?? 0 }}</dd></div><div><dt>已巩固</dt><dd>{{ summary?.consolidated ?? 0 }}</dd></div></dl>
      </section>

      <section class="filter-bar" aria-label="筛选错题">
        <div class="scope-tabs" role="tablist" aria-label="错题处理范围">
          <button type="button" role="tab" :aria-selected="filters.priorityScope === 'current_node'" :class="{ active: filters.priorityScope === 'current_node' }" @click="setPriorityScope('current_node')">当前必做 <span>{{ summary?.current_priority_count ?? 0 }}</span></button>
          <button type="button" role="tab" :aria-selected="filters.priorityScope === 'all'" :class="{ active: filters.priorityScope === 'all' }" @click="setPriorityScope('all')">全部错题 <span>{{ summary?.total ?? 0 }}</span></button>
        </div>
        <div class="filter-controls">
          <div class="source-tabs" aria-label="错题来源"><button v-for="option in sourceOptions" :key="option.value" type="button" :class="{ active: filters.sourceType === option.value }" :aria-pressed="filters.sourceType === option.value" @click="filters.sourceType = option.value">{{ option.label }}</button></div>
          <label><span>状态</span><select v-model="filters.status"><option value="">全部状态</option><option value="pending">待巩固</option><option value="reviewing">巩固中</option><option value="verification_pending">需要确认</option><option value="needs_more_practice">继续练习</option><option value="consolidated">已巩固</option></select></label>
          <label><span>难度</span><select v-model="filters.difficulty"><option value="">全部难度</option><option v-for="level in 5" :key="level" :value="String(level)">难度 {{ level }}</option></select></label>
          <button v-if="hasActiveFilters" type="button" class="btn text small" @click="resetFilters">清除条件</button>
          <small class="result-count">{{ totalItems }} 条结果</small>
        </div>
      </section>

      <PageState v-if="!items.length" type="empty" :title="emptyTitle" :description="emptyDescription"><button v-if="filters.priorityScope === 'current_node' && (summary?.total || 0) > 0" type="button" class="btn" @click="setPriorityScope('all')">查看全部错题</button></PageState>
      <div v-else class="mistake-layout">
        <section class="mistake-list" aria-label="错题队列">
          <header><div><strong>{{ filters.priorityScope === 'current_node' ? '当前节点必做' : '全部错题' }}</strong><span>{{ filters.priorityScope === 'current_node' ? '完成这些题后才能满足当前节点门禁' : '当前必做优先排列，后续节点也可提前练习' }}</span></div><small>{{ totalItems }} 道</small></header>
          <article v-for="item in items" :key="item.item_id" class="mistake-row" :class="{ selected: selected?.item_id === item.item_id, priority: item.is_current_priority }">
            <button type="button" class="mistake-main" @click="selectItem(item)">
              <span class="path-badge" :class="pathTone(item)">{{ pathLabel(item) }}</span>
              <span class="mistake-title"><strong>{{ formatKnowledgeName(item.knowledge_name) }}</strong><span class="status" :class="statusTone(item.status)">{{ statusLabel(item.status) }}</span></span>
              <span class="mistake-reason">{{ item.error_summary }}</span>
              <span class="mistake-meta">{{ sourceLabel(item.source_type) }} · {{ typeLabel(item.question_type) }} · 难度 {{ item.difficulty }}<template v-if="item.last_score != null"> · 得分 {{ Math.round(item.last_score * 100) }}</template></span>
            </button>
            <button v-if="item.status !== 'consolidated'" type="button" class="btn primary small row-primary" :disabled="startingId === item.item_id" @click="begin(item)">{{ startingId === item.item_id ? '正在准备' : '开始巩固' }}</button>
          </article>
          <nav v-if="totalPages > 1" class="pagination" aria-label="错题分页"><button type="button" class="btn small" :disabled="currentPage <= 1 || loading" @click="changePage(currentPage - 1)">上一页</button><span>第 {{ currentPage }} / {{ totalPages }} 页</span><button type="button" class="btn small" :disabled="currentPage >= totalPages || loading" @click="changePage(currentPage + 1)">下一页</button></nav>
        </section>

        <aside class="review-panel" :class="{ 'has-selection': selected }" aria-live="polite">
          <div v-if="!selected" class="review-empty"><AppIcon name="check" /><h2>从左侧选择一道错题</h2><p>查看原题解析、完成同知识点验证，或使用 AI 导学继续理解。</p></div>
          <template v-else>
            <header class="review-head"><div><span class="path-badge" :class="pathTone(selected)">{{ pathLabel(selected) }}</span><h2>{{ formatKnowledgeName(selected.knowledge_name) }}</h2><p>{{ sourceLabel(selected.source_type) }} · {{ typeLabel(selected.question_type) }} · 难度 {{ selected.difficulty }}</p></div><div class="review-head-actions"><button type="button" class="btn small tutor-trigger" @click="openMistakeTutor"><AppIcon name="sparkles" />AI 导学</button><span class="status" :class="statusTone(selected.status)">{{ statusLabel(selected.status) }}</span><button type="button" class="panel-close" aria-label="关闭详情" @click="selected = null"><span aria-hidden="true">×</span></button></div></header>
            <nav class="detail-tabs" role="tablist" aria-label="错题详情视图"><button v-for="tab in detailTabs" :key="tab.value" type="button" role="tab" :aria-selected="detailTab === tab.value" :class="{ active: detailTab === tab.value }" @click="detailTab = tab.value">{{ tab.label }}<span v-if="tab.value === 'history' && selected.attempts?.length">{{ selected.attempts.length }}</span></button></nav>

            <div v-if="detailTab === 'analysis'" class="detail-pane" role="tabpanel">
              <section class="detail-section"><span class="section-label">错误原因</span><p>{{ selected.scoring_comment || selected.error_summary }}</p></section>
              <section v-if="selected.question" class="detail-section"><span class="section-label">原题回顾</span><p class="question-stem">{{ selected.question.stem }}</p><ol v-if="selected.question.options?.length"><li v-for="option in selected.question.options" :key="option">{{ option }}</li></ol><p v-else class="question-type-note">该题为{{ typeLabel(selected.question_type) }}，没有选项。</p></section>
              <section v-if="selected.recommended_resource" class="resource-link"><div><span class="section-label">关联学习资源</span><strong>{{ selected.recommended_resource.title }}</strong></div><button type="button" class="btn" @click="openResource(selected)">打开资源</button></section>
            </div>

            <div v-else-if="detailTab === 'assessment'" class="detail-pane" role="tabpanel">
              <div v-if="!activeAttempt" class="pane-empty"><AppIcon name="check" /><h3>尚未开始巩固</h3><p>开始后，系统将从正式题库中选择一道同知识点新题，提交结果会作为正式学习证据。</p><button v-if="selected.status !== 'consolidated'" type="button" class="btn primary" :disabled="startingId === selected.item_id" @click="begin(selected)">开始巩固</button></div>
              <section v-else class="assessment-block">
                <div class="assessment-title"><div><span class="section-label">同知识点验证</span><h3>{{ activeAttempt.question.stem }}</h3></div><span class="tag">难度 {{ activeAttempt.question.difficulty }}</span></div>
                <div v-if="isTextAnswerQuestion(activeAttempt.question.question_type)" class="short-answer-field">
                  <label for="consolidation-short-answer">你的回答</label>
                  <textarea id="consolidation-short-answer" v-model="shortAnswer" :disabled="Boolean(result) || submitting" maxlength="4000" rows="6" placeholder="请结合题目要求，用自己的话说明你的理解。" />
                  <small>{{ shortAnswer.length }}/4000</small>
                </div>
                <div v-else class="answer-options"><button v-for="(option, index) in activeAttempt.question.options" :key="option" type="button" :class="{ selected: selectedAnswer === index }" :disabled="Boolean(result)" @click="selectedAnswer = index"><i></i><span>{{ option }}</span></button></div>
                <div v-if="result" class="result-box" :class="result.passed ? 'passed' : 'failed'"><strong>{{ result.passed ? '本次验证已通过' : '本次需要继续练习' }}</strong><p>得分 {{ Math.round(result.score * 100) }} · 通过阈值 {{ Math.round(result.threshold * 100) }} · 置信度 {{ Math.round(result.confidence * 100) }}%</p><p>{{ governanceMessage(result) }}</p><p v-if="result.node_gate && !result.node_gate.can_advance">当前节点仍有 {{ result.node_gate.blocking_mistake_count }} 道阻断性错题。</p><div v-if="result.resource_recommendation" class="result-actions"><button type="button" class="btn primary" :disabled="resourceDecisionSubmitting" @click="generateRecommendedResource">{{ resourceDecisionSubmitting ? '正在创建任务' : result.resource_recommendation.mode === 'next_node' ? '生成下一节点资源' : '生成补救资源' }}</button></div><small>证据 {{ result.evidence_ref }}</small></div>
                <button v-else type="button" class="btn primary detail-primary" :disabled="!hasAttemptAnswer || submitting" @click="submitAttempt">{{ submitting ? (isTextAnswerQuestion(activeAttempt.question.question_type) ? '正在评分' : '正在提交') : '提交验证' }}</button>
              </section>
            </div>

            <div v-else class="detail-pane" role="tabpanel"><ul v-if="selected.attempts?.length" class="history-list"><li v-for="attempt in selected.attempts" :key="attempt.attempt_id"><span>{{ formatDate(attempt.completed_at) }}</span><strong>{{ attempt.status === 'passed' ? '已通过' : attempt.status === 'failed' ? '需继续练习' : '等待确认' }}</strong><small v-if="attempt.evidence_ref">{{ attempt.evidence_ref }}</small></li></ul><div v-else class="pane-empty"><AppIcon name="history" /><h3>暂无巩固记录</h3><p>完成同知识点验证后，正式证据会显示在这里。</p></div></div>
          </template>
        </aside>
      </div>
    </template>

    <AppDrawer v-model="tutorOpen" title="AI 导学" :subtitle="selected ? `${formatKnowledgeName(selected.knowledge_name)} · 本错题独立记录` : '请选择一道错题'">
      <div class="tutor-drawer-content">
        <div v-if="selected" class="tutor-context"><span class="tutor-context-icon"><AppIcon name="sparkles" /></span><span>{{ pathLabel(selected) }} · {{ sourceLabel(selected.source_type) }} · 对话不会与学习资源页混用</span></div>
        <div v-if="!selected?.tutoring_available || !selected.recommended_resource" class="tutor-state"><span class="tutor-empty-icon"><AppIcon name="sparkles" /></span><strong>暂无可用导学资源</strong><p>当前错题没有可用于 AI 导学的已审核关联资源，请先学习或生成关联资源。</p></div>
        <template v-else>
          <div v-if="tutoringLoading" class="tutor-state"><strong>正在恢复导学记录</strong></div>
          <div v-else-if="!tutoringMessages.length && !nodeAssessment" class="tutor-state"><span class="tutor-empty-icon"><AppIcon name="sparkles" /></span><strong>围绕这道错题开始导学</strong><p>对话会持续保存在本错题下；掌握检查仍按当前学习节点的统一规则进行。</p><div class="tutor-suggestions"><button v-for="prompt in quickPrompts.slice(0, 3)" :key="prompt" type="button" :disabled="tutoringSending" @click="sendTutorPrompt(prompt)">{{ prompt }}</button></div></div>
          <div v-else class="tutoring-messages" aria-live="polite">
            <article v-if="nodeAssessment && !assessmentInMessages" class="assistant"><TutoringAssessmentCard :assessment="nodeAssessment" :submitting="assessmentSubmitting === nodeAssessment.assessment_id" @answer="answerAssessment(nodeAssessment, $event)" /></article>
            <article v-for="message in tutoringMessages" :key="message.message_id" :class="message.sender === 'learner' ? 'user' : 'assistant'"><div class="tutor-message-meta"><span class="tutor-avatar">{{ message.sender === 'learner' ? '我' : 'AI' }}</span><strong>{{ message.sender === 'learner' ? '我' : 'AI 导学' }}</strong></div><p>{{ displayTutorContent(message) || '正在组织讲解…' }}</p><small v-if="message.stream_status === 'paused'">已暂停，以上内容已保存。</small><small v-if="message.stream_status === 'interrupted' || message.stream_status === 'failed'">回复中断，可继续提问。</small><ul v-if="message.sources?.length"><li v-for="source in message.sources" :key="`${source.knowledge_id}-${source.source_title}`">{{ source.source_title }}</li></ul><TutoringAssessmentCard v-if="message.assessment" :assessment="message.assessment" :submitting="assessmentSubmitting === message.assessment.assessment_id" @answer="answerAssessment(message.assessment, $event)" /></article>
          </div>
          <p v-if="tutoringError" class="tutoring-error">{{ tutoringError }}</p>
        </template>
      </div>
      <template #footer><div class="tutor-footer-tools"><button class="btn" type="button" :disabled="masteryCheckLoading || tutoringSending || tutoringLoading || !tutorSession?.evidence_scope" @click="requestTutorMasteryCheck">{{ masteryCheckLoading ? '正在准备…' : '申请掌握检查' }}</button></div><form class="tutor-form" @submit.prevent="sendTutorPrompt(tutoringInput)"><div class="tutor-composer"><textarea v-model="tutoringInput" rows="3" maxlength="500" aria-label="输入导学问题" placeholder="输入你仍然不理解的地方" :disabled="tutoringSending || tutoringLoading || !selected?.tutoring_available" @keydown.enter.exact.prevent="sendTutorPrompt(tutoringInput)" /><small>{{ tutoringInput.length }}/500</small></div><button v-if="tutoringSending" class="btn" type="button" @click="pauseTutorOutput">暂停</button><button v-else class="tutor-send" type="submit" title="发送问题" aria-label="发送问题" :disabled="!tutoringInput.trim() || tutoringLoading || !selected?.tutoring_available"><AppIcon name="send" /></button></form></template>
    </AppDrawer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { answerConsolidation, getMistakeItem, getMistakeSummary, listMistakeItems, startConsolidation, type ConsolidationAttempt, type ConsolidationResult, type MistakeReviewItem, type MistakeStatus, type MistakeSummary } from '@/api/mistakeReview'
import { answerTutoringAssessment, createTutoringSession, getTutoringSession, pauseTutoringMessage, requestMasteryCheck, streamTutoringMessage, type TutoringAssessment, type TutoringSession } from '@/api/tutoring'
import { decideLearningAdjustmentResource } from '@/api/learningAdjustments'
import AppIcon from '@/components/Shared/AppIcon.vue'
import PageHeader from '@/components/Shared/PageHeader.vue'
import PageState from '@/components/Shared/PageState.vue'
import AppDrawer from '@/components/Shared/AppDrawer.vue'
import TutoringAssessmentCard from '@/components/ResourceViewer/TutoringAssessmentCard.vue'
import { useAuthStore } from '@/stores/authStore'
import { useDomainStore } from '@/stores/domainStore'
import { formatKnowledgeName } from '@/utils/knowledgeName'
import { useLearnerStore } from '@/stores/learnerStore'
import { useToast } from '@/composables/useToast'
import { isTextAnswerQuestion, mistakePathLabel, mistakePathTone } from './mistakeReviewState'
import { masteryCheckErrorMessage } from '@/utils/masteryCheckError'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const domainStore = useDomainStore()
const learnerStore = useLearnerStore()
const { showToast } = useToast()
const learnerId = computed(() => authStore.role === 'admin'
  ? String(route.query.learner_id || learnerStore.selectedLearnerId || '').trim()
  : String(authStore.user?.learner_id || '').trim())
const domainCode = computed(() => domainStore.currentDomainCode || 'ai_app_dev')
const summary = ref<MistakeSummary | null>(null)
const items = ref<MistakeReviewItem[]>([])
const totalItems = ref(0)
const currentPage = ref(1)
const pageSize = 20
const totalPages = computed(() => Math.max(1, Math.ceil(totalItems.value / pageSize)))
const selected = ref<MistakeReviewItem | null>(null)
const activeAttempt = ref<ConsolidationAttempt | null>(null)
const result = ref<ConsolidationResult | null>(null)
const detailTab = ref<'analysis' | 'assessment' | 'history'>('analysis')
const resourceDecisionSubmitting = ref(false)
const selectedAnswer = ref<number | null>(null)
const shortAnswer = ref('')
const loading = ref(false)
const submitting = ref(false)
const startingId = ref('')
const errorMessage = ref('')
const tutorSession = ref<TutoringSession | null>(null)
const tutorOpen = ref(false)
const tutoringLoading = ref(false)
const tutoringInput = ref('')
const tutoringSending = ref(false)
const tutoringError = ref('')
const masteryCheckLoading = ref(false)
const assessmentSubmitting = ref('')
let tutoringController: AbortController | null = null
let activeReplyId = ''
const tutoringMessages = computed(() => tutorSession.value?.messages || [])
const nodeAssessment = computed(() => tutorSession.value?.pending_assessment || tutorSession.value?.node_adjustment_result || null)
const assessmentInMessages = computed(() => Boolean(nodeAssessment.value && tutoringMessages.value.some(message => message.assessment?.assessment_id === nodeAssessment.value?.assessment_id)))
const quickPrompts = ['解释我为什么容易在这里出错', '换一种方式讲解这个知识点', '给我一个不包含答案的提示', '我还是不理解，拆成步骤说明']
const filters = reactive({ priorityScope: 'current_node' as 'current_node' | 'all', sourceType: '', status: '', difficulty: '' })
const hasActiveFilters = computed(() => Boolean(filters.sourceType || filters.status || filters.difficulty))
const hasAttemptAnswer = computed(() => {
  if (!activeAttempt.value) return false
  return isTextAnswerQuestion(activeAttempt.value.question.question_type)
    ? Boolean(shortAnswer.value.trim())
    : selectedAnswer.value != null
})
const overallProgress = computed(() => summary.value?.total ? Math.round(summary.value.consolidated / summary.value.total * 100) : 0)
const focusTip = computed(() => {
  const count = summary.value?.current_priority_count || 0
  if (count) return `有 ${count} 道错题会阻断当前节点推进，请优先完成巩固验证。`
  if (summary.value?.current_node) return '当前节点没有阻断性错题，可以继续完成本节点的其他学习任务。'
  return '完成首次诊断并生成学习路径后，系统会标出当前必须解决的错题。'
})
const emptyTitle = computed(() => filters.priorityScope === 'current_node' ? '当前节点没有必做错题' : '当前没有错题记录')
const emptyDescription = computed(() => filters.priorityScope === 'current_node' ? '当前节点不存在阻断性错题；你可以继续学习，或查看全部错题提前巩固。' : '继续完成诊断、路径验证和分阶测试，新的错题会自动汇总到这里。')
const sourceOptions = [{ label: '全部来源', value: '' }, { label: '首次诊断', value: 'initial_diagnostic' }, { label: '路径验证', value: 'path_assessment' }, { label: '分阶测试', value: 'graded_quiz' }]
const detailTabs = [{ value: 'analysis' as const, label: '错题解析' }, { value: 'assessment' as const, label: '巩固验证' }, { value: 'history' as const, label: '巩固记录' }]

async function loadAll(preserveSelection = false) {
  if (!learnerId.value) {
    summary.value = null; items.value = []; totalItems.value = 0; selected.value = null
    errorMessage.value = authStore.role === 'admin'
      ? '请先在用户管理中选择一名学习者，再查看其错题巩固记录。'
      : '当前账号未关联有效学习者。'
    return
  }
  loading.value = true; errorMessage.value = ''
  try {
    const [summaryData, listData] = await Promise.all([
      getMistakeSummary(domainCode.value, learnerId.value),
      listMistakeItems({ domainCode: domainCode.value, learnerId: learnerId.value, priorityScope: filters.priorityScope, status: filters.status, sourceType: filters.sourceType, difficulty: Number(filters.difficulty) || undefined, page: currentPage.value, pageSize }),
    ])
    summary.value = summaryData; items.value = listData.items; totalItems.value = listData.total
    if (selected.value) {
      const match = items.value.find(item => item.item_id === selected.value?.item_id)
      if (!match && !preserveSelection) selected.value = null
    }
  } catch { errorMessage.value = '无法读取错题记录，请确认服务和当前领域可用。' }
  finally { loading.value = false }
}

async function selectItem(item: MistakeReviewItem) {
  activeAttempt.value = null; result.value = null; selectedAnswer.value = null; shortAnswer.value = ''; detailTab.value = 'analysis'
  clearTutor(); tutoringInput.value = ''; tutoringError.value = ''
  try {
    selected.value = await getMistakeItem(item.item_id, learnerId.value)
  } catch {
    selected.value = item; showToast('错题详情暂时无法读取，请稍后重试。', 'error')
    return
  }
  if (selected.value.status === 'reviewing') {
    try { activeAttempt.value = await startConsolidation(item.item_id, learnerId.value) }
    catch { showToast('未能恢复待完成的巩固题，请稍后重试。', 'error') }
  }
}

function governanceMessage(value: ConsolidationResult) {
  if (!value.passed) return value.evidence.governance_status === 'conflicted' ? '正式证据存在冲突，画像保持不变，请继续学习和验证。' : '本次结果已记录为正式证据，知识点仍需继续加强。'
  if (value.profile_result.profile_updated) return `画像已更新至 V${value.profile_result.resulting_profile_version}`
  if (value.evidence.governance_status === 'no_change') return '正式证据充分，但画像保持不变。'
  if (value.evidence.governance_status === 'conflicted') return '正式证据存在冲突，画像保持不变，请继续学习和验证。'
  const remaining = Math.max(0, value.evidence.required_evidence_count - value.evidence.eligible_evidence_count)
  return remaining ? `还需 ${remaining} 条独立证据确认掌握。` : value.explanation
}

async function sendTutorPrompt(prompt: string) {
  const text = prompt.trim(); const item = selected.value
  if (!text || !item?.recommended_resource || tutoringSending.value) return
  tutoringSending.value = true; tutoringError.value = ''; tutoringInput.value = ''
  try {
    if (!tutorSession.value) await loadTutorSession(item)
    if (!tutorSession.value) return
    const sessionId = tutorSession.value.session_id
    const pendingId = `pending_${Date.now()}`
    tutorSession.value.messages.push({ message_id: pendingId, sender: 'learner', message_type: 'question', content: text, created_at: null, stream_status: 'completed' })
    const context = `我正在巩固知识点“${formatKnowledgeName(item.knowledge_name)}”。原题摘要：${item.question?.stem || '未提供'}。评分意见：${item.scoring_comment || item.error_summary}。我的问题：${text}。请不要直接给出原题或验证题答案。`
    const controller = new AbortController(); tutoringController = controller
    await streamTutoringMessage(sessionId, context, event => {
      if (!tutorSession.value || tutorSession.value.session_id !== sessionId) return
      if (event.type === 'accepted') { activeReplyId = event.reply_message_id; const pending = tutorSession.value.messages.find(message => message.message_id === pendingId); if (pending) pending.message_id = event.learner_message_id; tutorSession.value.messages.push({ message_id: activeReplyId, sender: 'tutoring_agent', message_type: 'explanation', content: '', created_at: null, stream_status: 'streaming' }) }
      const reply = 'reply_message_id' in event ? tutorSession.value.messages.find(message => message.message_id === event.reply_message_id) : null
      if (event.type === 'delta' && reply) reply.content += event.content
      if (event.type === 'completed' && reply) { reply.content = event.content; reply.sources = event.sources || []; reply.assessment = event.assessment; reply.stream_status = 'completed'; tutorSession.value.pending_assessment = event.pending_assessment || event.assessment; tutorSession.value.node_adjustment_result = event.node_adjustment_result }
      if (event.type === 'error') tutoringError.value = 'AI 导学暂时中断，请重试。'
    }, controller.signal)
  } catch (error) { if ((error as Error).name !== 'AbortError') { tutoringError.value = 'AI 导学暂时不可用，请稍后重试。'; await recoverTutor() } }
  finally { tutoringSending.value = false; tutoringController = null; activeReplyId = '' }
}

async function loadTutorSession(item: MistakeReviewItem) {
  if (!item.recommended_resource) return
  tutoringLoading.value = true; tutoringError.value = ''
  try { tutorSession.value = await createTutoringSession(item.recommended_resource.resource_id, learnerId.value, { type: 'mistake_review', id: item.item_id }) }
  catch { tutoringError.value = '无法打开这道错题的导学记录。' }
  finally { tutoringLoading.value = false }
}
function openMistakeTutor() { tutorOpen.value = true; if (selected.value) void loadTutorSession(selected.value) }
function clearTutor() { tutoringController?.abort(); tutoringController = null; activeReplyId = ''; tutorSession.value = null; tutoringSending.value = false; tutoringLoading.value = false }
async function recoverTutor() { if (tutorSession.value) { try { tutorSession.value = await getTutoringSession(tutorSession.value.session_id) } catch { tutoringError.value = '连接中断，无法恢复导学记录。' } } }
async function pauseTutorOutput() { if (!tutorSession.value || !activeReplyId) return; const replyId = activeReplyId; tutoringController?.abort(); try { await pauseTutoringMessage(tutorSession.value.session_id, replyId); await recoverTutor() } catch { await recoverTutor() } }
async function requestTutorMasteryCheck() { if (!tutorSession.value || masteryCheckLoading.value) return; masteryCheckLoading.value = true; try { await requestMasteryCheck(tutorSession.value.session_id); tutorSession.value = await getTutoringSession(tutorSession.value.session_id) } catch (error) { showToast(masteryCheckErrorMessage(error), 'info') } finally { masteryCheckLoading.value = false } }
async function answerAssessment(assessment: TutoringAssessment, answer: number) { if (!tutorSession.value || assessmentSubmitting.value) return; assessmentSubmitting.value = assessment.assessment_id; try { const response = await answerTutoringAssessment(tutorSession.value.session_id, assessment.assessment_id, answer); Object.assign(assessment, response, { status: 'scored' }); tutorSession.value = await getTutoringSession(tutorSession.value.session_id); showToast(response.decision_reason) } catch { showToast('验证答案提交失败，请刷新后重试。', 'error') } finally { assessmentSubmitting.value = '' } }
function displayTutorContent(message: TutoringSession['messages'][number]) { if (message.sender !== 'learner') return message.content; const marker = '我的问题：'; const content = message.content.includes(marker) ? message.content.split(marker).slice(1).join(marker).replace(/。请不要直接给出原题或验证题答案。$/, '') : message.content; return content }

async function begin(item: MistakeReviewItem) {
  startingId.value = item.item_id
  try { await selectItem(item); activeAttempt.value = await startConsolidation(item.item_id, learnerId.value); detailTab.value = 'assessment' }
  catch { showToast('当前知识点暂无可用的相似验证题，请先学习关联资源。', 'info') }
  finally { startingId.value = '' }
}

async function submitAttempt() {
  if (!selected.value || !activeAttempt.value || !hasAttemptAnswer.value) return
  const itemId = selected.value.item_id
  const answer = isTextAnswerQuestion(activeAttempt.value.question.question_type)
    ? shortAnswer.value.trim()
    : selectedAnswer.value
  if (answer == null) return
  submitting.value = true
  try {
    result.value = await answerConsolidation(itemId, activeAttempt.value.attempt_id, answer, learnerId.value)
    await loadAll(true)
    if (items.value.some(item => item.item_id === itemId)) selected.value = await getMistakeItem(itemId, learnerId.value)
  } catch { showToast('验证结果提交失败，请检查网络后重试。', 'error') }
  finally { submitting.value = false }
}

async function generateRecommendedResource() {
  const recommendation = result.value?.resource_recommendation
  if (!recommendation || resourceDecisionSubmitting.value) return
  resourceDecisionSubmitting.value = true
  try {
    const decision = await decideLearningAdjustmentResource(recommendation.proposal_id, 'generate')
    if (decision.task_id) await router.push({ path: '/resources', query: { task_id: decision.task_id, learner_id: learnerId.value } })
  } catch { showToast('补救资源任务创建失败，请稍后重试。', 'error') }
  finally { resourceDecisionSubmitting.value = false }
}

function openResource(item: MistakeReviewItem) { if (item.recommended_resource) router.push({ path: '/resources', query: { resource_id: item.recommended_resource.resource_id, learner_id: learnerId.value } }) }
function resetFilters() { filters.sourceType = ''; filters.status = ''; filters.difficulty = '' }
function setPriorityScope(scope: 'current_node' | 'all') { filters.priorityScope = scope }
function changePage(page: number) { currentPage.value = page; void loadAll() }
const pathLabel = mistakePathLabel
const pathTone = mistakePathTone
function statusLabel(status: MistakeStatus) { return ({ pending: '待巩固', reviewing: '巩固中', verification_pending: '需要确认', consolidated: '已巩固', needs_more_practice: '继续练习' } as Record<string, string>)[status] || status }
function statusTone(status: MistakeStatus) { return status === 'consolidated' ? 'ok' : status === 'reviewing' ? 'info' : status === 'needs_more_practice' ? 'error' : 'wait' }
function sourceLabel(source: string) { return ({ initial_diagnostic: '首次诊断', path_assessment: '路径验证', graded_quiz: '分阶测试' } as Record<string, string>)[source] || source }
function typeLabel(type: string) { return ({ single_choice: '单选题', multiple_choice: '多选题', short_answer: '简答题', coding: '编程题' } as Record<string, string>)[type] || type }
function formatDate(value?: string | null) { return value ? new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value)) : '时间待确认' }

watch(filters, () => { currentPage.value = 1; void loadAll() })
watch([learnerId, domainCode], () => { currentPage.value = 1; void loadAll() })
onMounted(loadAll)
</script>

<style scoped>
.mistake-page { max-width: 1080px; margin: 0 auto; gap: 20px; }
.context-label { display: inline-block; margin-top: 8px; color: var(--muted); font-size: 12px; }
.review-overview { display: grid; grid-template-columns: minmax(280px, 1.25fr) minmax(340px, 1fr); overflow: hidden; border: 1px solid var(--line); border-radius: 16px; background: var(--surface-raised); }
.progress-summary { padding: 24px 26px; border-right: 1px solid var(--line); }
.overview-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; }.overview-kicker { color: var(--blue); font-size: 12px; font-weight: 750; }.overview-heading h2 { margin-top: 6px; color: var(--ink); font-size: 22px; }.overview-heading p { margin-top: 6px; color: var(--muted); font-size: 13px; line-height: 1.7; }.overview-heading strong { color: var(--ink); font-size: 26px; line-height: 1; }
.progress-track { height: 8px; overflow: hidden; margin-top: 14px; border-radius: 999px; background: var(--track); }
.progress-track i { display: block; height: 100%; border-radius: inherit; background: var(--blue); transition: width 220ms cubic-bezier(.22, 1, .36, 1); }
.focus-tip { margin: 10px 0 0; color: var(--body); font-size: 12px; }
.status-summary { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin: 0; padding: 12px; }
.status-summary div { display: grid; align-content: center; gap: 6px; min-width: 0; border: 1px solid rgb(255 255 255 / .8); border-radius: 10px; background: rgb(255 255 255 / .75); padding: 14px 10px; text-align: center; }
.status-summary dt { color: var(--muted); font-size: 11px; }
.status-summary dd { margin: 0; color: var(--ink); font-size: 24px; font-weight: 760; line-height: 1.1; }
.filter-bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; border: 1px solid var(--line); border-radius: 16px; background: var(--panel); padding: 17px 20px; box-shadow: 0 1px 2px rgb(16 24 40 / .03); }
.filter-heading { width: 100%; display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; padding-bottom: 13px; border-bottom: 1px solid var(--line); }
.filter-heading > div { display: grid; gap: 3px; }.filter-heading strong { font-size: 15px; }.filter-heading span,.filter-heading small { color: var(--muted); font-size: 11px; }
.filter-group { display: flex; gap: 4px; flex-wrap: wrap; margin-right: auto; }
.filter-button { min-height: 36px; border: 1px solid transparent; border-radius: 7px; background: transparent; color: var(--body); padding: 6px 11px; transition: color var(--transition-fast), background var(--transition-fast), border-color var(--transition-fast); }
.filter-button:hover { background: var(--soft); }.filter-button.active { border-color: var(--line-info); background: var(--blue2); color: var(--text-info-strong); font-weight: 700; }
.filter-bar label { display: flex; align-items: center; gap: 7px; color: var(--muted); font-size: 12px; }.filter-bar select { min-height: 34px; border: 1px solid var(--line); border-radius: 7px; background: var(--panel); color: var(--ink); padding: 4px 28px 4px 9px; }
.clear-filter { flex: 0 0 auto; }
.mistake-layout { display: grid; grid-template-columns: minmax(0, 1.08fr) minmax(340px, .92fr); gap: 14px; align-items: start; }
.mistake-list { display: grid; gap: 10px; }.mistake-row { border: 1px solid var(--line); border-radius: 12px; background: var(--panel); padding: 17px 18px; transition: border-color var(--transition-fast), background var(--transition-fast); }.mistake-row:hover { border-color: #aebed2; }.mistake-row.selected { border-color: #91a9d8; background: var(--blue2); }
.mistake-main { width: 100%; display: grid; gap: 6px; border: 0; background: transparent; padding: 0; color: inherit; text-align: left; }.mistake-title { display: flex; align-items: center; justify-content: space-between; gap: 12px; }.mistake-title strong { font-size: 15px; }.mistake-meta,.mistake-date { color: var(--muted); font-size: 11px; }.mistake-reason { color: var(--body); font-size: 13px; line-height: 1.6; }.row-actions { display: flex; gap: 7px; flex-wrap: wrap; margin-top: 13px; padding-top: 12px; border-top: 1px solid var(--line); }
.mistake-meta { display: flex; gap: 0; flex-wrap: wrap; }.mistake-meta span { display: inline-flex; align-items: center; }.mistake-meta span + span::before { content: '·'; margin: 0 7px; color: #91a0b2; }
.review-panel { position: sticky; top: 90px; max-height: calc(100vh - 112px); overflow-y: auto; border: 1px solid var(--line); border-radius: 16px; background: var(--panel); padding: 22px 24px; box-shadow: 0 1px 2px rgb(16 24 40 / .03); }.review-empty { min-height: 300px; display: grid; place-items: center; align-content: center; gap: 8px; color: var(--muted); text-align: center; }.review-empty .app-icon { font-size: 28px; }.review-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }.review-head span:first-child { color: var(--muted); font-size: 11px; }.review-head h2 { margin-top: 4px; font-size: 18px; }.review-block { margin-top: 18px; padding-top: 17px; border-top: 1px solid var(--line); }.review-block h3 { margin-bottom: 8px; font-size: 14px; }.review-block p,.review-block li { color: var(--body); font-size: 13px; line-height: 1.65; }.question-stem { color: var(--ink) !important; font-weight: 600; }.review-block ol { margin: 8px 0 0; padding-left: 22px; }.assessment-title,.resource-link { display: flex; align-items: center; justify-content: space-between; gap: 12px; }.assessment-title span { color: var(--muted); font-size: 11px; }.answer-options { display: grid; gap: 7px; margin: 13px 0; }.answer-options button { display: flex; align-items: flex-start; gap: 9px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); color: var(--body); padding: 10px 11px; text-align: left; }.answer-options button:hover,.answer-options button.selected { border-color: #9fb6e5; background: var(--blue2); }.answer-options i { width: 14px; height: 14px; flex: 0 0 auto; margin-top: 3px; border: 1px solid #9aabc0; border-radius: 50%; }.answer-options button.selected i { border: 4px solid var(--blue); }.result-box { border-radius: 9px; padding: 12px; }.result-box.passed { background: var(--green2); color: var(--green); }.result-box.failed { background: var(--amber2); color: var(--amber); }.result-box p,.result-box small { display: block; margin-top: 4px; color: inherit; }.history-list { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }.history-list li { display: grid; grid-template-columns: 1fr auto; gap: 3px 10px; border-radius: 8px; background: var(--soft); padding: 9px 10px; }.history-list small { grid-column: 1 / -1; color: var(--muted); overflow-wrap: anywhere; }
.review-head-actions { display: flex; align-items: center; gap: 7px; }.panel-close { width: 30px; height: 30px; display: grid; place-items: center; border: 0; border-radius: 7px; background: transparent; color: var(--muted); font-size: 22px; line-height: 1; }.panel-close:hover { background: var(--soft); color: var(--ink); }
.question-type-note { margin-top: 10px !important; color: var(--muted) !important; font-size: 11px !important; }
.tutoring-block summary { display: flex; align-items: center; justify-content: space-between; gap: 12px; cursor: pointer; list-style: none; }.tutoring-block summary::-webkit-details-marker { display: none; }.tutoring-block summary span { display: grid; gap: 3px; }.tutoring-block summary small,.tutoring-empty { color: var(--muted); font-size: 11px; }.quick-prompts { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 13px; }.quick-prompts button { border: 1px solid var(--line); border-radius: 7px; background: var(--soft); color: var(--body); padding: 7px 9px; text-align: left; }.quick-prompts button:hover { border-color: #9fb6e5; background: var(--blue2); }.tutoring-messages { display: grid; gap: 8px; margin-top: 13px; }.tutoring-messages article { border-radius: 8px; background: var(--soft); padding: 10px 11px; }.tutoring-messages article.user { margin-left: 30px; background: var(--blue2); }.tutoring-messages article p { margin-top: 4px; white-space: pre-wrap; }.tutoring-messages ul { margin: 7px 0 0; padding-left: 18px; }.tutoring-compose { display: grid; gap: 8px; margin-top: 12px; }.tutoring-compose textarea { width: 100%; resize: vertical; }.tutoring-compose .btn { justify-self: end; }.tutoring-error { margin-top: 9px; color: var(--red) !important; }.tutoring-empty { margin-top: 12px; border-radius: 8px; background: var(--soft); padding: 11px; line-height: 1.6; }
.pagination { display: flex; align-items: center; justify-content: center; gap: 12px; padding: 8px 0 2px; }.pagination span { color: var(--muted); font-size: 11px; }
.filter-button:focus-visible,.mistake-main:focus-visible,.answer-options button:focus-visible,.panel-close:focus-visible { outline: 3px solid var(--visual-ring); outline-offset: 2px; }

/* 深色主题：概览、筛选与答题交互状态使用同一套语义色。 */
.app.theme-dark .review-overview { border-color: var(--line); background: var(--surface-raised); }
.app.theme-dark .progress-summary { border-color: var(--line); }
.app.theme-dark .status-summary div { border-color: var(--line); background: var(--panel); }
.app.theme-dark .filter-button.active { border-color: var(--line-info); color: var(--text-info-strong); }
.app.theme-dark .mistake-row:hover { border-color: var(--line-strong); }
.app.theme-dark .mistake-row.selected { border-color: var(--line-info); }
.app.theme-dark .mistake-meta span + span::before { color: var(--muted); }
.app.theme-dark .answer-options button:hover,
.app.theme-dark .answer-options button.selected,
.app.theme-dark .quick-prompts button:hover { border-color: var(--line-info); }
.app.theme-dark .answer-options i { border-color: var(--muted); }
@media (max-width: 980px) { .review-overview { grid-template-columns: 1fr; }.progress-summary { border-right: 0; border-bottom: 1px solid var(--line); }.mistake-layout { grid-template-columns: 1fr; }.review-panel { position: static; max-height: none; } }
@media (max-width: 680px) { .status-summary div { padding: 14px; }.filter-group { width: 100%; overflow-x: auto; flex-wrap: nowrap; padding-bottom: 2px; }.filter-button { white-space: nowrap; }.filter-bar label { width: calc(50% - 5px); display: grid; gap: 4px; }.filter-bar select { width: 100%; }.clear-filter { width: 100%; }.row-actions .btn { flex: 1; }.review-panel { padding: 16px; } }
@media (max-width: 480px) { .overview-heading { align-items: flex-start; flex-direction: column; gap: 8px; }.status-summary dd { font-size: 21px; }.filter-bar label { width: 100%; }.mistake-title { align-items: flex-start; }.mistake-meta span + span::before { margin: 0 5px; } }
@media (prefers-reduced-motion: reduce) { .progress-track i { transition: none; } }

/* Current-node-first mistake workspace */
.mistake-page { width: 100%; max-width: 1320px; gap: 16px; }
.priority-strip { display: grid; grid-template-columns: minmax(300px, 1.35fr) 112px minmax(220px, .8fr) minmax(300px, 1fr); align-items: stretch; overflow: hidden; border: 1px solid var(--line); border-left: 4px solid var(--amber); border-radius: var(--radius-panel); background: var(--panel); }
.priority-strip.complete { border-left-color: var(--green); }
.priority-copy { display: grid; align-content: center; gap: 4px; padding: 19px 22px; }
.priority-kicker,.section-label { color: var(--muted); font-size: 12px; font-weight: 700; }
.priority-copy h2 { font-size: 19px; }
.priority-copy p { color: var(--body); font-size: 13px; line-height: 1.55; }
.priority-count { display: grid; place-content: center; gap: 4px; border-left: 1px solid var(--line); border-right: 1px solid var(--line); background: var(--amber2); text-align: center; }
.priority-count strong { color: var(--amber); font-size: 32px; line-height: 1; }.priority-count span { color: var(--amber); font-size: 12px; font-weight: 700; }
.complete .priority-count { background: var(--green2); }.complete .priority-count strong,.complete .priority-count span { color: var(--green); }
.priority-strip .progress-summary { display: grid; align-content: center; gap: 8px; border-right: 1px solid var(--line); padding: 16px 20px; }
.priority-strip .progress-summary > div:first-child { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }.priority-strip .progress-summary span,.priority-strip .progress-summary small { color: var(--muted); font-size: 12px; }.priority-strip .progress-summary strong { font-size: 18px; }
.priority-strip .progress-track { height: 6px; margin: 0; border-radius: 4px; }.priority-strip .progress-track i { background: var(--green); }
.priority-strip .status-summary { padding: 10px; }.priority-strip .status-summary div { border: 0; border-right: 1px solid var(--line); border-radius: 0; background: transparent; }.priority-strip .status-summary div:last-child { border-right: 0; }.priority-strip .status-summary dt { font-size: 12px; }.priority-strip .status-summary dd { font-size: 21px; }
.filter-bar { display: grid; gap: 0; border-radius: var(--radius-panel); padding: 0; box-shadow: none; }
.scope-tabs { display: flex; gap: 22px; border-bottom: 1px solid var(--line); padding: 0 18px; }.scope-tabs button { position: relative; min-height: 48px; border: 0; background: transparent; color: var(--muted); padding: 0 2px; font-weight: 700; }.scope-tabs button::after { content: ''; position: absolute; right: 0; bottom: -1px; left: 0; height: 2px; background: transparent; }.scope-tabs button.active { color: var(--blue); }.scope-tabs button.active::after { background: var(--blue); }.scope-tabs span { margin-left: 5px; border-radius: 5px; background: var(--soft); padding: 2px 6px; font-size: 11px; }.scope-tabs button.active span { background: var(--blue2); }
.filter-controls { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 12px 16px; }.source-tabs { display: flex; gap: 3px; margin-right: auto; }.source-tabs button { min-height: 34px; border: 1px solid transparent; border-radius: 7px; background: transparent; color: var(--body); padding: 5px 10px; font-size: 12px; }.source-tabs button:hover { background: var(--soft); }.source-tabs button.active { border-color: #cddaff; background: var(--blue2); color: #244eae; font-weight: 700; }.filter-controls label { display: flex; align-items: center; gap: 6px; color: var(--muted); font-size: 12px; }.filter-controls select { min-height: 34px; border: 1px solid var(--line); border-radius: 7px; background: var(--panel); color: var(--ink); padding: 4px 28px 4px 9px; }.result-count { min-width: 52px; color: var(--muted); font-size: 12px; text-align: right; }
.mistake-layout { grid-template-columns: minmax(330px, 380px) minmax(0, 1fr); gap: 16px; }
.mistake-list { gap: 0; overflow: hidden; border: 1px solid var(--line); border-radius: var(--radius-panel); background: var(--panel); }.mistake-list > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; padding: 15px 16px; border-bottom: 1px solid var(--line); }.mistake-list > header div { display: grid; gap: 3px; }.mistake-list > header strong { font-size: 14px; }.mistake-list > header span,.mistake-list > header small { color: var(--muted); font-size: 12px; line-height: 1.45; }
.mistake-row { position: relative; display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: end; gap: 10px; border: 0; border-bottom: 1px solid var(--line); border-radius: 0; padding: 14px 14px 13px 16px; }.mistake-row:last-of-type { border-bottom: 0; }.mistake-row::before { content: ''; position: absolute; top: 0; bottom: 0; left: 0; width: 3px; background: transparent; }.mistake-row:hover { border-color: var(--line); background: var(--soft); }.mistake-row.selected { border-color: var(--line); background: var(--blue2); }.mistake-row.priority::before { background: var(--amber); }.mistake-row.selected::before { background: var(--blue); }
.mistake-main { gap: 6px; }.mistake-title strong { overflow: hidden; font-size: 14px; text-overflow: ellipsis; white-space: nowrap; }.mistake-reason { display: -webkit-box; overflow: hidden; color: var(--body); font-size: 13px; line-height: 1.5; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }.mistake-meta { display: block; color: var(--muted); font-size: 12px; }.row-primary { align-self: end; padding-inline: 10px; }.path-badge { width: fit-content; border-radius: 5px; padding: 3px 6px; font-size: 11px; font-weight: 700; }.path-badge.is-priority { background: var(--amber2); color: var(--amber); }.path-badge.is-future { background: var(--info2); color: var(--info); }.path-badge.is-completed { background: var(--green2); color: var(--green); }.path-badge.is-neutral { background: var(--soft); color: var(--muted); }
.review-panel { top: 88px; min-height: 520px; max-height: calc(100vh - 112px); border-radius: var(--radius-panel); padding: 0; box-shadow: none; }.review-empty { min-height: 518px; padding: 32px; }.review-empty p,.pane-empty p { max-width: 430px; color: var(--muted); font-size: 13px; line-height: 1.65; }
.review-head { padding: 19px 22px 16px; border-bottom: 1px solid var(--line); }.review-head > div:first-child { display: grid; gap: 5px; }.review-head h2 { margin: 0; font-size: 19px; }.review-head p { color: var(--muted); font-size: 12px; }.review-head-actions { align-items: flex-start; }
.detail-tabs { position: sticky; top: 0; z-index: 1; display: flex; gap: 20px; overflow-x: auto; border-bottom: 1px solid var(--line); background: var(--panel); padding: 0 22px; }.detail-tabs button { position: relative; min-height: 44px; border: 0; background: transparent; color: var(--muted); padding: 0; font-size: 13px; font-weight: 700; white-space: nowrap; }.detail-tabs button::after { content: ''; position: absolute; right: 0; bottom: -1px; left: 0; height: 2px; background: transparent; }.detail-tabs button.active { color: var(--blue); }.detail-tabs button.active::after { background: var(--blue); }.detail-tabs span { margin-left: 5px; border-radius: 4px; background: var(--soft); padding: 1px 5px; font-size: 10px; }
.detail-pane { min-height: 390px; padding: 22px; }.detail-section { display: grid; gap: 9px; padding-bottom: 20px; }.detail-section + .detail-section { border-top: 1px solid var(--line); padding-top: 20px; }.detail-section p,.detail-section li { color: var(--body); font-size: 14px; line-height: 1.75; }.detail-section ol { display: grid; gap: 7px; margin: 4px 0 0; padding-left: 24px; }.question-stem { font-weight: 650; }
.resource-link { margin-top: 2px; border: 1px solid var(--line); border-radius: 8px; background: var(--soft); padding: 13px 14px; }.resource-link > div { display: grid; gap: 4px; }.resource-link strong { font-size: 13px; }.detail-primary { margin-top: 18px; }
.pane-empty { min-height: 330px; display: grid; place-items: center; align-content: center; gap: 8px; text-align: center; }.pane-empty .app-icon { color: var(--muted); font-size: 28px; }.pane-empty .btn { margin-top: 7px; }
.assessment-title { align-items: flex-start; }.assessment-title > div { display: grid; gap: 8px; }.assessment-title h3 { max-width: 720px; font-size: 17px; line-height: 1.6; }.answer-options { gap: 9px; margin: 20px 0; }.answer-options button { min-height: 46px; padding: 12px 13px; font-size: 14px; line-height: 1.55; }.result-box { padding: 16px; }.result-box p { font-size: 13px; line-height: 1.6; }.result-actions { margin-top: 12px; }
.short-answer-field { display: grid; gap: 7px; margin: 20px 0; }.short-answer-field label { color: var(--body); font-size: 13px; font-weight: 700; }.short-answer-field textarea { width: 100%; min-height: 144px; resize: vertical; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); color: var(--ink); padding: 11px 12px; line-height: 1.65; }.short-answer-field textarea:focus { border-color: var(--blue); box-shadow: var(--focus); outline: 0; }.short-answer-field small { color: var(--muted); font-size: 11px; text-align: right; }
.tutoring-note { border-left: 3px solid var(--info); background: var(--info2); color: var(--info); padding: 10px 12px; font-size: 13px; }.quick-prompts { margin-top: 16px; }.quick-prompts button { min-height: 36px; font-size: 12px; }.tutoring-messages article { padding: 12px 13px; }.tutoring-compose textarea { min-height: 88px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); color: var(--ink); padding: 10px; }.history-list { gap: 0; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }.history-list li { border-bottom: 1px solid var(--line); border-radius: 0; background: var(--panel); padding: 12px 13px; }.history-list li:last-child { border-bottom: 0; }
.pagination { border-top: 1px solid var(--line); padding: 12px; }.pagination span { font-size: 12px; }
.scope-tabs button:focus-visible,.source-tabs button:focus-visible,.detail-tabs button:focus-visible,.path-badge:focus-visible { outline: 3px solid var(--visual-ring); outline-offset: 2px; }
.app.theme-dark .priority-strip,.app.theme-dark .filter-bar,.app.theme-dark .mistake-list,.app.theme-dark .review-panel { border-color: var(--line); background: var(--panel); }.app.theme-dark .source-tabs button.active { border-color: #4b6fa9; color: #d8e7ff; }.app.theme-dark .mistake-row.selected { background: var(--blue2); }
@media (max-width: 1180px) { .priority-strip { grid-template-columns: minmax(300px, 1.3fr) 100px minmax(220px, .8fr); }.priority-strip .status-summary { grid-column: 1 / -1; border-top: 1px solid var(--line); }.priority-strip .status-summary div { padding: 8px; } }
@media (max-width: 980px) { .priority-strip { grid-template-columns: minmax(0, 1fr) 100px; }.priority-strip .progress-summary { grid-column: 1 / -1; border-top: 1px solid var(--line); border-right: 0; }.mistake-layout { grid-template-columns: minmax(300px, 360px) minmax(0, 1fr); }.detail-tabs { gap: 14px; padding-inline: 16px; }.detail-pane { padding: 18px; } }
@media (max-width: 760px) { .priority-strip { grid-template-columns: minmax(0, 1fr) 88px; }.priority-copy { padding: 16px; }.priority-copy h2 { font-size: 17px; }.filter-controls { align-items: stretch; }.source-tabs { width: 100%; overflow-x: auto; }.source-tabs button { white-space: nowrap; }.filter-controls label { flex: 1; display: grid; gap: 4px; }.filter-controls select { width: 100%; }.result-count { align-self: center; }.mistake-layout { grid-template-columns: 1fr; }.mistake-list { order: 1; }.review-panel { display: none; }.review-panel.has-selection { position: fixed; inset: 72px 0 0; z-index: calc(var(--z-sticky) + 1); display: block; min-height: 0; max-height: none; overflow-y: auto; border-width: 1px 0 0; border-radius: 0; box-shadow: 0 -8px 24px rgb(22 35 55 / .12); }.review-head { position: sticky; top: 0; z-index: 2; background: var(--panel); }.detail-tabs { top: 89px; }.review-empty { min-height: 240px; } }
@media (max-width: 520px) { .priority-strip { grid-template-columns: 1fr; }.priority-count { grid-row: 1; grid-column: 1; justify-self: end; width: 76px; min-height: 70px; border-right: 0; }.priority-copy { padding-right: 96px; }.priority-strip .progress-summary { grid-column: 1; }.priority-strip .status-summary { grid-column: 1; }.scope-tabs { gap: 16px; padding-inline: 14px; }.filter-controls label { flex-basis: calc(50% - 5px); }.filter-controls .btn.text { width: 100%; }.mistake-row { grid-template-columns: 1fr; }.row-primary { width: 100%; min-height: 36px; }.review-head { padding: 16px; }.detail-tabs { padding-inline: 16px; }.detail-pane { padding: 16px; }.assessment-title { display: grid; }.quick-prompts { display: grid; }.quick-prompts button { width: 100%; } }

.tutor-trigger .app-icon { font-size: 14px; }
:global(.drawer) { width: min(500px, 95vw); }
:global(.drawer-head) { padding: 18px 20px 16px; background: var(--panel); }
:global(.drawer-body) { padding: 16px 18px 20px; background: var(--bg); }
:global(.drawer-foot) { padding: 14px 18px 18px; background: var(--panel); }
.tutor-drawer-content { min-height: 100%; }
.tutor-context { display: flex; align-items: center; gap: 8px; margin-bottom: 14px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); color: var(--body); padding: 9px 10px; font-size: 12px; font-weight: 650; line-height: 1.6; }
.tutor-context-icon,.tutor-empty-icon { display: grid; place-items: center; border-radius: 7px; background: var(--blue2); color: var(--blue); }.tutor-context-icon { width: 25px; height: 25px; font-size: 14px; }.tutor-empty-icon { width: 40px; height: 40px; font-size: 20px; }
.tutor-state { min-height: 260px; display: grid; align-content: center; justify-items: center; gap: 10px; border: 1px dashed var(--line); border-radius: 10px; background: var(--panel); color: var(--muted); padding: 28px; text-align: center; font-size: 13px; line-height: 1.65; }.tutor-state strong { color: var(--ink); font-size: 14px; }.tutor-state p { max-width: 320px; }.tutor-suggestions { display: flex; flex-wrap: wrap; justify-content: center; gap: 7px; margin-top: 4px; }.tutor-suggestions button { border: 1px solid #cbd9f4; border-radius: 7px; background: var(--blue2); color: var(--blue); padding: 7px 9px; font-size: 11px; }.tutor-suggestions button:hover:not(:disabled) { border-color: var(--blue); }
.tutoring-messages { align-content: start; }.tutoring-messages article { border: 1px solid var(--line); background: var(--panel); }.tutoring-messages article.user { margin-left: 36px; border-color: #cbd9f4; background: var(--blue2); }.tutor-message-meta { display: flex; align-items: center; gap: 7px; }.tutor-avatar { width: 25px; height: 25px; display: grid; place-items: center; border-radius: 6px; background: var(--blue2); color: var(--blue); font-size: 10px; font-weight: 800; }.user .tutor-avatar { background: var(--blue); color: #fff; }.tutor-message-meta strong { font-size: 12px; }.tutoring-messages article > p { font-size: 13px; line-height: 1.7; }
.tutor-form { display: grid; grid-template-columns: minmax(0, 1fr) 38px; align-items: end; gap: 8px; }.tutor-composer { position: relative; }.tutor-composer textarea { width: 100%; min-height: 76px; resize: none; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); color: var(--ink); padding: 9px 10px 22px; outline: none; }.tutor-composer textarea:focus { border-color: var(--blue); box-shadow: var(--focus); }.tutor-composer small { position: absolute; right: 8px; bottom: 6px; color: var(--muted); font-size: 10px; }.tutor-send { width: 38px; height: 38px; display: grid; place-items: center; border: 0; border-radius: 8px; background: var(--blue); color: #fff; font-size: 17px; }.tutor-send:disabled { cursor: not-allowed; opacity: .55; }
.tutor-footer-tools { display: flex; margin-bottom: 9px; }.tutor-footer-tools .btn { width: 100%; justify-content: center; }.tutoring-messages article > small { display: block; margin-top: 7px; color: var(--muted); }

/* Current node and drawer interactions share the semantic status palette. */
.source-tabs button.active { border-color: var(--line-info); color: var(--text-info-strong); }
.quick-prompts button:hover,.answer-options button:hover,.answer-options button.selected { border-color: var(--line-info); }
.tutor-suggestions button,.tutoring-messages article.user { border-color: var(--line-info); }
.tutor-composer textarea:focus { box-shadow: var(--focus); }
</style>
