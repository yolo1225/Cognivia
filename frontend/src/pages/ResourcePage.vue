<template>
  <section class="page">
    <div class="head">
      <div><h1>个性化学习资源</h1><p class="sub">完成诊断测评后，系统将根据画像生成个性化学习资源。</p></div>
      <div class="actions">
        <button class="btn" @click="loadResources" :disabled="loading">刷新资源</button>
        <button class="btn" :disabled="!canTutor" @click="openTutor">AI 导学</button>
        <button class="btn primary" @click="router.push('/diagnostic')">去诊断训练</button>
      </div>
    </div>

    <div v-if="loading" class="panel" style="text-align:center;padding:40px;color:var(--muted)">加载中...</div>

    <div v-else-if="errorMessage" class="error-state"><strong>资源加载失败</strong><p>{{ errorMessage }}</p><button class="btn" @click="loadResources">重新加载</button></div>

    <div v-else-if="resources.length === 0" class="panel" style="text-align:center;padding:60px;color:var(--muted)">
      <div style="font-size:36px;margin-bottom:12px">📚</div>
      <strong style="display:block;color:var(--ink);font-size:17px">暂无学习资源</strong>
      <p class="sub" style="margin-top:8px">
        请先完成<span style="color:var(--blue)">诊断训练</span>，系统将根据你的答题情况分析知识薄弱点，<br>然后<span style="color:var(--blue)">生成个性化学习资源</span>（讲义、实操指南、分阶测试）。
      </p>
      <button class="btn primary" style="margin-top:18px" @click="router.push('/diagnostic')">开始诊断训练</button>
    </div>

    <template v-else>
      <div class="panel" style="margin-bottom:14px">
        <div class="panel-head"><div><h2>学习资源列表</h2><p class="sub">针对诊断结果生成的个性化资源</p></div><span class="status ok">{{ resources.length }} 份</span></div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <button v-for="(r,i) in resources" :key="r.resource_id" class="resource-tab" :class="{ active: selectedIdx === i }" style="flex:1;min-width:180px" @click="selectedIdx = i">
            <strong>{{ r.title }}</strong><small>{{ r.resource_type }} · 难度 {{ r.difficulty }}</small>
          </button>
        </div>
      </div>

      <article v-if="selected" class="panel">
        <div class="trust">
          <span class="status" :class="selected.review_status === 'passed' ? 'ok' : 'wait'">{{ selected.review_status === 'passed' ? '✓ 已通过审核' : '待审核' }}</span>
          <span class="tag">难度 {{ selected.difficulty }}/5</span>
          <span class="tag">引用 {{ selected.sources.length }} 条</span>
          <span class="tag">资源 v{{ selected.version || 1 }}</span>
          <button class="btn" :disabled="!canTutor" @click="openTutor">AI 导学</button>
          <button class="btn" style="margin-left:auto" @click="exportDialog?.open()">导出资源</button>
        </div>
        <div class="article">
          <h1 style="font-size:24px;margin-top:18px">{{ selected.title }}</h1>
          <p class="sub">资源类型：{{ selected.resource_type }} · 审核状态：{{ selected.review_status }} · 生成任务：{{ selected.generation_task_id || '-' }}</p>
          <h2>知识来源</h2>
          <div v-for="s in selected.source_details || []" :key="s.knowledge_id" class="source">
            <strong>{{ s.name }}</strong><span>{{ s.source_title }}</span>
          </div>
          <div v-if="selected.content" class="resource-content">{{ selected.content }}</div>
        </div>
        <div class="panel feedback-panel">
          <h2>学习反馈</h2><p class="sub">反馈将触发补救解释、挑战任务或资源复核，不会直接覆盖学习画像。</p>
          <div class="chips"><button v-for="item in feedbackOptions" :key="item.value" class="chip" :disabled="feedbackSubmitting" @click="sendFeedback(item.value)">{{ item.label }}</button></div>
        </div>
      </article>
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
import { ref, computed, nextTick, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useToast } from '@/composables/useToast'
import { listResources, exportResource, submitFeedback, type ResourceSummary } from '@/api/resources'
import AppDialog from '@/components/Shared/AppDialog.vue'
import AppDrawer from '@/components/Shared/AppDrawer.vue'
import { createTutoringSession, getTutoringSession, pauseTutoringMessage, streamTutoringMessage, type TutoringSession } from '@/api/tutoring'
import ResourceMarkdownViewer from '@/components/ResourceViewer/ResourceMarkdownViewer.vue'

const router = useRouter()
const route = useRoute()
const { showToast } = useToast()
const loading = ref(false)
const resources = ref<ResourceSummary[]>([])
const selectedIdx = ref(0)
const exportFormat = ref('markdown')
const exportDialog = ref<InstanceType<typeof AppDialog> | null>(null)
const errorMessage = ref('')
const feedbackSubmitting = ref(false)
const tutorOpen = ref(false)
const tutorLoading = ref(false)
const tutorSending = ref(false)
const tutorError = ref('')
const tutorDraft = ref('')
const tutorSession = ref<TutoringSession | null>(null)
const messageList = ref<HTMLElement | null>(null)
let streamController: AbortController | null = null
let activeReplyId = ''
const feedbackOptions = [{value:'too_hard',label:'内容太难'},{value:'too_easy',label:'内容太简单'},{value:'confusing',label:'解释不清楚'},{value:'incorrect',label:'内容可能有误'},{value:'helpful',label:'对我有帮助'}]
const formats = [
  { value: 'markdown', label: 'Markdown', desc: '保留标题、表格、代码块和知识来源结构。', tag: '源格式' },
  { value: 'pdf', label: 'PDF', desc: '适合阅读、打印和提交。', tag: '推荐' },
]

const selected = computed(() => resources.value[selectedIdx.value] || null)
const canTutor = computed(() => Boolean(selected.value && selected.value.review_status === 'passed' && selected.value.is_current !== false))
const tutorMessages = computed(() => tutorSession.value?.messages || [])

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
    tutorSession.value = await createTutoringSession(selected.value.resource_id)
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
  if (tutorOpen.value) openTutor()
})

async function loadResources() {
  loading.value = true
  errorMessage.value = ''
  try {
    resources.value = await listResources({ taskId: String(route.query.task_id || '') || undefined, learnerId: 'learner_001', domainCode: 'ai_app_dev' })
  } catch {
    errorMessage.value = '无法读取学习资源，请确认后端服务可用。'
  } finally {
    loading.value = false
  }
}

async function sendFeedback(type: string) {
  if (!selected.value) return
  feedbackSubmitting.value = true
  try { const result = await submitFeedback(selected.value.resource_id, type); showToast(`反馈已记录：${String((result as any).decision_reason || (result as any).recommended_action || '系统将按证据处理')}`) }
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

onMounted(loadResources)
</script>

<style scoped>
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
@media (max-width: 480px) { .tutor-form { grid-template-columns: 1fr; } .tutor-messages { max-height: calc(100vh - 340px); } }
@keyframes tutor-blink { 50% { opacity: 0; } }
</style>
