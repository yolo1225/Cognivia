<template>
  <section class="page resource-page">
    <header class="rp-head">
      <div>
        <h1>学习资源</h1>
        <p>根据诊断画像生成的个性化学习包：先读讲义、再实操、最后用分级测验检验掌握程度。</p>
      </div>
      <div class="rp-head-actions">
        <button class="btn" :disabled="loading" @click="loadResources">刷新</button>
        <button class="btn" @click="openReport">学习画像</button>
      </div>
    </header>

    <div v-if="taskDetail && !isTaskTerminal" class="panel generation-state">
      <strong>{{ taskDetail.decision === 'revision_required' ? '正在自动修订资源' : '正在生成个性化学习资源' }}</strong>
      <p class="sub">三类资源将在全部达到质量门槛后统一发布。</p>
      <div class="progress-track"><i :style="{ width: `${taskDetail.progress || 5}%` }"></i></div>
    </div>

    <div v-else-if="taskDetail?.status === 'failed'" class="error-state">
      <strong>本次资源未达到发布标准</strong>
      <p>{{ taskDetail.failure_reason || '自动修订达到上限，未达标资源不会向学习者发布。' }}</p>
      <QualityMetrics v-if="taskDetail.package_quality" :metrics="taskDetail.package_quality" />
      <button class="btn primary" :disabled="retrying" @click="retryTask">{{ retrying ? '重新生成中...' : '重新生成' }}</button>
    </div>

    <div v-if="loading" class="panel" style="text-align:center;padding:40px;color:var(--muted)">加载中...</div>

    <div v-else-if="errorMessage" class="error-state"><strong>资源加载失败</strong><p>{{ errorMessage }}</p><button class="btn" @click="loadResources">重新加载</button></div>

    <div v-else-if="taskDetail?.status !== 'failed' && resources.length === 0" class="empty-card">
      <div class="empty-icon">📚</div>
      <h2>暂无学习资源</h2>
      <p>请先在「学习报告」确认初始画像与学习路线，再创建个性化学习包（讲义、实操指南、分阶测试）。</p>
      <button class="btn primary" @click="openReport">查看学习画像</button>
    </div>

    <template v-else-if="taskDetail?.status !== 'failed'">
      <header v-if="resources.length" class="rp-hero">
        <div class="hero-copy">
          <span class="hero-kicker">个性化学习包 · 已达标</span>
          <h2>你的个性化学习包</h2>
          <p>针对诊断画像生成的三类资源已全部通过质量审核，按「讲义 → 实训 → 测验」顺序完成学习。</p>
        </div>
        <div v-if="packageQuality" class="hero-metrics">
          <div><span>幻觉率</span><strong>{{ fmt(packageQuality.hallucination_rate) }}%</strong></div>
          <div><span>难度适配</span><strong>{{ fmt(packageQuality.difficulty_match_score) }}%</strong></div>
          <div><span>核心覆盖</span><strong>{{ fmt(packageQuality.core_knowledge_coverage) }}%</strong></div>
        </div>
      </header>

      <nav v-if="resources.length" class="rp-nav" aria-label="学习资源类型">
        <button
          v-for="(r, i) in resources"
          :key="r.resource_id"
          type="button"
          class="type-card"
          :class="[`tc-${r.resource_type}`, { active: selectedIdx === i }]"
          @click="selectedIdx = i"
        >
          <span class="type-card-icon"><ResourceTypeIcon :type="r.resource_type" /></span>
          <span class="type-card-body">
            <strong :title="r.title">{{ r.title }}</strong>
            <small>{{ typeLabel(r.resource_type) }} · 难度 {{ r.difficulty }}/5</small>
          </span>
          <span class="type-card-flag" aria-hidden="true">›</span>
        </button>
      </nav>

      <div v-if="selected" class="reader-shell" :class="{ 'has-toc': showToc }">
        <main class="reader" :class="`reader-${selected.resource_type}`">
          <header class="reader-head">
            <div class="reader-title">
              <span class="reader-icon"><ResourceTypeIcon :type="selected.resource_type" /></span>
              <div>
                <span class="reader-kicker">{{ typeLabel(selected.resource_type) }} · 难度 {{ selected.difficulty }}/5 · {{ selected.review_status === 'passed' ? '已通过审核' : '待审核' }} · 引用 {{ selected.sources.length }} 条</span>
                <h1>{{ selected.title }}</h1>
              </div>
            </div>
            <div class="reader-tools">
              <button class="btn" :disabled="!canTutor" @click="openTutor">AI 导学</button>
              <button class="btn" @click="exportDialog?.open()">导出</button>
            </div>
          </header>

          <QualityMetrics v-if="selected.quality_metrics" :metrics="selected.quality_metrics" show-details />

          <div class="reader-body">
            <GradedQuizViewer v-if="quizContent" :key="quizContent.title" :content="quizContent" />
            <ResourceMarkdownViewer v-else-if="bodyContent" :content="bodyContent" collapsible :open-headings="2" @headings="onHeadings" />
          </div>

          <section v-if="selected.source_details?.length" class="reader-sources">
            <h2>知识来源</h2>
            <div v-for="s in selected.source_details" :key="s.knowledge_id" class="source">
              <strong>{{ s.name }}</strong><span>{{ s.source_title }}</span>
            </div>
          </section>

          <section class="reader-feedback">
            <h2>学习反馈</h2>
            <p>反馈将触发补救解释、挑战任务或资源复核，不会直接覆盖学习画像。</p>
            <div class="chips">
              <button v-for="item in feedbackOptions" :key="item.value" class="chip" :disabled="feedbackSubmitting" @click="sendFeedback(item.value)">{{ item.label }}</button>
            </div>
          </section>
        </main>

        <aside v-if="showToc" class="reader-toc">
          <span class="toc-title">本页目录</span>
          <button v-for="h in headings" :key="h.id" class="toc-link" :class="`toc-h${h.level}`" @click="scrollToHeading(h.id)">{{ h.text }}</button>
        </aside>
      </div>
    </template>

    <AppDialog ref="exportDialog" title="导出资源" :subtitle="selected?.title || ''">
      <label v-for="f in formats" :key="f.value" class="export-row">
        <input type="radio" name="fmt" :value="f.value" v-model="exportFormat" />
        <span><strong>{{ f.label }}</strong><small>{{ f.desc }}</small></span><span class="tag">{{ f.tag }}</span>
      </label>
      <template #footer>
        <button class="btn" @click="exportDialog?.close()">取消</button>
        <button class="btn primary" @click="doExport">导出资源</button>
      </template>
    </AppDialog>

    <AppDrawer v-model="tutorOpen" title="AI 导学" :subtitle="selected?.title || '请选择学习资源'">
      <div class="tutor-context">围绕当前资源提问。导学记录会按资源分别保存。</div>
      <div v-if="tutorLoading" class="tutor-state">正在加载导学记录...</div>
      <div v-else-if="tutorError" class="tutor-state tutor-error"><p>{{ tutorError }}</p><button class="btn" @click="openTutor">重新加载</button></div>
      <div v-else-if="tutorMessages.length === 0" class="tutor-state">你可以询问概念解释、步骤拆解或练习建议。</div>
      <div v-else ref="messageList" class="tutor-messages" aria-live="polite">
        <div v-for="message in tutorMessages" :key="message.message_id" class="tutor-message" :class="message.sender === 'learner' ? 'is-learner' : 'is-agent'">
          <span>{{ message.sender === 'learner' ? '我' : 'AI 导学' }}</span>
          <ResourceMarkdownViewer :content="message.content || (message.stream_status === 'streaming' ? '正在思考…' : '')" />
          <i v-if="message.stream_status === 'streaming'" class="tutor-cursor" aria-label="正在输出" />
          <small v-if="message.stream_status === 'paused'" class="tutor-stream-note">已暂停，保留以上内容。</small>
          <small v-if="message.stream_status === 'interrupted' || message.stream_status === 'failed'" class="tutor-stream-note">回复中断，可继续提问。</small>
          <small v-if="message.sources?.length" class="tutor-sources">依据：{{ message.sources.map(source => source.name).join('、') }}</small>
          <div v-if="message.assessment?.status === 'pending'" class="tutor-assessment">
            <strong>掌握情况验证</strong><p>{{ message.assessment.prompt }}</p>
            <small>回答后，系统会结合可验证证据判断是否需要调整画像。</small>
          </div>
        </div>
      </div>
      <template #footer>
        <form class="tutor-form" @submit.prevent="sendTutorMessage">
          <textarea v-model="tutorDraft" rows="3" maxlength="2000" placeholder="例如：请用一个例子解释这一部分" :disabled="tutorSending || tutorLoading" @keydown.enter.exact.prevent="sendTutorMessage" />
          <button v-if="tutorSending" class="btn" type="button" @click="pauseTutorMessage">暂停输出</button>
          <button v-else class="btn primary" type="submit" :disabled="!tutorDraft.trim() || tutorLoading">发送</button>
        </form>
      </template>
    </AppDrawer>
  </section>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useToast } from '@/composables/useToast'
