<template>
  <section class="wizard" aria-label="建立初始学习画像">
    <header class="wizard-head">
      <div>
        <span class="stage-label">首次学习准备</span>
        <h1>建立你的学习画像</h1>
        <p>先确认学习背景，再完成一次能力诊断。系统会据此安排学习路线。</p>
      </div>
      <ol class="steps" aria-label="建立画像进度">
        <li :class="{ active: step === 'context', done: step !== 'context' }"><span>1</span>学习背景</li>
        <li :class="{ active: step === 'diagnostic', done: step === 'result' }"><span>2</span>能力诊断</li>
        <li :class="{ active: step === 'result' }"><span>3</span>初始画像</li>
      </ol>
    </header>

    <form v-if="step === 'context'" class="wizard-body context-form" @submit.prevent="startDiagnostic">
      <div class="identity"><span>学习者</span><strong>{{ authStore.userId || learnerId }}</strong><span class="tag">{{ domainStore.currentDomainName || domainCode }}</span></div>
      <div class="form-grid">
        <label>学历层次
          <select v-model="form.education_level" required>
            <option value="" disabled>请选择学历层次</option>
            <option value="中职/高中">中职/高中</option><option value="专科">专科</option><option value="本科">本科</option><option value="硕士及以上">硕士及以上</option>
          </select>
        </label>
        <label>专业背景
          <input v-model.trim="form.major" required maxlength="128" placeholder="例如：软件工程、非相关专业" />
        </label>
        <label>相关经验年限
          <input v-model.number="form.experience_years" type="number" min="0" max="50" step="1" required />
        </label>
        <label>学习偏好
          <select v-model="form.learning_style"><option value="theory">理论理解优先</option><option value="practice">项目实操优先</option><option value="mixed">结合推进</option></select>
        </label>
      </div>
      <fieldset>
        <legend>本轮学习方向</legend>
        <p>请选择 1 至 3 项，系统会优先从相关知识主题抽取诊断题。</p>
        <div class="direction-list">
          <label v-for="item in directions" :key="item.value" class="direction" :class="{ selected: form.direction_tags.includes(item.value) }">
            <input v-model="form.direction_tags" type="checkbox" :value="item.value" :disabled="!form.direction_tags.includes(item.value) && form.direction_tags.length >= 3" />
            <span><strong>{{ item.label }}</strong><small>{{ item.description }}</small></span>
          </label>
        </div>
      </fieldset>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <footer class="wizard-actions"><button class="btn primary" type="submit" :disabled="saving || form.direction_tags.length === 0">{{ saving ? '正在保存...' : '保存并开始诊断' }}</button></footer>
    </form>

    <section v-else-if="step === 'diagnostic' && session" class="wizard-body diagnostic-stage">
      <aside class="question-nav"><strong>首次能力诊断</strong><p>{{ session.selection_summary.single_choice_count }} 道选择题 · {{ session.selection_summary.short_answer_count }} 道简答题</p><p>{{ session.selection_summary.theory_count }} 道理论题 · {{ session.selection_summary.practice_count }} 道实操场景题</p><div><button v-for="(_, index) in session.questions" :key="index" type="button" :class="{ current: currentIndex === index, answered: hasAnswer(index) }" @click="currentIndex = index">{{ index + 1 }}</button></div><small>已完成 {{ answeredCount }}/{{ session.question_count }} 题</small></aside>
      <article v-if="currentQuestion" class="question-panel">
        <div class="question-meta"><span class="tag">{{ currentQuestion.question_type === 'single_choice' ? '选择题' : '简答题' }}</span><span class="tag">难度 {{ currentQuestion.difficulty }}/5</span></div>
        <h2>{{ currentQuestion.stem }}</h2>
        <div v-if="currentQuestion.question_type === 'single_choice'" class="options"><label v-for="(option, index) in currentQuestion.options" :key="index"><input v-model="answers[currentIndex]" type="radio" :name="`question-${currentIndex}`" :value="index" :disabled="submitting || scoringPending" />{{ String.fromCharCode(65 + index) }}. {{ option }}</label></div>
        <textarea v-else v-model="answers[currentIndex]" rows="6" placeholder="请输入你的分析与答案" aria-label="简答题答案" :disabled="submitting || scoringPending"></textarea>
        <p v-if="error" class="error" role="alert">{{ error }}</p>
        <p class="draft-note">{{ scoringPending ? '仍有简答题等待评分，可重试未完成题。' : submitting ? `AI 正在评分，进度 ${scoringProgress}% ，可离开页面后再返回。` : '当前答案已暂存，可在提交前返回任意题目修改。' }}</p>
        <footer class="wizard-actions split"><button class="btn" type="button" :disabled="currentIndex === 0 || submitting" @click="currentIndex--">上一题</button><button v-if="currentIndex < session.questions.length - 1" class="btn primary" type="button" :disabled="submitting" @click="currentIndex++">下一题</button><button v-else class="btn primary" type="button" :disabled="submitting || (!scoringPending && answeredCount !== session.question_count)" @click="submitDiagnostic">{{ submitting ? `正在评分 ${scoringProgress}%` : scoringPending ? '重试未完成评分' : answeredCount === session.question_count ? '提交并生成画像' : `还有 ${session.question_count - answeredCount} 题未完成` }}</button></footer>
      </article>
    </section>

    <section v-else-if="step === 'result' && result" class="wizard-body result-stage">
      <span class="result-mark">✓</span><div><span class="stage-label">初始画像已生成</span><h2>{{ profileLabel(result.profile_type) }}</h2><p>本次画像依据已保存：学习背景用于确定学习方向和案例语境，诊断结果用于判定能力与薄弱知识。</p></div>
      <div class="result-grid"><div><span>诊断正确率</span><strong>{{ result.score.toFixed(0) }}%</strong></div><div><span>薄弱知识点</span><strong>{{ result.weak_knowledge.length }} 项</strong></div><div><span>学习路线</span><strong>已生成</strong></div></div>
      <div class="result-evidence"><div><span>先验背景</span><strong>{{ form.education_level }} · {{ form.major }} · {{ form.experience_years }} 年经验</strong><small>用于学习方向、案例语境和资源表达方式。</small></div><div><span>诊断测评</span><strong>{{ result.question_count }} 道题，正确率 {{ result.score.toFixed(0) }}%</strong><small>用于能力分数、掌握度和薄弱知识点判断。</small></div></div>
      <div class="result-radar"><RadarChart :values="radarValues" /></div>
      <div class="result-weak"><strong>优先关注</strong><span v-for="item in result.weak_knowledge.slice(0, 3)" :key="item.knowledge_id">{{ item.name }}</span></div>
      <div v-if="resultStages.length" class="result-route"><strong>推荐学习路线</strong><ol><li v-for="stage in resultStages.slice(0, 3)" :key="stage.name"><span>{{ stage.name }}</span><small>{{ stage.description }}</small></li></ol></div>
      <footer class="wizard-actions"><button class="btn primary" type="button" @click="$emit('complete')">进入学习中心</button></footer>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { createDiagnosticSession, getCurrentDiagnosticSession, getDiagnosticSession, retryDiagnosticSession, streamDiagnosticSession, submitDiagnosticSession, type DiagnosticResult, type DiagnosticSession, type DiagnosticSessionStatus } from '@/api/diagnostics'
