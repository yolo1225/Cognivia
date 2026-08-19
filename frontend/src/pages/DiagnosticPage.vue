<template>
  <section class="page">
    <div class="head">
      <div><h1>诊断训练</h1><p class="sub">完成 10 道领域题目，帮助系统识别当前能力基础与需要优先巩固的知识。</p></div>
      <div class="actions">
        <button class="btn primary" @click="startSession" :disabled="creatingSession || submitting">{{ creatingSession ? '创建中...' : session || result ? '重新开始训练' : '创建 10 题训练' }}</button>
      </div>
    </div>

    <!-- No Session -->
    <div v-if="!session && !result" class="panel" style="text-align:center;padding:60px">
      <div class="upload-icon" style="margin:auto">◎</div>
      <strong style="display:block;margin-top:14px">尚未开始诊断训练</strong>
      <p class="sub">系统将从 {{ domainCode }} 领域题库中抽取 10 道题，覆盖理论理解与实操场景。</p>
      <button class="btn primary" style="margin-top:16px" @click="startSession" :disabled="creatingSession">{{ creatingSession ? '创建中...' : '开始诊断训练' }}</button>
    </div>

    <!-- Test View -->
    <div v-if="session && !result" class="diag">
      <aside class="panel">
        <h2>{{ session.domain_code }} 诊断</h2>
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
            <input type="radio" :name="'q'+currentIdx" :value="i" v-model="answers[currentIdx]" />{{ String.fromCharCode(65+i) }}. {{ opt }}
          </label>
        </div>
        <textarea v-else v-model="answers[currentIdx]" aria-label="简答题答案" placeholder="请输入答案..." style="margin-top:14px;min-height:100px"></textarea>
        <div class="actions" style="margin-top:22px;justify-content:flex-end">
          <button class="btn" @click="currentIdx = Math.max(0, currentIdx-1)" :disabled="currentIdx===0">上一题</button>
          <button v-if="!isLastQuestion" class="btn primary" @click="currentIdx++">下一题</button>
          <button v-else class="btn primary" @click="submitAll" :disabled="submitting || !allAnswered">{{ submitting ? '正在进行 AI 评分...' : scoringPending ? '重试 AI 评分' : allAnswered ? '提交诊断' : `还有 ${unansweredCount} 题未完成` }}</button>
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
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useToast } from '@/composables/useToast'
import { createDiagnosticSession, submitDiagnosticSession, type DiagnosticSession, type DiagnosticResult } from '@/api/diagnostics'
import { createGenerationTask } from '@/api/generation'
import { useLearnerStore } from '@/stores/learnerStore'

const router = useRouter()
const route = useRoute()
const learnerStore = useLearnerStore()
const { showToast } = useToast()
const domainCode = 'ai_app_dev'

const creatingSession = ref(false)
const submitting = ref(false)
const generating = ref(false)
const currentIdx = ref(0)
const session = ref<DiagnosticSession | null>(null)
const result = ref<DiagnosticResult | null>(null)
const scoringPending = ref(false)
const answers = ref<Record<number, string>>({})

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

async function startSession() {
  if (!learnerId.value) { showToast('当前账号未关联学习者'); return }
  creatingSession.value = true
  try {
    session.value = await createDiagnosticSession(learnerId.value)
    result.value = null
    answers.value = {}
    scoringPending.value = false
    showToast('已创建 10 题诊断测评')
  } catch { showToast('创建测评失败') }
  finally { creatingSession.value = false }
}

async function submitAll() {
  if (!session.value || !learnerId.value) return
  submitting.value = true
  try {
    const list = Object.entries(answers.value).map(([idx, answer]) => ({
      question_id: session.value!.questions[Number(idx)].question_id,
      answer,
    }))
    result.value = await submitDiagnosticSession(session.value.session_id, list, learnerId.value)
    scoringPending.value = false
    showToast(`诊断完成，答对 ${result.value.correct_count}/${result.value.question_count} 题`)
  } catch (error: any) {
    if (error?.response?.data?.error?.code === 'DIAGNOSTIC_SCORING_PENDING') {
      scoringPending.value = true
      showToast('AI 评分暂未完成，答案已保留，请重试。', 'error')
    } else showToast('提交失败', 'error')
  }
  finally { submitting.value = false }
}

async function generateResources() {
  if (!result.value || !learnerId.value) return
  generating.value = true
  try {
    const task = await createGenerationTask(result.value.profile_id, learnerId.value)
    router.push({ path: '/resources', query: { task_id: task.task_id, learner_id: learnerId.value } })
  } catch { showToast('创建生成任务失败') }
  finally { generating.value = false }
}
</script>

<style scoped>
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
  .completion-stats { grid-template-columns: 1fr; }
  .ai-results { grid-template-columns: 1fr; }
  .completion-actions { display: grid; }
}
</style>
