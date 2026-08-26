<template>
  <div class="quiz">
    <template v-if="!showSummary">
      <!-- 进度区 -->
      <div class="quiz-progress">
        <div class="quiz-progress-meta">
          <span class="qp-level">{{ levelLabel(current.level) }}</span>
          <span class="qp-count">{{ currentIndex + 1 }} / {{ orderedQuestions.length }}<small v-if="syncState === 'saving'">正在同步</small><small v-else-if="syncState === 'pending'" class="sync-warn">等待同步</small><small v-else-if="hasDraftScope">进度已保存</small></span>
        </div>
        <div class="quiz-progress-track">
          <span
            v-for="q in orderedQuestions"
            :key="q.question_id"
            class="qp-seg"
            :class="[`qp-${q.level}`, { done: stateOf(q).checked, current: q.question_id === current.question_id }]"
          />
        </div>
      </div>

      <!-- 当前题卡片 -->
      <article class="quiz-card">
        <div class="q-tags">
          <span class="q-level" :class="`ql-${current.level}`">{{ levelLabel(current.level) }}</span>
          <span class="q-type">{{ typeLabel(current.question_type) }}</span>
          <span class="q-diff">难度 {{ current.difficulty }}/5</span>
        </div>
        <h3 class="q-prompt">{{ current.prompt }}</h3>

        <div v-if="isChoice(current)" class="q-options">
          <button
            v-for="opt in current.options"
            :key="opt"
            type="button"
            class="q-option"
            :class="optionClass(current, opt)"
            :disabled="stateOf(current).checked"
            @click="toggleOption(current, opt)"
          >
            <span class="q-option-dot" />
            <span>{{ opt }}</span>
          </button>
        </div>
        <textarea
          v-else
          v-model="answers[current.question_id].text"
          class="q-textarea"
          rows="4"
          placeholder="在此作答…"
          :disabled="stateOf(current).checked"
        />

        <div v-if="stateOf(current).checked" class="q-explanation" :class="verdictClass(current)">
          <strong>
            <template v-if="stateOf(current).correct === true">✓ 回答正确</template>
            <template v-else-if="stateOf(current).correct === false">✗ 回答错误</template>
            <template v-else-if="stateOf(current).selfMarked">✓ 已自评掌握</template>
            <template v-else>参考答案</template>
          </strong>
          <p><b>参考答案：</b>{{ current.correct_answer }}</p>
          <p><b>解析：</b>{{ current.explanation }}</p>
          <p class="q-source"><b>知识点：</b>{{ current.knowledge_id }} · <b>来源：</b>{{ current.source_ref_ids.join('、') }}</p>
          <button
            v-if="!isObjective(current) && !stateOf(current).selfMarked"
            type="button"
            class="btn text"
            @click="markSelfChecked(current)"
          >已完成自我检查</button>
        </div>
      </article>

      <!-- 底部导航 -->
      <div class="quiz-nav">
        <button type="button" class="btn ghost" :disabled="currentIndex === 0" @click="currentIndex -= 1">上一题</button>
        <button v-if="!stateOf(current).checked" type="button" class="btn primary" :disabled="!canCheck(current) || syncState === 'saving'" @click="submitAnswer(current)">
          {{ syncState === 'saving' ? '正在提交' : isObjective(current) ? '提交答案' : '查看参考答案' }}
        </button>
        <button v-else-if="currentIndex < orderedQuestions.length - 1" type="button" class="btn primary" @click="currentIndex += 1">下一题</button>
        <button v-else type="button" class="btn primary" @click="showSummary = true">查看成绩</button>
      </div>
    </template>

    <!-- 成绩总结卡 -->
    <template v-else>
      <div class="quiz-summary">
        <div class="summary-hero">
          <div class="summary-ring" :style="{ '--pct': scorePercent }"><span>{{ scorePercent }}<small>%</small></span></div>
          <div class="summary-copy">
            <h3>测验完成</h3>
            <p>客观题答对 {{ correctObjective }} / {{ objectiveTotal }}，主观题已自评 {{ selfMarkedSubjective }} 道。</p>
          </div>
        </div>
        <div class="summary-levels">
          <div v-for="seg in levelSegments" :key="seg.level" class="summary-level" :class="`sl-${seg.level}`">
            <span class="sl-name">{{ seg.label }}</span>
            <span class="sl-stat">{{ seg.correct }} / {{ seg.count }}</span>
          </div>
        </div>
        <div v-if="weakPoints.length" class="summary-weak">
          <h4>建议巩固的知识点</h4>
          <div class="summary-weak-tags"><span v-for="k in weakPoints" :key="k" class="tag">{{ k }}</span></div>
        </div>
        <div class="summary-actions">
          <button type="button" class="btn ghost" @click="restart">重新作答</button>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { completeQuizAttempt, createQuizAttempt, saveQuizAnswer, type GradedQuizContent, type QuizLevel, type QuizQuestion } from '@/api/resources'