import { getLearnerProfile, updateInitialContext, type InitialContextPayload } from '@/api/learners'
import { useAuthStore } from '@/stores/authStore'
import { useDomainStore } from '@/stores/domainStore'
import RadarChart from '@/components/Charts/RadarChart.vue'

const props = defineProps<{ learnerId: string }>()
defineEmits<{ complete: [] }>()
const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const domainStore = useDomainStore()
const step = ref<'context' | 'diagnostic' | 'result'>('context')
const saving = ref(false)
const submitting = ref(false)
const scoringPending = ref(false)
const scoringProgress = ref(0)
const error = ref('')
const session = ref<DiagnosticSession | null>(null)
const result = ref<DiagnosticResult | null>(null)
const domainCode = ref('')
const currentIndex = ref(0)
const answers = ref<Record<number, string | number>>({})
let scoringEvents: EventSource | null = null
const form = reactive<InitialContextPayload>({ education_level: '', major: '', experience_years: 0, learning_style: 'mixed', direction_tags: [] })
const directions = computed(() => {
  const domain = domainStore.domains.find(item => item.domain_code === domainCode.value)
  return (domain?.config?.learning_directions as Array<{ value: string; label: string; description: string }> | undefined) || []
})
const currentQuestion = computed(() => session.value?.questions[currentIndex.value] || null)
const answeredCount = computed(() => session.value?.questions.filter((_, index) => hasAnswer(index)).length || 0)
const radarValues = computed(() => ['theory', 'practice', 'problem_solving', 'breadth', 'learning_speed'].map((key) => Number(result.value?.ability_profile?.[key] || 0)))
const resultStages = computed(() => result.value?.learning_path?.stages || [])

