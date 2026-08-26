<template>
  <section class="page">
    <PageHeader title="诊断训练" description="完成 10 道领域题目，识别当前能力基础与需要优先巩固的知识。">
      <template #actions>
        <button type="button" class="btn primary" :disabled="creatingSession || submitting" @click="startSession">{{ creatingSession ? '正在创建' : session || result ? '重新开始训练' : '创建 10 题训练' }}</button>
      </template>
    </PageHeader>

    <!-- No Session -->
    <div v-if="!session && !result" class="panel diagnostic-empty">
      <div class="upload-icon">◎</div>
      <strong>尚未开始诊断训练</strong>
      <p class="sub">系统将从 {{ domainStore.currentDomainName || domainCode }} 领域题库中抽取 10 道题，覆盖理论理解与实操场景。</p>
      <button type="button" class="btn primary" :disabled="creatingSession" @click="startSession">{{ creatingSession ? '正在创建' : '开始诊断训练' }}</button>
    </div>

    <!-- Test View -->
    <div v-if="session && !result" class="diag">
      <aside class="panel">
        <h2>{{ domainStore.currentDomainName || session.domain_code }} 诊断</h2>
        <p class="sub">{{ session.question_count }} 题 · 会话 {{ session.session_id?.slice(0,8) }}</p>
        <div class="qnav">
          <button v-for="(q,i) in session.questions" :key="q.question_id" class="q"
            :class="{ done: answers[i] !== undefined && answers[i] !== '', current: i === currentIdx }" :aria-current="i===currentIdx?'step':undefined" @click="currentIdx=i">{{ i+1 }}</button>
        </div>
        <p class="sub" style="margin-top:18px">已完成 {{ answeredCount }}/{{ session.question_count }} 题</p>
      </aside>
      <article v-if="currentQuestion" class="panel">
        <div class="meta">
          <span class="tag">{{ currentQuestion.question_type === 'single_choice' ? '单选题' : '简答题' }}</span>
          <span class="tag">难度 {{ currentQuestion.difficulty }}/5</span>
        </div>
        <h2 class="question">{{ currentQuestion.stem }}</h2>
        <div v-if="currentQuestion.question_type === 'single_choice'" class="options">
          <label v-for="(opt, i) in currentQuestion.options" :key="i" class="option">
            <input type="radio" :name="'q'+currentIdx" :value="i" v-model="answers[currentIdx]" :disabled="submitting || scoringPending" />{{ String.fromCharCode(65+i) }}. {{ opt }}
          </label>
        </div>
        <textarea v-else v-model="answers[currentIdx]" class="short-answer" :disabled="submitting || scoringPending" aria-label="简答题答案" placeholder="请输入答案"></textarea>
        <div class="actions question-actions">
          <button type="button" class="btn" :disabled="currentIdx===0" @click="currentIdx = Math.max(0, currentIdx-1)">上一题</button>
          <button v-if="!isLastQuestion" type="button" class="btn primary" @click="currentIdx++">下一题</button>
          <button v-else type="button" class="btn primary" :disabled="submitting || (!allAnswered && !scoringPending)" @click="submitAll">{{ submitting ? '正在进行 AI 评分' : scoringPending ? '重试 AI 评分' : allAnswered ? '提交诊断' : `还有 ${unansweredCount} 题未完成` }}</button>
        </div>
      </article>
    </div>

    <!-- Completion summary: profile details live in the learning report. -->
    <div v-if="result" class="panel completion-panel">
      <div class="completion-mark" aria-hidden="true">✓</div>
      <div>
        <h2>诊断训练已完成</h2>
        <p class="sub">答题结果已保存，能力画像与薄弱知识分析请前往学习报告查看。</p>
      </div>
      <div class="completion-stats" aria-label="诊断训练结果">
        <div><span>答对题数</span><strong>{{ result.correct_count }}/{{ result.question_count }}</strong></div>
        <div><span>正确题数</span><strong>{{ result.correct_count }}</strong></div>
        <div><span>正确率</span><strong>{{ accuracyPercent }}%</strong></div>
      </div>
      <div v-if="shortAnswerResults.length" class="ai-results">
        <article v-for="item in shortAnswerResults" :key="item.question_id" class="ai-result">
          <div class="ai-result-head">
            <strong>简答题 AI 评分</strong>
            <span :class="['status', item.scoring_uncertain ? 'wait' : 'ok']">{{ Math.round(item.score * 100) }} 分</span>
          </div>
          <p>{{ item.ai_comment || '已完成结构化评分。' }}</p>
          <ul v-if="item.criteria.length" class="criteria-list">
            <li v-for="criterion in item.criteria" :key="criterion.criterion_id">
              <span>{{ criterion.rationale }}</span><strong>{{ Math.round(criterion.score * 100) }}</strong>
            </li>
          </ul>
          <p v-if="item.missing_points.length" class="result-note">缺失点：{{ item.missing_points.join('、') }}</p>
          <p v-if="item.factual_errors.length" class="result-error">事实错误：{{ item.factual_errors.join('、') }}</p>
          <p v-if="item.scoring_uncertain" class="result-note">预检与模型结论存在分歧，系统已采用保守分数。</p>
        </article>
      </div>
      <div class="actions completion-actions">
        <button class="btn" @click="router.push('/report')">查看学习报告</button>
        <button class="btn primary" :disabled="generating" @click="generateResources">{{ generating ? '正在创建...' : '生成学习资源' }}</button>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useToast } from '@/composables/useToast'
