<template>
  <section class="page mistake-page">
    <PageHeader title="错题巩固" description="集中处理诊断、路径验证和分阶测试中的薄弱题目，用正式验证记录学习进展。">
      <template #meta><span v-if="learnerId" class="context-label">当前学习者：{{ learnerId }}</span></template>
      <template #actions><button type="button" class="btn" :disabled="loading" @click="loadAll"><AppIcon name="history" />{{ loading ? '正在刷新' : '刷新记录' }}</button></template>
    </PageHeader>

    <PageState v-if="loading && !items.length" type="loading" title="正在整理错题" />
    <PageState v-else-if="errorMessage" type="error" title="错题加载失败" :description="errorMessage">
      <button type="button" class="btn" @click="loadAll">重新加载</button>
    </PageState>

    <template v-else>
      <section class="review-overview" aria-label="错题巩固概览">
        <div class="progress-summary">
          <div class="overview-heading"><div><span class="overview-kicker">错题巩固概览</span><h2>巩固进度</h2><p>已巩固 {{ summary?.consolidated ?? 0 }} / {{ summary?.total ?? 0 }} 道错题<template v-if="summary?.consolidation_rate != null"> · 验证通过率 {{ summary.consolidation_rate }}%</template></p></div><strong>{{ overallProgress }}%</strong></div>
          <div class="progress-track" role="progressbar" aria-label="错题巩固进度" :aria-valuenow="overallProgress" aria-valuemin="0" aria-valuemax="100"><i :style="{ width: `${overallProgress}%` }" /></div>
          <p class="focus-tip">{{ summary?.focus_knowledge ? `建议优先处理“${summary.focus_knowledge.name}”相关题目` : '完成正式验证后，这里会显示巩固率。' }}</p>
        </div>
        <dl class="status-summary">
          <div><dt>待巩固</dt><dd>{{ summary?.pending ?? 0 }}</dd></div>
          <div><dt>巩固中</dt><dd>{{ summary?.in_progress ?? 0 }}</dd></div>
          <div><dt>已巩固</dt><dd>{{ summary?.consolidated ?? 0 }}</dd></div>
        </dl>
      </section>

      <section class="filter-bar" aria-label="筛选错题">
        <div class="filter-heading"><div><strong>错题列表</strong><span>按来源、状态和难度筛选</span></div><small>{{ totalItems }} 条结果</small></div>
        <div class="filter-group">
          <button v-for="option in sourceOptions" :key="option.value" type="button" class="filter-button" :class="{ active: filters.sourceType === option.value }" :aria-pressed="filters.sourceType === option.value" @click="filters.sourceType = option.value">{{ option.label }}</button>
        </div>
        <label>状态
          <select v-model="filters.status"><option value="">全部状态</option><option value="pending">待巩固</option><option value="reviewing">巩固中</option><option value="verification_pending">需要确认</option><option value="needs_more_practice">继续练习</option><option value="consolidated">已巩固</option></select>
        </label>
        <label>难度
          <select v-model="filters.difficulty"><option value="">全部难度</option><option v-for="level in 5" :key="level" :value="String(level)">难度 {{ level }}</option></select>
        </label>
        <button v-if="hasActiveFilters" type="button" class="btn text small clear-filter" @click="resetFilters">清除筛选</button>
      </section>

      <PageState v-if="!items.length" type="empty" title="当前没有需要巩固的题目" description="继续完成学习资源和路径验证，新的学习证据会自动汇总到这里。" />
      <div v-else class="mistake-layout">
        <section class="mistake-list" aria-label="错题列表">
          <article v-for="item in items" :key="item.item_id" class="mistake-row" :class="{ selected: selected?.item_id === item.item_id }">
            <button type="button" class="mistake-main" @click="selectItem(item)">
              <span class="mistake-title"><strong>{{ formatKnowledgeName(item.knowledge_name) }}</strong><span class="status" :class="statusTone(item.status)">{{ statusLabel(item.status) }}</span></span>
              <span class="mistake-meta"><span>{{ sourceLabel(item.source_type) }}</span><span>{{ typeLabel(item.question_type) }}</span><span>难度 {{ item.difficulty }}</span><span v-if="item.last_score != null">上次得分 {{ Math.round(item.last_score * 100) }}</span></span>
              <span class="mistake-reason">{{ item.error_summary }}</span>
              <span class="mistake-date">{{ formatDate(item.last_wrong_at) }}<template v-if="item.review_count"> · 已练习 {{ item.review_count }} 次</template></span>
            </button>
            <div class="row-actions">
              <button type="button" class="btn small" @click="selectItem(item)">查看解析</button>
              <button v-if="item.recommended_resource" type="button" class="btn small" @click="openResource(item)">学习关联资源</button>
              <button v-if="item.status !== 'consolidated'" type="button" class="btn primary small" :disabled="startingId === item.item_id" @click="begin(item)">{{ startingId === item.item_id ? '正在准备' : '开始巩固' }}</button>
            </div>
          </article>
          <nav v-if="totalPages > 1" class="pagination" aria-label="错题分页"><button type="button" class="btn small" :disabled="currentPage <= 1 || loading" @click="changePage(currentPage - 1)">上一页</button><span>第 {{ currentPage }} / {{ totalPages }} 页</span><button type="button" class="btn small" :disabled="currentPage >= totalPages || loading" @click="changePage(currentPage + 1)">下一页</button></nav>
        </section>

        <aside class="review-panel" aria-live="polite">
          <div v-if="!selected" class="review-empty"><AppIcon name="check" /><h2>选择一道错题</h2><p>查看错误原因、关联资源和历次巩固记录。</p></div>
          <template v-else>
            <div class="review-head"><div><span>{{ selected.category }}</span><h2>{{ formatKnowledgeName(selected.knowledge_name) }}</h2></div><div class="review-head-actions"><span class="status" :class="statusTone(selected.status)">{{ statusLabel(selected.status) }}</span><button type="button" class="panel-close" aria-label="关闭详情" @click="selected = null"><span aria-hidden="true">×</span></button></div></div>
            <section class="review-block"><h3>错误原因</h3><p>{{ selected.scoring_comment || selected.error_summary }}</p></section>
            <section v-if="selected.question" class="review-block"><h3>原题回顾</h3><p class="question-stem">{{ selected.question.stem }}</p><template v-if="selected.question.options?.length"><button type="button" class="btn text small" @click="showOriginalOptions = !showOriginalOptions">{{ showOriginalOptions ? '收起选项' : '查看题目选项' }}</button><ol v-if="showOriginalOptions"><li v-for="option in selected.question.options" :key="option">{{ option }}</li></ol></template><p v-else class="question-type-note">该题为{{ typeLabel(selected.question_type) }}，没有选项。</p></section>
            <section v-if="activeAttempt" class="review-block assessment-block">
              <div class="assessment-title"><h3>同知识点验证</h3><span>难度 {{ activeAttempt.question.difficulty }}</span></div>
              <p class="question-stem">{{ activeAttempt.question.stem }}</p>
              <div class="answer-options"><button v-for="(option, index) in activeAttempt.question.options" :key="option" type="button" :class="{ selected: selectedAnswer === index }" :disabled="Boolean(result)" @click="selectedAnswer = index"><i></i>{{ option }}</button></div>
              <div v-if="result" class="result-box" :class="result.passed ? 'passed' : 'failed'"><strong>{{ result.passed ? '本次验证已通过' : '本次需要继续练习' }}</strong><p>得分 {{ Math.round(result.score * 100) }}，通过阈值 {{ Math.round(result.threshold * 100) }}，置信度 {{ Math.round(result.confidence * 100) }}%</p><p>{{ governanceMessage(result) }}</p><p v-if="result.profile_result.decision_reason">{{ result.profile_result.decision_reason }}</p><p v-if="result.node_gate && !result.node_gate.can_advance">核心知识已确认 {{ result.node_gate.mastered_knowledge_count || 0 }}/{{ result.node_gate.core_knowledge_count || 0 }}，当前节点仍有 {{ result.node_gate.blocking_mistake_count }} 道阻断性错题。</p><p v-if="result.path_result.updated">学习路径已推进，当前节点：{{ result.path_result.current_node_id || '等待下一节点' }}</p><div v-if="result.resource_recommendation" class="result-actions"><button type="button" class="btn primary small" :disabled="resourceDecisionSubmitting" @click="generateRecommendedResource">{{ resourceDecisionSubmitting ? '正在创建任务' : result.resource_recommendation.mode === 'next_node' ? '生成下一节点资源' : '生成补救资源' }}</button></div><small>证据 {{ result.evidence_ref }}</small></div>
              <button v-else type="button" class="btn primary" :disabled="selectedAnswer == null || submitting" @click="submitAttempt">{{ submitting ? '正在评分' : '提交验证' }}</button>
            </section>
            <section v-if="selected.recommended_resource" class="review-block resource-link"><div><h3>关联学习资源</h3><p>{{ selected.recommended_resource.title }}</p></div><button type="button" class="btn small" @click="openResource(selected)">打开资源</button></section>
            <details class="review-block tutoring-block">
              <summary><span><strong>AI 导学</strong><small>理解错误原因，不替代正式验证</small></span><AppIcon name="sparkles" /></summary>
              <div v-if="!selected.tutoring_available || !selected.recommended_resource" class="tutoring-empty">当前暂无可用于 AI 导学的已审核资源，请先生成或学习关联资源。</div>
              <template v-else>
                <div class="quick-prompts"><button v-for="prompt in quickPrompts" :key="prompt" type="button" :disabled="tutoringSending" @click="sendTutorPrompt(prompt)">{{ prompt }}</button></div>
                <div v-if="tutoringMessages.length" class="tutoring-messages"><article v-for="(message, index) in tutoringMessages" :key="index" :class="message.role"><strong>{{ message.role === 'user' ? '我' : 'AI 导学' }}</strong><p>{{ message.content || '正在组织讲解…' }}</p><ul v-if="message.sources?.length"><li v-for="source in message.sources" :key="`${source.knowledge_id}-${source.source_title}`">{{ source.source_title }}</li></ul></article></div>
                <p v-if="tutoringError" class="tutoring-error">{{ tutoringError }}</p>
                <div class="tutoring-compose"><textarea v-model="tutoringInput" rows="2" maxlength="500" placeholder="输入你仍然不理解的地方" @keydown.ctrl.enter.prevent="sendTutorPrompt(tutoringInput)" /><button type="button" class="btn primary small" :disabled="!tutoringInput.trim() || tutoringSending" @click="sendTutorPrompt(tutoringInput)">{{ tutoringSending ? '正在回答' : '发送问题' }}</button></div>
              </template>
            </details>
            <section v-if="selected.attempts?.length" class="review-block"><h3>巩固记录</h3><ul class="history-list"><li v-for="attempt in selected.attempts" :key="attempt.attempt_id"><span>{{ formatDate(attempt.completed_at) }}</span><strong>{{ attempt.status === 'passed' ? '已通过' : attempt.status === 'failed' ? '需继续练习' : '等待确认' }}</strong><small v-if="attempt.evidence_ref">{{ attempt.evidence_ref }}</small></li></ul></section>
          </template>
        </aside>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { answerConsolidation, getMistakeItem, getMistakeSummary, listMistakeItems, startConsolidation, type ConsolidationAttempt, type ConsolidationResult, type MistakeReviewItem, type MistakeStatus, type MistakeSummary } from '@/api/mistakeReview'