import { loadGradedQuizDraft, saveGradedQuizDraft } from '@/utils/gradedQuizDraft'

interface AnswerState {
  selected: string[]
  text: string
  checked: boolean
  correct: boolean | null
  selfMarked: boolean
}

const props = defineProps<{
  content: GradedQuizContent
  learnerId?: string
  resourceId?: string
  resourceVersion?: number
}>()

const LEVEL_ORDER: QuizLevel[] = ['foundation', 'improvement', 'challenge']
const LEVEL_LABELS: Record<QuizLevel, string> = { foundation: '基础巩固', improvement: '能力提升', challenge: '挑战突破' }

const orderedQuestions = computed(() =>
  [...props.content.questions].sort((a, b) => LEVEL_ORDER.indexOf(a.level) - LEVEL_ORDER.indexOf(b.level)),
)

const currentIndex = ref(0)
const showSummary = ref(false)
const serverAttemptId = ref('')
const syncState = ref<'ready' | 'saving' | 'pending'>('ready')
const answers = reactive<Record<string, AnswerState>>({})
for (const q of props.content.questions) {
  answers[q.question_id] = { selected: [], text: '', checked: false, correct: null, selfMarked: false }
}

const hasDraftScope = computed(() => Boolean(props.learnerId && props.resourceId))

function restoreDraft() {
  const draft = loadGradedQuizDraft(
    props.learnerId || '',
    props.resourceId || '',
    props.resourceVersion,
    props.content.questions.map(question => question.question_id),
  )
  if (!draft) return
  for (const [questionId, state] of Object.entries(draft.answers)) {
    if (answers[questionId]) Object.assign(answers[questionId], state)
  }
  currentIndex.value = draft.currentIndex
  showSummary.value = draft.showSummary
}

function persistDraft() {
  if (!hasDraftScope.value) return
  saveGradedQuizDraft(props.learnerId || '', props.resourceId || '', props.resourceVersion, {
    answers: Object.fromEntries(Object.entries(answers).map(([questionId, state]) => [questionId, {
      selected: [...state.selected],
      text: state.text,
      checked: state.checked,
      correct: state.correct,
      selfMarked: state.selfMarked,
    }])),
    currentIndex: currentIndex.value,
    showSummary: showSummary.value,
  })
}

restoreDraft()
watch([answers, currentIndex, showSummary], persistDraft, { deep: true })

async function restoreServerAttempt() {
  if (!hasDraftScope.value) return
  try {
    const attempt = await createQuizAttempt(props.resourceId || '', props.learnerId)
    serverAttemptId.value = attempt.attempt_id
    for (const [questionId, saved] of Object.entries(attempt.answers || {})) {
      const state = answers[questionId]
      const question = props.content.questions.find(item => item.question_id === questionId)
      if (!state || !question) continue
      const value = saved.answer
      state.selected = Array.isArray(value) ? value.map(String) : isChoice(question) ? [String(value)] : []
      state.text = Array.isArray(value) ? '' : String(value || '')
      state.checked = saved.checked
      state.correct = saved.correct
      state.selfMarked = saved.self_checked
    }
    showSummary.value = attempt.status === 'completed'
    syncState.value = 'ready'
  } catch { syncState.value = 'pending' }
}