import { listResources, exportResource, submitFeedback, type ResourceSummary } from '@/api/resources'
import { getGenerationTask, retryGenerationTask, type GenerationTaskDetail } from '@/api/generation'
import QualityMetrics from '@/components/ResourceViewer/QualityMetrics.vue'
import AppDialog from '@/components/Shared/AppDialog.vue'
import AppDrawer from '@/components/Shared/AppDrawer.vue'
import { createTutoringSession, getTutoringSession, pauseTutoringMessage, streamTutoringMessage, type TutoringSession } from '@/api/tutoring'
import ResourceMarkdownViewer from '@/components/ResourceViewer/ResourceMarkdownViewer.vue'
import GradedQuizViewer from '@/components/ResourceViewer/GradedQuizViewer.vue'
import ResourceTypeIcon from '@/components/ResourceViewer/ResourceTypeIcon.vue'
import { useAuthStore } from '@/stores/authStore'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const { showToast } = useToast()
const loading = ref(false)
const resources = ref<ResourceSummary[]>([])
const selectedIdx = ref(0)
const headings = ref<HeadingItem[]>([])
const exportFormat = ref('markdown')
const exportDialog = ref<InstanceType<typeof AppDialog> | null>(null)
const errorMessage = ref('')
const feedbackSubmitting = ref(false)
const retrying = ref(false)
const taskDetail = ref<GenerationTaskDetail | null>(null)
const tutorOpen = ref(false)
const tutorLoading = ref(false)
const tutorSending = ref(false)
const tutorError = ref('')
const tutorDraft = ref('')
const tutorSession = ref<TutoringSession | null>(null)
const messageList = ref<HTMLElement | null>(null)
let streamController: AbortController | null = null
let activeReplyId = ''
const feedbackOptions = [{ value: 'too_hard', label: '内容太难' }, { value: 'too_easy', label: '内容太简单' }, { value: 'confusing', label: '解释不清楚' }, { value: 'incorrect', label: '内容可能有误' }, { value: 'helpful', label: '对我有帮助' }]
const formats = [
  { value: 'markdown', label: 'Markdown', desc: '保留标题、表格、代码块和知识来源结构。', tag: '源格式' },
  { value: 'pdf', label: 'PDF', desc: '适合阅读、打印和提交。', tag: '推荐' },
]