import { createTutoringSession, streamTutoringMessage } from '@/api/tutoring'
import { decideLearningAdjustmentResource } from '@/api/learningAdjustments'
import AppIcon from '@/components/Shared/AppIcon.vue'
import PageHeader from '@/components/Shared/PageHeader.vue'
import PageState from '@/components/Shared/PageState.vue'
import { useAuthStore } from '@/stores/authStore'
import { useDomainStore } from '@/stores/domainStore'
import { formatKnowledgeName } from '@/utils/knowledgeName'
import { useLearnerStore } from '@/stores/learnerStore'
import { useToast } from '@/composables/useToast'

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
const resourceDecisionSubmitting = ref(false)
const selectedAnswer = ref<number | null>(null)
const showOriginalOptions = ref(false)
const loading = ref(false)
const submitting = ref(false)
const startingId = ref('')
const errorMessage = ref('')
const tutoringSessionId = ref('')
const tutoringInput = ref('')
const tutoringSending = ref(false)
const tutoringError = ref('')
const tutoringMessages = ref<Array<{ role: 'user' | 'assistant'; content: string; sources?: Array<{ knowledge_id: string; source_title: string }> }>>([])
const quickPrompts = ['解释我为什么容易在这里出错', '换一种方式讲解这个知识点', '给我一个不包含答案的提示', '我还是不理解，拆成步骤说明']
const filters = reactive({ sourceType: '', status: '', difficulty: '' })
const hasActiveFilters = computed(() => Boolean(filters.sourceType || filters.status || filters.difficulty))
const overallProgress = computed(() => summary.value?.total ? Math.round(summary.value.consolidated / summary.value.total * 100) : 0)
const sourceOptions = [{ label: '全部', value: '' }, { label: '首次诊断', value: 'initial_diagnostic' }, { label: '路径验证', value: 'path_assessment' }, { label: '分阶测试', value: 'graded_quiz' }]