onMounted(restoreServerAttempt)

const current = computed(() => orderedQuestions.value[currentIndex.value])
const levelSegments = computed(() =>
  LEVEL_ORDER.filter(level => orderedQuestions.value.some(q => q.level === level)).map(level => {
    const items = orderedQuestions.value.filter(q => q.level === level)
    const correct = items.filter(q => {
      const s = stateOf(q)
      return isObjective(q) ? s.checked && s.correct === true : s.checked && s.selfMarked
    }).length
    return { level, label: LEVEL_LABELS[level], count: items.length, correct }
  }),
)

function stateOf(q: QuizQuestion): AnswerState {
  return answers[q.question_id]
}

function levelLabel(level: QuizLevel): string {
  return LEVEL_LABELS[level]
}

function typeLabel(type: string): string {
  return ({ single_choice: '单选', multiple_choice: '多选', short_answer: '简答', coding: '编程' } as Record<string, string>)[type] || type
}

function isChoice(q: QuizQuestion): boolean {
  return q.question_type === 'single_choice' || q.question_type === 'multiple_choice'
}

function isObjective(q: QuizQuestion): boolean {
  return q.question_type === 'single_choice' || q.question_type === 'multiple_choice'
}

function normalize(text: string): string {
  return text
    .trim()
    .toLowerCase()
    .replace(/^[A-Za-z][.、:：)\s]+/, '')
    .replace(/[\s,，、;；]+/g, '')
}

function judge(q: QuizQuestion, state: AnswerState): boolean | null {
  if (!isObjective(q)) return null
  if (q.question_type === 'single_choice') {
    return normalize(state.selected[0] ?? '') === normalize(q.correct_answer)
  }
  const correctParts = q.correct_answer.split(/[、,，;；]/).map(normalize).filter(Boolean)
  const chosen = (state.selected ?? []).map(normalize).filter(Boolean)
  if (correctParts.length === 0 || chosen.length === 0) return null
  return correctParts.length === chosen.length && correctParts.every(p => chosen.includes(p))
}

function isCorrectOption(q: QuizQuestion, opt: string): boolean {
  if (q.question_type === 'single_choice') return normalize(opt) === normalize(q.correct_answer)
  return q.correct_answer.split(/[、,，;；]/).map(normalize).includes(normalize(opt))
}

function toggleOption(q: QuizQuestion, opt: string): void {
  const state = stateOf(q)
  if (q.question_type === 'single_choice') {
    state.selected = [opt]
    return
  }
  state.selected = state.selected.includes(opt)
    ? state.selected.filter(o => o !== opt)
    : [...state.selected, opt]
}

function canCheck(q: QuizQuestion): boolean {
  const state = stateOf(q)
  return isChoice(q) ? state.selected.length > 0 : state.text.trim().length > 0
}

async function submitAnswer(q: QuizQuestion): Promise<void> {
  const state = stateOf(q)
  const localVerdict = judge(q, state)
  if (!hasDraftScope.value || !serverAttemptId.value) {
    state.checked = true
    state.correct = localVerdict
    syncState.value = hasDraftScope.value ? 'pending' : 'ready'
    return
  }
  syncState.value = 'saving'
  try {
    const result = await saveQuizAnswer(
      props.resourceId || '', serverAttemptId.value, q.question_id,
      isChoice(q) ? state.selected : state.text, props.learnerId,
    )
    state.checked = true
    state.correct = result.correct
    syncState.value = 'ready'
  } catch {
    state.checked = true
    state.correct = localVerdict
    syncState.value = 'pending'
  }
}

async function markSelfChecked(q: QuizQuestion) {
  const state = stateOf(q)
  state.selfMarked = true
  if (!serverAttemptId.value || !hasDraftScope.value) return
  syncState.value = 'saving'
  try {
    await saveQuizAnswer(
      props.resourceId || '', serverAttemptId.value, q.question_id, state.text, props.learnerId, true,
    )
    syncState.value = 'ready'
  } catch { syncState.value = 'pending' }
}