import {
  createDiagnosticSession,
  getCurrentDiagnosticSession,
  getDiagnosticSession,
  retryDiagnosticSession,
  streamDiagnosticSession,
  submitDiagnosticSession,
  type DiagnosticResult,
  type DiagnosticSession,
  type DiagnosticSessionStatus,
} from '@/api/diagnostics'
import { createGenerationTask } from '@/api/generation'
import { useLearnerStore } from '@/stores/learnerStore'
import { useDomainStore } from '@/stores/domainStore'
import { getLearnerProfile } from '@/api/learners'
import { clearDiagnosticDraft, loadDiagnosticDraft, saveDiagnosticDraft } from '@/utils/diagnosticDraft'
import PageHeader from '@/components/Shared/PageHeader.vue'

const router = useRouter()
const route = useRoute()
const learnerStore = useLearnerStore()
const domainStore = useDomainStore()
const { showToast } = useToast()
const domainCode = computed(() => domainStore.currentDomainCode)

const creatingSession = ref(false)
const submitting = ref(false)
const generating = ref(false)
const currentIdx = ref(0)
const session = ref<DiagnosticSession | null>(null)
const result = ref<DiagnosticResult | null>(null)
const scoringPending = ref(false)
const answers = ref<Record<number, string | number>>({})
let scoringEvents: EventSource | null = null

const currentQuestion = computed(() => session.value?.questions[currentIdx.value] || null)
const isLastQuestion = computed(() => Boolean(session.value) && currentIdx.value === session.value!.questions.length - 1)
const answeredCount = computed(() => session.value?.questions.filter((_, index) => String(answers.value[index] ?? '').trim() !== '').length || 0)
const unansweredCount = computed(() => Math.max(0, (session.value?.question_count || 0) - answeredCount.value))
const allAnswered = computed(() => Boolean(session.value) && unansweredCount.value === 0)
const routeLearnerId = String(route.query.learner_id || '').trim()
if (routeLearnerId) learnerStore.setSelectedLearner(routeLearnerId)
const learnerId = computed(() => routeLearnerId || learnerStore.selectedLearnerId)
const accuracyPercent = computed(() => result.value ? Math.round((result.value.correct_count / Math.max(1, result.value.question_count)) * 100) : 0)
const shortAnswerResults = computed(() => result.value?.answer_results?.filter(item => item.question_type === 'short_answer') || [])