function hasAnswer(index: number) { return String(answers.value[index] ?? '').trim() !== '' }
function profileLabel(type: string) { return ({ beginner: '基础起步型画像', intermediate: '进阶提升型画像', advanced: '综合应用型画像', practice_oriented: '实操导向型画像' } as Record<string, string>)[type] || '个性化学习画像' }

async function startDiagnostic() {
  if (!domainStore.readiness?.diagnostic_ready) {
    error.value = `当前领域尚未满足诊断条件：${domainStore.readiness?.runtime_reasons?.join('、') || '领域配置不可用'}`
    return
  }
  error.value = ''
  saving.value = true
  try {
    await updateInitialContext(props.learnerId, form)
    session.value = await createDiagnosticSession(domainCode.value, props.learnerId)
    await router.replace({ query: { ...route.query, diagnostic_session_id: session.value.session_id } })
    answers.value = {}
    currentIndex.value = 0
    step.value = 'diagnostic'
  } catch (caught: any) {
    error.value = caught.response?.data?.error?.message || '无法保存学习背景或创建诊断，请稍后重试。'
  } finally { saving.value = false }
}

function applyDiagnosticStatus(status: DiagnosticSessionStatus) {
  if (status.questions?.length) session.value = status
  scoringProgress.value = status.progress
  if (status.status === 'scored' && status.result) {
    result.value = status.result
    scoringPending.value = false
    submitting.value = false
    step.value = 'result'
    scoringEvents?.close()
    scoringEvents = null
  } else if (status.status === 'pending_scoring') {
    scoringPending.value = true
    submitting.value = false
    error.value = '部分简答题暂未完成评分，可安全重试未完成题。'
  } else if (status.status === 'failed') {
    scoringPending.value = status.retryable
    submitting.value = false
    error.value = status.retryable ? '评分暂时失败，可重试未完成题。' : `诊断失败：${status.error_code || '未知错误'}`
  } else if (status.status === 'scoring') {
    submitting.value = true
    scoringPending.value = false
  }
}

function followScoring(sessionId: string) {
  scoringEvents?.close()
  scoringEvents = streamDiagnosticSession(sessionId, props.learnerId, event => applyDiagnosticStatus(event))
  scoringEvents.onerror = async () => {
    scoringEvents?.close()
    scoringEvents = null
    try {
      const status = await getDiagnosticSession(sessionId, props.learnerId)
      applyDiagnosticStatus(status)
      if (status.status === 'scoring') followScoring(sessionId)
    } catch {
      submitting.value = false
      error.value = '评分连接中断，请刷新页面恢复进度。'
    }
  }
}

async function submitDiagnostic() {
  if (!session.value) return
  error.value = ''
  submitting.value = true
  try {
    const status = scoringPending.value
      ? await retryDiagnosticSession(session.value.session_id, props.learnerId)
      : await submitDiagnosticSession(session.value.session_id, session.value.questions.map((question, index) => ({ question_id: question.question_id, answer: answers.value[index] })), domainCode.value, props.learnerId)
    error.value = ''
    applyDiagnosticStatus(status)
    if (status.status === 'scoring') followScoring(session.value.session_id)
  } catch (caught: any) {
    error.value = caught.response?.data?.error?.message || '诊断提交失败，请稍后重试。'
  } finally { submitting.value = false }
}