watch(showSummary, async value => {
  if (!value || !serverAttemptId.value || !hasDraftScope.value) return
  try {
    await completeQuizAttempt(props.resourceId || '', serverAttemptId.value, props.learnerId)
  } catch { syncState.value = 'pending' }
})

function optionClass(q: QuizQuestion, opt: string): string {
  const state = stateOf(q)
  const selected = state.selected.includes(opt)
  if (!state.checked) return selected ? 'is-selected' : ''
  if (isCorrectOption(q, opt)) return 'is-correct'
  if (selected) return 'is-wrong'
  return ''
}

function verdictClass(q: QuizQuestion): string {
  const s = stateOf(q)
  if (s.correct === true) return 'is-ok'
  if (s.correct === false) return 'is-bad'
  return 'is-neutral'
}

const objectiveTotal = computed(() => orderedQuestions.value.filter(isObjective).length)
const correctObjective = computed(() => orderedQuestions.value.filter(q => isObjective(q) && stateOf(q).checked && stateOf(q).correct === true).length)
const selfMarkedSubjective = computed(() => orderedQuestions.value.filter(q => !isObjective(q) && stateOf(q).checked && stateOf(q).selfMarked).length)
const subjectiveTotal = computed(() => orderedQuestions.value.filter(q => !isObjective(q)).length)
const scorePercent = computed(() => {
  if (objectiveTotal.value > 0) return Math.round((correctObjective.value / objectiveTotal.value) * 100)
  if (subjectiveTotal.value > 0) return Math.round((selfMarkedSubjective.value / subjectiveTotal.value) * 100)
  return 0
})

const weakPoints = computed(() => {
  const ids = new Set<string>()
  for (const q of orderedQuestions.value) {
    const s = stateOf(q)
    if (s.checked && (s.correct === false || (!isObjective(q) && !s.selfMarked))) ids.add(q.knowledge_id)
  }
  return [...ids]
})

function restart(): void {
  for (const q of orderedQuestions.value) {
    const s = stateOf(q)
    s.selected = []
    s.text = ''
    s.checked = false
    s.correct = null
    s.selfMarked = false
  }
  currentIndex.value = 0
  showSummary.value = false
}
</script>

<style scoped>
.quiz { display: grid; gap: 16px; }