interface HeadingItem { level: number; text: string; id: string }

const RESOURCE_TYPE_LABELS: Record<string, string> = {
  lecture: '讲义',
  practice_guide: '实训指导',
  graded_quiz: '分级测验',
}
function typeLabel(type: string) { return RESOURCE_TYPE_LABELS[type] || type }
function fmt(value: number) { return Number(value || 0).toFixed(value > 0 && value < 5 ? 1 : 0) }
function onHeadings(items: HeadingItem[]) { headings.value = items }
function scrollToHeading(id: string) {
  const el = document.getElementById(id)
  if (!el) return
  const section = el.closest('details.md-section')
  if (section) (section as HTMLDetailsElement).open = true
  el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

const selected = computed(() => resources.value[selectedIdx.value] || null)
// 后端 render_resource_markdown 会在正文末尾统一追加「## 知识来源」，
// 而页面下方已用更丰富的 source_details 渲染来源，故此处剥离避免重复。
const bodyContent = computed(() => {
  const content = selected.value?.content || ''
  const marker = '\n## 知识来源'
  const index = content.lastIndexOf(marker)
  return index >= 0 ? content.slice(0, index).trimEnd() : content
})
const canTutor = computed(() => Boolean(selected.value && selected.value.review_status === 'passed' && selected.value.is_current !== false))
const quizContent = computed(() => {
  const structured = selected.value?.structured_content
  return structured && structured.resource_type === 'graded_quiz' ? structured : null
})
const isGradedQuiz = computed(() => Boolean(quizContent.value))
const showToc = computed(() => !isGradedQuiz.value && headings.value.length > 1)
const tutorMessages = computed(() => tutorSession.value?.messages || [])
const taskId = computed(() => String(route.query.task_id || '').trim())
const currentLearnerId = computed(() => {
  if (taskId.value) return String(taskDetail.value?.learner_id || route.query.learner_id || '').trim()
  return String(authStore.user?.learner_id || '').trim()
})
const isTaskTerminal = computed(() => ['completed', 'failed'].includes(taskDetail.value?.status || ''))
const packageQuality = computed(() => taskDetail.value?.package_quality || resources.value[0]?.package_quality || null)
let taskTimer: number | null = null

function scrollTutorToLatest() {
  nextTick(() => {
    if (messageList.value) messageList.value.scrollTop = messageList.value.scrollHeight
  })
}

async function openTutor() {
  if (!canTutor.value || !selected.value) return
  tutorOpen.value = true
  tutorLoading.value = true
  tutorError.value = ''
  tutorSession.value = null
  try {
    tutorSession.value = await createTutoringSession(selected.value.resource_id, currentLearnerId.value || undefined)
    scrollTutorToLatest()
  } catch {
    tutorError.value = '无法打开导学会话，请稍后重试。'
  } finally {
    tutorLoading.value = false
  }
}

async function sendTutorMessage() {
  const content = tutorDraft.value.trim()
  if (!content || !tutorSession.value || tutorSending.value) return
  tutorSending.value = true
  tutorError.value = ''
  const pendingId = `pending_${Date.now()}`
  tutorSession.value.messages.push({ message_id: pendingId, sender: 'learner', message_type: 'question', content, created_at: null, stream_status: 'completed' })
  tutorDraft.value = ''
  scrollTutorToLatest()
  streamController = new AbortController()
  try {
    await streamTutoringMessage(tutorSession.value.session_id, content, event => {
      if (!tutorSession.value) return
      if (event.type === 'accepted') {
        activeReplyId = event.reply_message_id
        const learner = tutorSession.value.messages.find(item => item.message_id === pendingId)
        if (learner) learner.message_id = event.learner_message_id
        tutorSession.value.messages.push({ message_id: activeReplyId, sender: 'tutoring_agent', message_type: 'explanation', content: '', created_at: null, stream_status: 'streaming' })
      } else {
        const reply = tutorSession.value.messages.find(item => item.message_id === event.reply_message_id)
        if (event.type === 'delta' && reply) reply.content += event.content
        if (event.type === 'completed' && reply) { reply.content = event.content; reply.sources = event.sources; reply.scope_status = event.scope_status; reply.assessment = event.assessment; reply.stream_status = 'completed'; if (event.task_id) showToast('已触发后续学习调整，可前往任务记录查看进度。') }
        if (event.type === 'paused' && reply) { reply.content = event.content; reply.stream_status = 'paused' }
        if (event.type === 'error' && reply) reply.stream_status = event.recoverable ? 'interrupted' : 'failed'
      }
      scrollTutorToLatest()
    }, streamController.signal)
    tutorSession.value.turn_count += 1
  } catch (error) {
    if ((error as Error).name !== 'AbortError') await recoverTutorSession()
  } finally {
    tutorSending.value = false
    streamController = null
    activeReplyId = ''
  }
}

async function pauseTutorMessage() {
  if (!tutorSession.value || !activeReplyId) return
  streamController?.abort()
  try { await pauseTutoringMessage(tutorSession.value.session_id, activeReplyId); const reply = tutorSession.value.messages.find(item => item.message_id === activeReplyId); if (reply) reply.stream_status = 'paused' }
  catch { await recoverTutorSession() }
}

async function recoverTutorSession() {
  if (!tutorSession.value) return
  try { tutorSession.value = await getTutoringSession(tutorSession.value.session_id); scrollTutorToLatest() }
  catch { tutorError.value = '连接中断，无法恢复导学记录。' }
}

watch(selectedIdx, () => {
  headings.value = []
  if (tutorOpen.value) openTutor()
})

async function loadResources() {
  loading.value = true
  errorMessage.value = ''
  try {
    resources.value = await listResources({ taskId: String(route.query.task_id || '') || undefined, learnerId: currentLearnerId.value || undefined, domainCode: 'ai_app_dev' })
  } catch {
    errorMessage.value = '无法读取学习资源，请确认后端服务可用。'
  } finally {
    loading.value = false
  }
}

async function loadTask() {
  if (!taskId.value) return
  try {
    taskDetail.value = await getGenerationTask(taskId.value)
    if (taskDetail.value.status === 'completed') await loadResources()
    if (!isTaskTerminal.value) taskTimer = window.setTimeout(loadTask, 1500)
  } catch { errorMessage.value = '无法读取生成任务状态。' }
}

function openReport() {
  router.push({
    path: '/report',
    query: {
      ...(currentLearnerId.value ? { learner_id: currentLearnerId.value } : {}),
      ...(taskId.value ? { task_id: taskId.value } : {}),
    },
  })
}

async function retryTask() {
  if (!taskId.value) return
  retrying.value = true
  try { taskDetail.value = await retryGenerationTask(taskId.value); await loadTask() }
  catch { showToast('重新生成失败') }
  finally { retrying.value = false }
}

async function sendFeedback(type: string) {
  if (!selected.value) return
  feedbackSubmitting.value = true
  try { const result = await submitFeedback(selected.value.resource_id, type, 3, currentLearnerId.value || undefined); showToast(`反馈已记录：${String((result as any).decision_reason || (result as any).recommended_action || '系统将按证据处理')}`) }
  catch { showToast('反馈提交失败') }
  finally { feedbackSubmitting.value = false }
}

async function doExport() {
  if (!selected.value) return
  try {
    const r = await exportResource(selected.value.resource_id, exportFormat.value as 'markdown' | 'pdf')
    exportDialog.value?.close()
    showToast(`已导出：${r.file_name}`)
  } catch { showToast('导出失败') }
}

onMounted(async () => { if (taskId.value) await loadTask(); else await loadResources() })
onUnmounted(() => { if (taskTimer !== null) window.clearTimeout(taskTimer) })
</script>

<style scoped>
.resource-page { gap: 20px; }

/* 页头 */
.rp-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; }
.rp-head h1 { font-size: 26px; }
.rp-head p { max-width: 720px; margin-top: 8px; color: var(--muted); font-size: 14px; line-height: 1.7; }
.rp-head-actions { display: flex; gap: 8px; flex-shrink: 0; }