function restoreDiagnosticDraft() {
  if (!session.value || !learnerId.value) return
  const draft = loadDiagnosticDraft(
    learnerId.value,
    session.value.session_id,
    session.value.questions.length,
  )
  if (!draft) return
  answers.value = draft.answers
  currentIdx.value = draft.currentIndex
}

function applyDiagnosticStatus(status: DiagnosticSessionStatus) {
  if (status.questions?.length) session.value = status
  if (status.status === 'scored' && status.result) {
    result.value = status.result
    if (learnerId.value) clearDiagnosticDraft(learnerId.value, status.session_id)
    scoringPending.value = false
    submitting.value = false
    showToast(`诊断完成，答对 ${status.result.correct_count}/${status.result.question_count} 题`)
  } else if (status.status === 'pending_scoring') {
    scoringPending.value = true
    submitting.value = false
    showToast('部分简答题评分暂未完成，可安全重试未完成题。', 'error')
  } else if (status.status === 'failed') {
    scoringPending.value = status.retryable
    submitting.value = false
    showToast(`诊断处理失败：${status.error_code || '未知错误'}`, 'error')
  } else if (status.status === 'scoring') submitting.value = true
}

function followScoring(sessionId: string) {
  const currentLearnerId = learnerId.value
  if (!currentLearnerId) return
  scoringEvents?.close()
  scoringEvents = streamDiagnosticSession(sessionId, currentLearnerId, event => {
    applyDiagnosticStatus(event)
    if (event.type !== 'status') scoringEvents = null
  })
  scoringEvents.onerror = async () => {
    scoringEvents?.close()
    scoringEvents = null
    try { applyDiagnosticStatus(await getDiagnosticSession(sessionId, currentLearnerId)) }
    catch { submitting.value = false; showToast('评分连接中断，请刷新页面恢复进度。', 'error') }
  }
}

async function startSession() {
  if (!learnerId.value) { showToast('当前账号未关联学习者'); return }
  if (!domainStore.readiness?.diagnostic_ready) {
    showToast(`当前领域尚未满足诊断条件：${domainStore.readiness?.runtime_reasons?.join('、') || '领域配置不可用'}`, 'error')
    return
  }
  creatingSession.value = true
  try {
    session.value = await createDiagnosticSession(domainCode.value, learnerId.value)
    await router.replace({ query: { ...route.query, session_id: session.value.session_id } })
    result.value = null
    answers.value = {}
    currentIdx.value = 0
    scoringPending.value = false
    showToast('已创建 10 题诊断测评')
  } catch { showToast('创建测评失败') }
  finally { creatingSession.value = false }
}

async function submitAll() {
  if (!session.value || !learnerId.value) return
  submitting.value = true
  try {
    const status = scoringPending.value
      ? await retryDiagnosticSession(session.value.session_id, learnerId.value)
      : await submitDiagnosticSession(
        session.value.session_id,
        Object.entries(answers.value).map(([idx, answer]) => ({
          question_id: session.value!.questions[Number(idx)].question_id,
          answer,
        })),
        domainCode.value,
        learnerId.value,
      )
    scoringPending.value = false
    applyDiagnosticStatus(status)
    if (status.status === 'scoring') followScoring(session.value.session_id)
  } catch (error: any) {
    submitting.value = false
    const code = error?.response?.data?.error?.code || error?.response?.data?.detail
    showToast(code === 'DIAGNOSTIC_ANSWERS_CHANGED' ? '诊断已提交，不能修改本次答案。' : '提交失败', 'error')
  }
}

async function generateResources() {
  if (!result.value || !learnerId.value) return
  if (!domainStore.readiness?.generation_ready) {
    showToast(`当前领域尚未满足生成条件：${domainStore.readiness?.runtime_reasons?.join('、') || 'Candidate RAG 未就绪'}`, 'error')
    return
  }
  generating.value = true
  try {
    const task = await createGenerationTask(domainCode.value, result.value.profile_id, learnerId.value)
    router.push({ path: '/resources', query: { task_id: task.task_id, learner_id: learnerId.value } })
  } catch { showToast('创建生成任务失败') }
  finally { generating.value = false }
}