/* 进度 */
.quiz-progress-meta { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.qp-level { color: var(--ink); font-size: 13px; font-weight: 700; }
.qp-count { display: inline-flex; align-items: center; gap: 6px; color: var(--muted); font-size: 12px; }
.qp-count small { color: var(--green); font-size: 11px; }
.qp-count small.sync-warn { color: var(--amber); }
.quiz-progress-track { display: flex; gap: 4px; }
.qp-seg { flex: 1; height: 6px; border-radius: 999px; background: var(--track); transition: background .2s ease; }
.qp-seg.done { background: var(--green); }
.qp-seg.current { background: var(--blue); }
.qp-seg.qp-foundation.done { background: #4f8a5d; }
.qp-seg.qp-improvement.done { background: #6a8bc0; }
.qp-seg.qp-challenge.done { background: #c08a4a; }

/* 题目卡 */
.quiz-card { border: 1px solid var(--line); border-radius: 14px; background: var(--panel); padding: 22px; box-shadow: 0 1px 2px rgb(16 24 40 / .03); }
.q-tags { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.q-level, .q-type, .q-diff { border-radius: 6px; padding: 3px 9px; font-size: 11px; font-weight: 650; }
.q-level.ql-foundation { background: var(--green2); color: #2f6a48; }
.q-level.ql-improvement { background: var(--blue2); color: #3a5a96; }
.q-level.ql-challenge { background: var(--amber2); color: #a0641c; }
.q-type { background: var(--soft); color: var(--muted); }
.q-diff { color: var(--muted); background: var(--soft); }
.q-prompt { margin: 0 0 16px; color: var(--ink); font-size: 16px; font-weight: 650; line-height: 1.6; }

.q-options { display: grid; gap: 10px; }
.q-option { display: flex; align-items: center; gap: 10px; width: 100%; border: 1px solid var(--line); border-radius: 10px; background: var(--panel); padding: 12px 14px; color: var(--ink); font-size: 14px; line-height: 1.6; text-align: left; cursor: pointer; transition: border-color .15s ease, background .15s ease, box-shadow .15s ease; }
.q-option:hover:not(:disabled) { border-color: #b9c9e4; }
.q-option:disabled { cursor: default; }
.q-option-dot { width: 16px; height: 16px; flex-shrink: 0; border: 2px solid #c6d0dd; border-radius: 50%; transition: all .15s ease; }
.q-option.is-selected { border-color: var(--blue); background: var(--blue2); }
.q-option.is-selected .q-option-dot { border-color: var(--blue); background: var(--blue); box-shadow: inset 0 0 0 3px #fff; }
.q-option.is-correct { border-color: var(--green); background: var(--green2); }
.q-option.is-correct .q-option-dot { border-color: var(--green); background: var(--green); box-shadow: inset 0 0 0 3px #fff; }
.q-option.is-wrong { border-color: var(--red); background: var(--red2); }
.q-option.is-wrong .q-option-dot { border-color: var(--red); background: var(--red); box-shadow: inset 0 0 0 3px #fff; }

.q-textarea { width: 100%; border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; color: var(--ink); font-size: 14px; line-height: 1.7; resize: vertical; }
.q-textarea:focus { outline: 0; border-color: var(--blue); box-shadow: 0 0 0 3px rgb(49 95 206 / .12); }

.q-explanation { margin-top: 16px; border-radius: 10px; padding: 13px 15px; font-size: 13px; line-height: 1.7; }
.q-explanation strong { display: block; font-size: 14px; margin-bottom: 4px; }
.q-explanation p { margin: 6px 0 0; }
.q-explanation b { font-weight: 650; }
.q-explanation .q-source { color: var(--muted); font-size: 12px; }
.q-explanation.is-ok { border: 1px solid #c8e6d6; background: var(--green2); color: #1f5c41; }
.q-explanation.is-bad { border: 1px solid #f0cfcf; background: var(--red2); color: #7c3c3c; }
.q-explanation.is-neutral { border: 1px solid #dfe6ef; background: var(--soft); color: var(--body); }
.q-explanation .btn { margin-top: 10px; }

/* 底部导航 */
.quiz-nav { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.quiz-nav .btn { min-width: 110px; }

/* 总结卡 */
.quiz-summary { display: grid; gap: 18px; border: 1px solid var(--line); border-radius: 14px; background: var(--panel); padding: 26px; box-shadow: 0 1px 2px rgb(16 24 40 / .03); }
.summary-hero { display: flex; align-items: center; gap: 20px; }
.summary-ring { --pct: 0; width: 92px; height: 92px; flex-shrink: 0; display: grid; place-items: center; border-radius: 50%; background: conic-gradient(var(--green) calc(var(--pct) * 1%), #e6ebf2 0); }
.summary-ring span { display: grid; place-items: center; width: 72px; height: 72px; border-radius: 50%; background: var(--panel); font-size: 24px; font-weight: 760; color: var(--ink); }
.summary-ring small { font-size: 13px; font-weight: 650; color: var(--muted); }
.summary-copy h3 { margin: 0 0 6px; color: var(--ink); font-size: 20px; }
.summary-copy p { margin: 0; color: var(--muted); font-size: 13px; line-height: 1.7; }
.summary-levels { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.summary-level { display: grid; gap: 4px; border-radius: 10px; padding: 13px 15px; background: var(--soft); }
.summary-level .sl-name { color: var(--muted); font-size: 12px; }
.summary-level .sl-stat { color: var(--ink); font-size: 20px; font-weight: 700; }
.summary-weak h4 { margin: 0 0 8px; color: var(--ink); font-size: 14px; }
.summary-weak-tags { display: flex; flex-wrap: wrap; gap: 7px; }
.summary-actions { display: flex; justify-content: flex-end; }
@media (max-width: 560px) { .summary-levels { grid-template-columns: 1fr; } }
</style>