async function loadAll() {
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
      listMistakeItems({ domainCode: domainCode.value, learnerId: learnerId.value, status: filters.status, sourceType: filters.sourceType, difficulty: Number(filters.difficulty) || undefined, page: currentPage.value, pageSize }),
    ])
    summary.value = summaryData; items.value = listData.items; totalItems.value = listData.total
    if (selected.value) {
      const match = items.value.find(item => item.item_id === selected.value?.item_id)
      if (!match) selected.value = null
    }
  } catch { errorMessage.value = '无法读取错题记录，请确认服务和当前领域可用。' }
  finally { loading.value = false }
}

async function selectItem(item: MistakeReviewItem) {
  activeAttempt.value = null; result.value = null; selectedAnswer.value = null; showOriginalOptions.value = false
  tutoringSessionId.value = ''; tutoringInput.value = ''; tutoringMessages.value = []; tutoringError.value = ''
  try { selected.value = await getMistakeItem(item.item_id, learnerId.value) }
  catch { selected.value = item; showToast('错题详情暂时无法读取，请稍后重试。', 'error') }
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
    if (!tutoringSessionId.value) {
      const session = await createTutoringSession(item.recommended_resource.resource_id, learnerId.value)
      tutoringSessionId.value = session.session_id
    }
    tutoringMessages.value.push({ role: 'user', content: text })
    const reply = { role: 'assistant' as const, content: '', sources: [] as Array<{ knowledge_id: string; source_title: string }> }
    tutoringMessages.value.push(reply)
  const context = `我正在巩固知识点“${formatKnowledgeName(item.knowledge_name)}”。原题摘要：${item.question?.stem || '未提供'}。评分意见：${item.scoring_comment || item.error_summary}。我的问题：${text}。请不要直接给出原题或验证题答案。`
    await streamTutoringMessage(tutoringSessionId.value, context, event => {
      if (event.type === 'delta') reply.content += event.content
      if (event.type === 'completed') { reply.content = event.content; reply.sources = event.sources || [] }
      if (event.type === 'error') tutoringError.value = 'AI 导学暂时中断，请重试。'
    }, new AbortController().signal)
  } catch { tutoringError.value = 'AI 导学暂时不可用，请稍后重试。' }
  finally { tutoringSending.value = false }
}