/* 空态 */
.empty-card { display: grid; justify-items: center; gap: 8px; max-width: 560px; margin: 40px auto; border: 1px dashed var(--line); border-radius: 16px; background: #fff; padding: 48px 32px; text-align: center; }
.empty-icon { font-size: 40px; }
.empty-card h2 { color: var(--ink); font-size: 18px; }
.empty-card p { max-width: 420px; color: var(--muted); font-size: 13px; line-height: 1.7; }
.empty-card .btn { margin-top: 12px; }

/* Hero */
.rp-hero { display: flex; align-items: center; justify-content: space-between; gap: 24px; border: 1px solid #e2e8f2; border-radius: 16px; padding: 24px 26px; background: linear-gradient(135deg, #eef3ff 0%, #f8fafc 55%, #eef8f3 100%); }
.hero-kicker { color: var(--blue); font-size: 12px; font-weight: 750; }
.hero-copy h2 { margin-top: 6px; color: var(--ink); font-size: 22px; }
.hero-copy p { margin-top: 6px; color: var(--muted); font-size: 13px; line-height: 1.7; }
.hero-metrics { display: flex; gap: 10px; flex-shrink: 0; }
.hero-metrics > div { min-width: 84px; display: grid; gap: 3px; border: 1px solid rgb(255 255 255 / .8); border-radius: 12px; background: rgb(255 255 255 / .75); padding: 12px 16px; text-align: center; }
.hero-metrics span { color: var(--muted); font-size: 11px; }
.hero-metrics strong { color: var(--ink); font-size: 20px; }

/* 导航卡 */
.rp-nav { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.type-card { position: relative; display: flex; align-items: center; gap: 12px; border: 1px solid var(--line); border-radius: 14px; background: #fff; padding: 14px 16px; text-align: left; cursor: pointer; transition: border-color .15s ease, box-shadow .15s ease, transform .15s ease; }
.type-card:hover { transform: translateY(-1px); border-color: #c3cede; box-shadow: 0 6px 16px rgb(31 48 75 / .08); }
.type-card.active { border-color: var(--type); box-shadow: 0 6px 18px rgb(31 48 75 / .1); }
.type-card-icon { width: 40px; height: 40px; flex-shrink: 0; display: grid; place-items: center; border-radius: 11px; background: var(--type-soft); color: var(--type); font-size: 22px; }
.type-card-body { min-width: 0; display: grid; gap: 4px; }
.type-card-body strong { overflow: hidden; color: var(--ink); font-size: 13.5px; text-overflow: ellipsis; white-space: nowrap; }
.type-card-body small { color: var(--muted); font-size: 11.5px; }
.type-card-flag { margin-left: auto; color: #c2cddc; font-size: 20px; line-height: 1; }
.type-card.active .type-card-flag { color: var(--type); }
.tc-lecture { --type: #315fce; --type-soft: #e9efff; }
.tc-practice_guide { --type: #138560; --type-soft: #e9f7f1; }
.tc-graded_quiz { --type: #b96308; --type-soft: #fff3e2; }

/* 阅读区：正文恒宽 780px，目录作为固定右侧栏、不压缩正文 */
.reader-shell { display: grid; grid-template-columns: minmax(0, 780px); max-width: 780px; margin: 0 auto; }
.reader-shell.has-toc { grid-template-columns: minmax(0, 780px) 220px; max-width: 1030px; gap: 30px; justify-content: center; }
.reader { min-width: 0; border: 1px solid var(--line); border-top: 3px solid var(--type); border-radius: 16px; background: #fff; padding: 28px 32px 34px; box-shadow: 0 1px 2px rgb(16 24 40 / .03); }
.reader-lecture { --type: #315fce; --type-soft: #e9efff; }
.reader-practice_guide { --type: #138560; --type-soft: #e9f7f1; }
.reader-graded_quiz { --type: #b96308; --type-soft: #fff3e2; }

.reader-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; padding-bottom: 18px; border-bottom: 1px solid var(--line); }
.reader-title { display: flex; align-items: flex-start; gap: 13px; min-width: 0; }
.reader-icon { width: 44px; height: 44px; flex-shrink: 0; display: grid; place-items: center; border-radius: 12px; background: var(--type-soft, var(--soft)); color: var(--type, var(--blue)); font-size: 24px; }
.reader-kicker { color: var(--muted); font-size: 12px; }
.reader-title h1 { margin-top: 5px; color: var(--ink); font-size: 21px; line-height: 1.35; }
.reader-tools { display: flex; gap: 8px; flex-shrink: 0; }
.reader-body { margin-top: 20px; }

.reader-sources { margin-top: 26px; padding-top: 20px; border-top: 1px solid var(--line); }
.reader-sources h2 { color: var(--ink); font-size: 16px; margin-bottom: 6px; }
.reader-feedback { margin-top: 22px; border: 1px solid var(--line); border-radius: 12px; background: var(--soft); padding: 18px; }
.reader-feedback h2 { color: var(--ink); font-size: 15px; }
.reader-feedback p { margin-top: 6px; color: var(--muted); font-size: 12.5px; line-height: 1.6; }

/* 目录 */
.reader-toc { position: sticky; top: 96px; display: grid; gap: 2px; align-content: start; max-height: calc(100vh - 130px); overflow-y: auto; padding: 4px 0 4px 18px; border-left: 1px solid var(--line); }
.toc-title { margin-bottom: 8px; color: var(--muted); font-size: 11px; font-weight: 700; letter-spacing: .04em; }
.toc-link { border: 0; background: transparent; padding: 5px 8px; text-align: left; color: #5a6b81; font-size: 12.5px; line-height: 1.5; border-radius: 7px; cursor: pointer; }
.toc-link:hover { background: var(--soft); color: var(--ink); }
.toc-h1 { font-weight: 700; color: var(--ink); }
.toc-h2 { padding-left: 4px; }
.toc-h3 { padding-left: 16px; color: var(--muted); font-size: 12px; }
.toc-h4 { padding-left: 24px; color: var(--muted); font-size: 11.5px; }

/* 生成中 */
.generation-state { margin-bottom: 0; }
.progress-track { height: 8px; margin-top: 16px; overflow: hidden; border-radius: 4px; background: var(--soft); }
.progress-track i { display: block; height: 100%; background: var(--blue); transition: width .25s ease; }

/* AI 导学抽屉 */
.tutor-context { margin-bottom: 14px; color: var(--muted); font-size: 12px; line-height: 1.6; }
.tutor-state { display: grid; gap: 10px; place-items: start; min-height: 140px; color: var(--muted); font-size: 13px; line-height: 1.6; }
.tutor-error { color: var(--red); }
.tutor-error p { margin: 0; }
.tutor-messages { display: grid; gap: 12px; align-content: start; min-height: 220px; max-height: calc(100vh - 290px); overflow-y: auto; padding-right: 2px; }
.tutor-message { max-width: 92%; }
.tutor-message span { display: block; margin-bottom: 4px; color: var(--muted); font-size: 11px; font-weight: 650; }
.tutor-message :deep(.markdown-body) { border-radius: 10px; background: var(--soft); padding: 10px 12px; color: var(--ink); font-size: 13px; overflow-wrap: anywhere; }
.tutor-message :deep(.markdown-body > :first-child) { margin-top: 0; }
.tutor-message :deep(.markdown-body > :last-child) { margin-bottom: 0; }
.tutor-message.is-learner { justify-self: end; }
.tutor-message.is-learner span { text-align: right; }
.tutor-message.is-learner :deep(.markdown-body) { background: var(--blue2); color: #27457f; }
.tutor-cursor { display: inline-block; width: 7px; height: 14px; margin: 6px 0 0 8px; background: var(--blue); animation: tutor-blink 1s steps(2, start) infinite; vertical-align: middle; }
.tutor-stream-note { display: block; margin-top: 5px; color: var(--muted); font-size: 11px; }
.tutor-sources { display: block; margin-top: 5px; color: var(--muted); font-size: 11px; line-height: 1.5; }
.tutor-assessment { margin-top: 9px; border: 1px solid #cbd9f4; border-radius: 8px; background: #f5f8ff; padding: 10px; color: #27457f; font-size: 12px; line-height: 1.6; }
.tutor-assessment p { margin: 5px 0; background: transparent; padding: 0; color: inherit; }
.tutor-assessment small { color: #516788; }
.tutor-form { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 10px; align-items: end; }
.tutor-form textarea { width: 100%; min-height: 78px; resize: vertical; border: 1px solid var(--line); border-radius: 8px; padding: 9px 10px; color: var(--ink); line-height: 1.5; }
@keyframes tutor-blink { 50% { opacity: 0; } }

@media (max-width: 1100px) {
  .reader-shell.has-toc { grid-template-columns: minmax(0, 1fr); max-width: 780px; }
  .reader-toc { display: none; }
}
@media (max-width: 900px) {
  .rp-nav { grid-template-columns: 1fr; }
  .rp-hero { flex-direction: column; align-items: flex-start; }
}
@media (max-width: 480px) {
  .tutor-form { grid-template-columns: 1fr; }
  .tutor-messages { max-height: calc(100vh - 340px); }
  .reader { padding: 20px 18px 26px; }
  .reader-head { flex-direction: column; }
}
</style>
