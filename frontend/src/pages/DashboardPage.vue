<template>
  <section class="dashboard">
    <PageHeader
      :title="profileReady ? '首页' : '开始建立学习画像'"
      :description="profileReady ? '从当前节点继续学习，完成系统为你推荐的下一步。' : '填写学习背景并完成首次能力诊断后，系统才能生成个性化学习内容。'"
    >
      <template #actions>
        <label v-if="currentLearnerId && domainStore.domains.length" class="domain-picker">
          <span>学习领域</span>
          <select v-model="selectedDomainCode" class="field" :disabled="switchingDomain" @change="switchLearningDomain">
            <option value="" disabled>请选择领域</option>
            <option v-for="domain in domainStore.domains" :key="domain.domain_code" :value="domain.domain_code">{{ domain.name }}</option>
          </select>
        </label>
      </template>
    </PageHeader>

    <section v-if="loading" class="learning-stage loading-stage" aria-busy="true"><div class="loading-line wide"></div><div class="loading-line"></div><div class="loading-line short"></div></section>
    <section v-else-if="loadError" class="learning-stage stage-error" role="alert"><div class="stage-copy"><span class="stage-label">加载失败</span><h2>暂时无法读取学习状态</h2><p>{{ loadError }}</p><button class="btn primary" type="button" @click="loadDashboard">重新加载</button></div></section>
    <section v-else-if="currentLearnerId && !domainStore.currentDomainCode" class="learning-stage stage-error"><div class="stage-copy"><span class="stage-label">选择学习领域</span><h2>先选择本次学习使用的领域</h2><p>系统只展示已完成知识、题库和检索就绪检查的领域。选择后再建立该领域的独立学习画像。</p></div></section>
    <InitialProfileWizard v-else-if="!profileReady && currentLearnerId" :learner-id="currentLearnerId" @complete="completeOnboarding" />
    <section v-else-if="!currentLearnerId" class="learning-stage stage-error"><div class="stage-copy"><span class="stage-label">学习者未关联</span><h2>当前账号未关联学习者档案</h2><p>请重新登录或联系管理员完成账号配置。</p></div></section>

    <section v-else class="learning-stage" :class="`state-${dashboardState.kind}`">
      <div class="stage-copy">
        <template v-if="dashboardState.kind === 'assessment'">
          <span class="stage-label">建议下一步</span><h2>{{ primaryAction?.label || '开始你的首个学习包' }}</h2><p>{{ primaryAction?.description || '画像与路线已准备好，现在可以创建包含讲义、实操指南和分阶测试的学习包。' }}</p>
          <div class="assessment-facts"><span>诊断已完成</span><span>{{ profile?.weak_knowledge.length || 0 }} 项待巩固</span><span>{{ profile?.direction_tags.map(directionLabel).join('、') || '学习方向已确认' }}</span></div>
          <div class="stage-actions"><button class="btn primary stage-primary" type="button" :disabled="creatingGeneration && primaryAction?.type === 'generation'" @click="triggerPrimaryAction">{{ creatingGeneration && primaryAction?.type === 'generation' ? '正在创建学习包...' : primaryAction?.label || '创建学习包' }}</button><button class="btn" type="button" @click="openReport">查看学习报告</button></div>
        </template>
        <template v-else-if="dashboardState.kind === 'preparing'">
          <span class="stage-label">{{ dashboardState.feedbackTriggered ? '正在根据反馈调整学习内容' : '正在生成学习包' }}</span><h2>{{ dashboardState.task.decision === 'revision_required' ? '资源正在自动修订' : '正在准备个性化学习资源' }}</h2><p>检索、生成和自动质量校验会依次完成；仅达到质量门槛的资源会发布到学习资源页。</p><div class="task-progress"><span><i :style="{ width: `${progressValue}%` }"></i></span><strong>{{ progressValue }}%</strong></div><div class="stage-actions"><button class="btn" type="button" @click="openResources(dashboardState.task.task_id)">查看生成进度</button></div>
        </template>
        <template v-else-if="dashboardState.kind === 'resource'">
          <span class="stage-label">学习包已准备好</span><h2>{{ dashboardState.resource.title }}</h2><p>学习过程中可通过分阶测试、反馈和导学对话提供新的证据，系统会据此决定是否更新画像。</p><div class="resource-meta"><span>{{ resourceTypeLabel(dashboardState.resource.resource_type) }}</span><span>难度 {{ dashboardState.resource.difficulty }}/5</span><span>质量校验通过</span></div><div class="stage-actions"><button class="btn primary" type="button" @click="openResources()">开始学习</button><button class="btn" type="button" @click="openReport">查看学习报告</button></div>
        </template>
        <template v-else>
          <span class="stage-label">需要重新处理</span><h2>学习包尚未达到发布标准</h2><p>{{ dashboardState.task.failure_reason || '本次生成未通过质量门槛，未向学习者发布。' }}</p><div class="stage-actions"><button class="btn primary" type="button" :disabled="retrying" @click="retryTask(dashboardState.task.task_id)">{{ retrying ? '正在重新生成...' : '重新生成' }}</button></div>
        </template>
      </div>
      <div class="stage-visual" aria-hidden="true"><div class="visual-mark"></div><span>{{ visualLabel }}</span></div>
    </section>
    <section v-if="feedbackState" class="home-feedback-card">
      <div><span class="section-kicker">反馈处理状态</span><h2>{{ feedbackState.title }}</h2><p>{{ feedbackState.description }}</p></div>
      <button class="btn" type="button" @click="openResources()">查看学习资源</button>
    </section>
    <section v-if="report && pathNodes.length" class="home-route-card">
      <div class="home-route-head">
        <div><span class="section-kicker">当前学习路线</span><h2>已完成 {{ completedPathNodeCount }}/{{ pathNodes.length }} 个节点</h2><p>{{ currentPathNode ? '当前学习：' + currentPathNode.title + '；仅展示当前节点附近的学习安排。' : '当前路线已完成，可在学习报告查看完整记录。' }}</p></div>
        <button class="btn" type="button" @click="openReport">查看学习报告</button>
      </div>
      <div class="home-route-steps">
        <article v-for="node in visiblePathNodes" :key="node.path_node_id" class="home-route-step" :class="'node-' + node.status">
          <span>{{ node.path_order }}</span><div><strong>{{ node.title }}</strong><small>{{ pathStatusLabel(node.status) }}</small></div>
        </article>
      </div>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import InitialProfileWizard from '@/components/Onboarding/InitialProfileWizard.vue'