onMounted(async () => {
  if (!learnerId.value) return
  const profile = await getLearnerProfile(learnerId.value)
  await domainStore.initialize(profile.domain_code)
  const sessionId = String(route.query.session_id || '').trim()
  try {
    const status = sessionId
      ? await getDiagnosticSession(sessionId, learnerId.value)
      : await getCurrentDiagnosticSession(learnerId.value, profile.domain_code)
    if (!status) return
    if (!sessionId) {
      await router.replace({ query: { ...route.query, session_id: status.session_id } })
    }
    applyDiagnosticStatus(status)
    restoreDiagnosticDraft()
    if (status.status === 'scoring') followScoring(status.session_id)
  } catch { await router.replace({ query: { ...route.query, session_id: undefined } }) }
})

watch([() => session.value?.session_id, answers, currentIdx], () => {
  if (!session.value || !learnerId.value || result.value) return
  saveDiagnosticDraft(learnerId.value, session.value.session_id, answers.value, currentIdx.value)
}, { deep: true, flush: 'sync' })

watch(() => domainStore.selectionVersion, () => {
  scoringEvents?.close()
  scoringEvents = null
  session.value = null
  result.value = null
  answers.value = {}
  currentIdx.value = 0
  scoringPending.value = false
})
onBeforeUnmount(() => scoringEvents?.close())
</script>

<style scoped>
.diagnostic-empty { display: grid; justify-items: center; gap: 10px; padding: 48px 28px; text-align: center; }
.diagnostic-empty .upload-icon { margin: auto; }
.diagnostic-empty > strong { margin-top: 4px; }
.diagnostic-empty .sub { max-width: 620px; margin-top: 0; }
.diagnostic-empty .btn { margin-top: 8px; }
.short-answer { width: 100%; min-height: 120px; margin-top: 14px; resize: vertical; }
.question-actions { justify-content: flex-end; margin-top: 22px; }
.completion-panel {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 18px;
  align-items: center;
  padding: 26px;
}
.completion-mark {
  width: 46px;
  height: 46px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--green2);
  color: var(--green);
  font-size: 22px;
  font-weight: 800;
}
.completion-panel h2 { margin: 0; font-size: 19px; }
.completion-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(88px, 1fr));
  gap: 1px;
  border-radius: 10px;
  background: var(--line);
  overflow: hidden;
}
.completion-stats div { min-width: 96px; background: var(--soft); padding: 13px 16px; }
.completion-stats span { display: block; color: var(--muted); font-size: 11px; }
.completion-stats strong { display: block; margin-top: 5px; font-size: 18px; }
.completion-actions { grid-column: 2 / -1; justify-content: flex-end; }
.ai-results { grid-column: 1 / -1; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.ai-result { border: 1px solid var(--line); border-radius: 8px; padding: 14px; background: var(--soft); }
.ai-result-head, .criteria-list li { display: flex; justify-content: space-between; gap: 12px; }
.ai-result p { margin-top: 8px; color: var(--muted); font-size: 12px; line-height: 1.6; }
.criteria-list { display: grid; gap: 6px; margin-top: 10px; padding: 0; list-style: none; font-size: 12px; }
.criteria-list span { color: var(--muted); }
.result-error { color: var(--red) !important; }
.result-note { color: var(--amber) !important; }
@media (max-width: 900px) {
  .completion-panel { grid-template-columns: auto 1fr; }
  .completion-stats, .completion-actions { grid-column: 1 / -1; }
}
@media (max-width: 480px) {
  .diagnostic-empty { padding: 36px 20px; }
  .question-actions { display: grid; grid-template-columns: 1fr 1fr; }
  .question-actions .btn:last-child { grid-column: 2; }
  .completion-stats { grid-template-columns: 1fr; }
  .ai-results { grid-template-columns: 1fr; }
  .completion-actions { display: grid; }
}
</style>