onMounted(async () => {
  try {
    const detail = await getLearnerProfile(props.learnerId)
    domainCode.value = detail.domain_code
    await domainStore.initialize(detail.domain_code)
    form.education_level = detail.education_level || ''
    form.major = detail.major || ''
    form.experience_years = detail.experience_years || 0
    form.learning_style = detail.learning_style as InitialContextPayload['learning_style'] || 'mixed'
    form.direction_tags = detail.direction_tags || []
    const explicitSessionId = String(route.query.diagnostic_session_id || '').trim()
    const status = explicitSessionId
      ? await getDiagnosticSession(explicitSessionId, props.learnerId)
      : await getCurrentDiagnosticSession(props.learnerId, detail.domain_code)
    if (status) {
      if (!explicitSessionId) {
        await router.replace({ query: { ...route.query, diagnostic_session_id: status.session_id } })
      }
      applyDiagnosticStatus(status)
      step.value = status.status === 'scored' ? 'result' : 'diagnostic'
      if (status.status === 'scoring') followScoring(status.session_id)
    }
  } catch { /* The form remains usable for a newly registered learner. */ }
})
onBeforeUnmount(() => scoringEvents?.close())
</script>

<style scoped>
.wizard { max-width: 1080px; border: 1px solid var(--line); border-radius: 10px; background: #fff; overflow: hidden; }
.wizard-head { display: flex; justify-content: space-between; gap: 28px; padding: 34px 42px 26px; border-bottom: 1px solid var(--line); background: #f7f9fd; }.wizard h1,.wizard h2 { margin: 0; color: var(--ink); text-wrap: balance; }.wizard h1 { font-size: 29px; }.wizard-head p { max-width: 580px; margin: 8px 0 0; color: var(--muted); font-size: 14px; line-height: 1.7; }.steps { display: flex; align-items: center; gap: 14px; margin: 0; padding: 0; list-style: none; color: var(--muted); font-size: 12px; white-space: nowrap; }.steps li { display: grid; gap: 5px; justify-items: center; }.steps span { display: grid; width: 24px; height: 24px; place-items: center; border: 1px solid var(--line); border-radius: 50%; background: #fff; }.steps .active,.steps .done { color: var(--blue); font-weight: 700; }.steps .active span,.steps .done span { border-color: var(--blue); background: var(--blue2); }.wizard-body { padding: 34px 42px 40px; }.identity { display: flex; align-items: center; flex-wrap: wrap; gap: 9px; margin-bottom: 26px; color: var(--muted); font-size: 13px; }.identity strong { color: var(--ink); }.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }.context-form label,.context-form fieldset { color: var(--ink); font-size: 13px; font-weight: 700; }.context-form label { display: grid; gap: 8px; }.context-form input,.context-form select,.question-panel textarea { width: 100%; border: 1px solid var(--line); border-radius: 7px; background: #fff; color: var(--ink); padding: 10px 11px; outline: none; }.context-form input:focus,.context-form select:focus,.question-panel textarea:focus { border-color: var(--blue); box-shadow: var(--focus); }.context-form fieldset { margin: 28px 0 0; border: 0; padding: 0; }.context-form legend { margin-bottom: 5px; }.context-form fieldset p { margin: 0 0 12px; color: var(--muted); font-size: 12px; font-weight: 400; }.direction-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }.direction { display: flex !important; align-items: flex-start; gap: 10px; min-height: 76px; border: 1px solid var(--line); border-radius: 8px; padding: 13px; cursor: pointer; }.direction.selected { border-color: var(--blue); background: var(--blue2); }.direction input { width: auto; margin-top: 3px; }.direction span { display: grid; gap: 4px; }.direction small { color: var(--muted); font-size: 11px; font-weight: 400; line-height: 1.5; }.wizard-actions { display: flex; justify-content: flex-end; margin-top: 28px; }.wizard-actions.split { justify-content: space-between; }.error { margin: 16px 0 0; color: var(--red); font-size: 13px; }.diagnostic-stage { display: grid; grid-template-columns: 210px minmax(0, 1fr); gap: 24px; }.question-nav { border-right: 1px solid var(--line); padding-right: 24px; }.question-nav p,.question-nav small { display: block; color: var(--muted); font-size: 12px; line-height: 1.6; }.question-nav div { display: flex; flex-wrap: wrap; gap: 7px; margin: 18px 0; }.question-nav button { width: 30px; height: 30px; border: 1px solid var(--line); border-radius: 6px; background: #fff; color: var(--muted); font-size: 12px; }.question-nav button.current { border-color: var(--blue); color: var(--blue); }.question-nav button.answered { background: var(--blue2); color: var(--blue); }.question-panel h2 { margin-top: 18px; font-size: 21px; line-height: 1.55; }.question-meta { display: flex; gap: 8px; }.options { display: grid; gap: 10px; margin-top: 24px; }.options label { display: flex; gap: 9px; align-items: flex-start; border: 1px solid var(--line); border-radius: 7px; padding: 12px; color: #405067; font-size: 14px; line-height: 1.55; }.options input { margin-top: 4px; }.question-panel textarea { margin-top: 24px; resize: vertical; line-height: 1.6; }.draft-note { margin: 22px 0 -14px; color: var(--muted); font-size: 12px; }.result-stage { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 20px; align-items: start; }.result-mark { display: grid; width: 48px; height: 48px; place-items: center; border-radius: 50%; background: var(--green2); color: var(--green); font-size: 22px; font-weight: 800; }.result-stage p { margin: 10px 0 0; color: var(--muted); line-height: 1.7; }.result-grid { grid-column: 2; display: grid; grid-template-columns: repeat(3, 1fr); gap: 1px; margin-top: 8px; border-radius: 8px; overflow: hidden; background: var(--line); }.result-grid div { background: var(--soft); padding: 14px; }.result-grid span { display: block; color: var(--muted); font-size: 11px; }.result-grid strong { display: block; margin-top: 5px; font-size: 18px; }.result-evidence { grid-column: 2; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1px; overflow: hidden; border-radius: 8px; background: var(--line); }.result-evidence div { display: grid; gap: 4px; background: var(--soft); padding: 13px; }.result-evidence span,.result-evidence small { color: var(--muted); font-size: 11px; line-height: 1.5; }.result-evidence strong { color: var(--ink); font-size: 13px; line-height: 1.5; }.result-radar { grid-column: 2; min-height: 260px; border: 1px solid var(--line); border-radius: 8px; }.result-radar :deep(.chart) { min-height: 260px; }.result-weak { grid-column: 2; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; color: var(--muted); font-size: 12px; }.result-weak strong,.result-route > strong { color: var(--ink); }.result-weak span { border-radius: 6px; background: var(--amber2); color: var(--amber); padding: 4px 7px; }.result-route { grid-column: 2; }.result-route ol { display: grid; gap: 8px; margin: 10px 0 0; padding: 0; list-style: none; }.result-route li { display: grid; grid-template-columns: minmax(130px, .7fr) minmax(0, 1.3fr); gap: 12px; border-top: 1px solid var(--line); padding-top: 8px; color: var(--ink); font-size: 13px; }.result-route small { color: var(--muted); font-size: 12px; line-height: 1.5; }.result-stage .wizard-actions { grid-column: 2; }
@media (max-width: 760px) { .wizard-head { display: grid; padding: 26px 22px 20px; }.steps { justify-content: space-between; }.wizard-body { padding: 26px 22px; }.form-grid,.direction-list,.result-grid { grid-template-columns: 1fr; }.diagnostic-stage { grid-template-columns: 1fr; }.question-nav { border-right: 0; border-bottom: 1px solid var(--line); padding: 0 0 18px; }.result-stage { grid-template-columns: auto minmax(0, 1fr); }.result-grid,.result-weak,.result-stage .wizard-actions { grid-column: 1 / -1; } }
@media (max-width: 760px) { .result-evidence { grid-template-columns: 1fr; }.result-evidence,.result-radar,.result-route { grid-column: 1 / -1; }.result-route li { grid-template-columns: 1fr; gap: 4px; } }
</style>