import PageHeader from '@/components/Shared/PageHeader.vue'
import { createGenerationTask, getActiveGenerationTask, listGenerationTasks, retryGenerationTask, type GenerationTaskDetail } from '@/api/generation'
import { getLearnerProfile, type LearnerProfileDetail } from '@/api/learners'
import { listResources, type ResourceSummary } from '@/api/resources'
import { getLearningReport, type LearningReport } from '@/api/reports'
import type { LearningPathNode } from '@/api/learningPaths'
import { getDomainReadiness } from '@/api/domains'
import { useToast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/authStore'
import { useProfileGateStore } from '@/stores/profileGateStore'
import { useDomainStore } from '@/stores/domainStore'
import { getDashboardState } from './dashboardState'
import { formatKnowledgeName } from '@/utils/knowledgeName'

const router = useRouter()
const authStore = useAuthStore()
const profileGate = useProfileGateStore()
const domainStore = useDomainStore()
const { showToast } = useToast()
const loading = ref(true)
const retrying = ref(false)
const switchingDomain = ref(false)
const creatingGeneration = ref(false)
const selectedDomainCode = ref('')
const loadError = ref('')
const profile = ref<LearnerProfileDetail | null>(null)
const activeTask = ref<GenerationTaskDetail | null>(null)
const recentTasks = ref<GenerationTaskDetail[]>([])
const resources = ref<ResourceSummary[]>([])
const report = ref<LearningReport | null>(null)
const currentLearnerId = computed(() => authStore.user?.learner_id || '')
const profileReady = computed(() => profile.value?.profile_status === 'ready')
const dashboardState = computed(() => getDashboardState(activeTask.value, resources.value, recentTasks.value))
const progressValue = computed(() => Math.min(100, Math.max(0, dashboardState.value.kind === 'preparing' ? dashboardState.value.task.progress ?? 0 : 0)))
const visualLabel = computed(() => ({ assessment: '路线已就绪', preparing: '正在处理', resource: '可以开始', failed: '需要重试' })[dashboardState.value.kind])
const pathNodes = computed<LearningPathNode[]>(() => report.value?.learning_path?.nodes || [])
const currentPathNode = computed(() => pathNodes.value.find(node => node.status === 'current'))
const completedPathNodeCount = computed(() => pathNodes.value.filter(node => node.status === 'completed').length)
const visiblePathNodes = computed(() => {
  const currentIndex = pathNodes.value.findIndex(node => node.status === 'current')
  if (currentIndex < 0) return pathNodes.value.slice(0, 5)
  return pathNodes.value.slice(Math.max(0, currentIndex - 1), currentIndex + 4)
})
const hasPublishedResources = computed(() => resources.value.some(resource => resource.review_status === 'passed'))
const primaryAction = computed(() => {
  const action = report.value?.next_actions?.[0] || null
  return action?.type === 'feedback' && !hasPublishedResources.value
    ? { type: 'generation', label: '生成个性化资源', description: '基于当前画像生成讲义、实操指南和分阶测试。', route: '/dashboard?intent=generate' }
    : action
})
const feedbackState = computed(() => {
  if (!hasPublishedResources.value) return null
  const action = report.value?.feedback_summary?.latest_action
  if (!action || action === 'no_change') return null
  return ({
    explain: { title: '已安排补救解释', description: '系统会围绕当前困惑补充更易理解的解释与练习。' },
    challenge: { title: '已安排进阶挑战', description: '系统已识别你的进阶需求，下一轮将提供更有挑战性的任务。' },
    review: { title: '资源正在复核', description: '系统正在根据反馈重新核验相关内容与知识来源。' },
    regenerate: { title: '资源正在调整', description: '系统会根据有效反馈生成更匹配当前水平的内容。' },
    ask_follow_up: { title: '等待补充学习证据', description: '系统需要更多作答或对话证据，再决定是否调整画像与路线。' },
    pending: { title: '反馈正在处理中', description: '系统正在理解你的反馈并判断是否需要调整学习内容。' },
  } as Record<string, { title: string; description: string }>)[action] || { title: '反馈已记录', description: '系统已记录本次反馈，并会在后续学习中作为调整依据。' }
})

async function loadDashboard() {
  const learnerId = currentLearnerId.value
  loading.value = true
  loadError.value = ''
  try {
    profile.value = learnerId ? await getLearnerProfile(learnerId) : null
    await domainStore.initialize(profile.value?.domain_code || '')
    selectedDomainCode.value = domainStore.currentDomainCode
    await profileGate.refresh(learnerId)
    if (!profileReady.value || !learnerId) { activeTask.value = null; recentTasks.value = []; resources.value = []; report.value = null; return }
    const domainCode = domainStore.currentDomainCode
    const [active, publishedResources, tasks, reportData] = await Promise.all([getActiveGenerationTask(learnerId), listResources({ learnerId, domainCode }), listGenerationTasks({ learnerId, domainCode, limit: 10 }), getLearningReport(learnerId).catch(() => null)])
    activeTask.value = active
    resources.value = publishedResources
    recentTasks.value = tasks
    report.value = reportData?.profile_ready ? reportData : null
  } catch { loadError.value = '请检查网络连接后重试。' } finally { loading.value = false }
}

async function completeOnboarding() { await loadDashboard() }
async function switchLearningDomain() {
  if (!currentLearnerId.value || !selectedDomainCode.value) return
  switchingDomain.value = true
  try {
    await domainStore.selectForLearner(currentLearnerId.value, selectedDomainCode.value)
    await loadDashboard()
  } catch {
    selectedDomainCode.value = domainStore.currentDomainCode
    loadError.value = '领域切换失败，请确认该领域仍处于已发布状态。'
  } finally { switchingDomain.value = false }
}
function openReport() { router.push({ path: '/report', query: { learner_id: currentLearnerId.value } }) }
function openResources(taskId?: string | null) { router.push({ path: '/resources', query: { learner_id: currentLearnerId.value, ...(taskId ? { task_id: taskId } : {}) } }) }
async function retryTask(taskId: string) { retrying.value = true; try { const task = await retryGenerationTask(taskId); activeTask.value = task; openResources(task.task_id) } catch { loadError.value = '重新生成失败，请稍后再试。' } finally { retrying.value = false } }
function pathStatusLabel(status: LearningPathNode['status']) { return ({ locked: '未解锁', current: '当前学习', completed: '已完成', skipped: '已跳过' } as const)[status] }
function triggerPrimaryAction() { if (primaryAction.value) void handleNextAction(primaryAction.value); else openReport() }
async function handleNextAction(action: LearningReport['next_actions'][number]) {
  if (action.type !== 'generation') { router.push(action.route); return }
  if (!report.value?.profile_id || !currentLearnerId.value) return
  creatingGeneration.value = true
  try {
    const readiness = await getDomainReadiness(report.value.domain_code)
    if (!readiness.generation_ready) {
      showToast('当前领域尚未满足生成条件：' + (readiness.runtime_reasons?.join('、') || 'Candidate RAG 未就绪'), 'error')
      return
    }
    const task = await createGenerationTask(report.value.domain_code, report.value.profile_id, currentLearnerId.value)
    openResources(task.task_id)
  } catch { showToast('创建学习包失败，请确认画像状态和生成环境后重试。', 'error') }
  finally { creatingGeneration.value = false }
}
function resourceTypeLabel(type: string) { return ({ lecture: '讲义', practice_guide: '实操指南', graded_quiz: '测试题' } as Record<string, string>)[type] || type }
function directionLabel(value: string) { return ({ llm_application: '大模型应用', prompt_engineering: 'Prompt 工程', rag_knowledge_base: 'RAG 知识库', agent_orchestration: 'Agent 编排' } as Record<string, string>)[value] || (value.startsWith('direction_') ? '专项学习方向' : formatKnowledgeName(value)) }
onMounted(loadDashboard)
</script>

<style scoped>
.dashboard { display: grid; width: 100%; gap: 18px; }.learning-stage { position: relative; display: grid; grid-template-columns: minmax(0, 1fr) 230px; min-height: 360px; overflow: hidden; border: 1px solid var(--line); border-radius: var(--radius-panel); background: var(--panel); }.stage-copy { display: grid; align-content: center; justify-items: start; gap: 14px; padding: 48px 54px; }.stage-label { color: var(--blue); font-size: 12px; font-weight: 750; }.stage-copy h2 { max-width: 620px; margin: 0; color: var(--ink); font-size: 30px; line-height: 1.3; text-wrap: balance; }.stage-copy > p { max-width: 560px; margin: 0; color: var(--muted); font-size: 14px; line-height: 1.75; text-wrap: pretty; }.stage-actions { display: flex; flex-wrap: wrap; gap: 9px; margin-top: 8px; }.stage-actions .btn { min-width: 112px; }.stage-primary { min-height: 42px; padding-inline: 18px; }.assessment-facts,.resource-meta { display: flex; flex-wrap: wrap; gap: 8px; }.assessment-facts span,.resource-meta span { border: 1px solid var(--line); border-radius: 6px; background: var(--soft); padding: 5px 8px; color: var(--body); font-size: 12px; }.stage-visual { display: grid; place-content: center; gap: 12px; border-left: 1px solid var(--line); background: var(--soft); color: var(--body); font-size: 12px; font-weight: 700; text-align: center; }.visual-mark { width: 48px; height: 48px; margin: auto; border: 10px solid var(--visual-ring); border-top-color: var(--blue); border-radius: 50%; }.state-assessment .stage-visual { background: var(--blue2); color: var(--info); }.state-resource .stage-visual { background: var(--green2); color: var(--green); }.state-failed .stage-visual { background: var(--amber2); color: #8b4c0b; }.task-progress { display: grid; grid-template-columns: minmax(180px, 340px) auto; align-items: center; gap: 10px; width: 100%; margin-top: 2px; }.task-progress > span { display: block; height: 7px; overflow: hidden; border-radius: 5px; background: var(--track); }.task-progress i { display: block; height: 100%; border-radius: inherit; background: var(--blue); }.task-progress strong { color: var(--body); font-size: 12px; }.stage-error { display: block; min-height: 280px; border-color: #edc9c9; background: var(--red2); }.stage-error .stage-label { color: var(--red); }.loading-stage { display: grid; align-content: center; gap: 14px; padding: 48px 54px; }.loading-line { width: min(420px, 76%); height: 14px; border-radius: 5px; background: var(--track); }.loading-line.wide { width: min(520px, 92%); height: 32px; }.loading-line.short { width: 132px; height: 40px; margin-top: 10px; background: var(--blue2); }@media (max-width: 760px) { .learning-stage { grid-template-columns: 1fr; min-height: 0; }.stage-copy { padding: 34px 26px; }.stage-copy h2 { font-size: 25px; }.stage-visual { min-height: 96px; border-top: 1px solid var(--line); border-left: 0; }.visual-mark { width: 32px; height: 32px; border-width: 7px; }.task-progress { grid-template-columns: minmax(0, 1fr) auto; } }@media (max-width: 480px) { .dashboard { gap: 16px; }.stage-copy { padding: 28px 20px; }.stage-actions { display: grid; width: 100%; }.stage-actions .btn { width: 100%; min-height: 44px; } }
.domain-picker { display: flex; align-items: center; gap: 8px; color: var(--muted); font-size: 12px; }
.domain-picker select { min-width: 180px; }
.section-kicker { color: var(--blue); font-size: 12px; font-weight: 750; }
.home-feedback-card,.home-route-card { border: 1px solid var(--line); border-radius: var(--radius-panel); background: var(--panel); padding: 22px 24px; }
.home-feedback-card { display: flex; align-items: center; justify-content: space-between; gap: 20px; border-color: #c8e4d7; background: var(--green2); }
.home-feedback-card h2,.home-route-card h2 { margin: 5px 0 0; color: var(--ink); font-size: 19px; }
.home-feedback-card p,.home-route-card p { margin: 6px 0 0; color: var(--muted); font-size: 13px; line-height: 1.65; }
.home-route-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.home-route-steps { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; margin-top: 18px; }
.home-route-step { display: flex; align-items: flex-start; gap: 10px; border: 1px solid var(--line); border-radius: 10px; background: var(--soft); padding: 11px 12px; }
.home-route-step > span { display: grid; width: 24px; height: 24px; flex-shrink: 0; place-items: center; border-radius: 50%; background: var(--track); color: var(--muted); font-size: 11px; font-weight: 750; }
.home-route-step div { display: grid; min-width: 0; gap: 4px; }
.home-route-step strong { color: var(--ink); font-size: 12px; line-height: 1.45; }
.home-route-step small { color: var(--muted); font-size: 11px; }
.home-route-step.node-current { border-color: #b9caeb; background: var(--blue2); }
.home-route-step.node-current > span { background: var(--blue); color: #fff; }
.home-route-step.node-completed { border-color: #cfe7d8; background: var(--green2); }
.home-route-step.node-completed > span { background: var(--green); color: #fff; }
.home-route-step.node-locked { opacity: .68; }
:global(.app.theme-dark) .home-feedback-card { border-color: #34765f; background: var(--green2); }
:global(.app.theme-dark) .home-route-step.node-current { border-color: #4b6fa9; }
:global(.app.theme-dark) .home-route-step.node-completed { border-color: #34765f; }
@media (max-width: 760px) { .home-feedback-card { align-items: flex-start; flex-direction: column; }.home-route-head { align-items: flex-start; flex-direction: column; } }
@media (max-width: 480px) { .home-feedback-card .btn { width: 100%; min-height: 44px; }.home-feedback-card,.home-route-card { padding: 20px; } }
</style>