async function begin(item: MistakeReviewItem) {
  startingId.value = item.item_id
  try { await selectItem(item); activeAttempt.value = await startConsolidation(item.item_id, learnerId.value) }
  catch { showToast('当前知识点暂无可用的相似验证题，请先学习关联资源。', 'info') }
  finally { startingId.value = '' }
}

async function submitAttempt() {
  if (!selected.value || !activeAttempt.value || selectedAnswer.value == null) return
  const itemId = selected.value.item_id
  submitting.value = true
  try {
    result.value = await answerConsolidation(itemId, activeAttempt.value.attempt_id, selectedAnswer.value, learnerId.value)
    await loadAll()
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
function changePage(page: number) { currentPage.value = page; void loadAll() }
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
.review-overview { display: grid; grid-template-columns: minmax(280px, 1.25fr) minmax(340px, 1fr); overflow: hidden; border: 1px solid #e2e8f2; border-radius: 16px; background: linear-gradient(135deg, #eef3ff 0%, #f8fafc 55%, #eef8f3 100%); }
.progress-summary { padding: 24px 26px; border-right: 1px solid #e2e8f2; }
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
.filter-button:hover { background: var(--soft); }.filter-button.active { border-color: #cddaff; background: var(--blue2); color: #244eae; font-weight: 700; }
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
.app.theme-dark .review-overview { border-color: #3e5878; background: #1a2b41; }
.app.theme-dark .progress-summary { border-color: #3e5878; }
.app.theme-dark .status-summary div { border-color: var(--line); background: var(--panel); }
.app.theme-dark .filter-button.active { border-color: #4b6fa9; color: #d8e7ff; }
.app.theme-dark .mistake-row:hover { border-color: #597093; }
.app.theme-dark .mistake-row.selected { border-color: #4b6fa9; }
.app.theme-dark .mistake-meta span + span::before { color: var(--muted); }
.app.theme-dark .answer-options button:hover,
.app.theme-dark .answer-options button.selected,
.app.theme-dark .quick-prompts button:hover { border-color: #4b6fa9; }
.app.theme-dark .answer-options i { border-color: var(--muted); }
@media (max-width: 980px) { .review-overview { grid-template-columns: 1fr; }.progress-summary { border-right: 0; border-bottom: 1px solid var(--line); }.mistake-layout { grid-template-columns: 1fr; }.review-panel { position: static; max-height: none; } }
@media (max-width: 680px) { .status-summary div { padding: 14px; }.filter-group { width: 100%; overflow-x: auto; flex-wrap: nowrap; padding-bottom: 2px; }.filter-button { white-space: nowrap; }.filter-bar label { width: calc(50% - 5px); display: grid; gap: 4px; }.filter-bar select { width: 100%; }.clear-filter { width: 100%; }.row-actions .btn { flex: 1; }.review-panel { padding: 16px; } }
@media (max-width: 480px) { .overview-heading { align-items: flex-start; flex-direction: column; gap: 8px; }.status-summary dd { font-size: 21px; }.filter-bar label { width: 100%; }.mistake-title { align-items: flex-start; }.mistake-meta span + span::before { margin: 0 5px; } }
@media (prefers-reduced-motion: reduce) { .progress-track i { transition: none; } }
</style>
