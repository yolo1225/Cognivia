<template>
  <section class="dashboard">
    <PageHeader
      :title="profileReady ? '学习中心' : '开始建立学习画像'"
      :description="profileReady ? '查看当前学习状态，继续完成下一步学习任务。' : '填写学习背景并完成首次能力诊断后，系统才能生成个性化学习内容。'"
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
          <span class="stage-label">画像与路线已就绪</span><h2>{{ profile?.profile_type ? profileTypeLabel(profile.profile_type) : '你的初始学习画像已生成' }}</h2><p>请先查看能力画像和学习路线，确认后再创建包含讲义、实操指南和分阶测试的学习包。</p>
          <div class="assessment-facts"><span>诊断已完成</span><span>{{ profile?.weak_knowledge.length || 0 }} 项待巩固</span><span>{{ profile?.direction_tags.map(directionLabel).join('、') || '学习方向已确认' }}</span></div>
          <div class="stage-actions"><button class="btn primary stage-primary" type="button" @click="openReport">查看画像与学习路线</button></div>
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
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import InitialProfileWizard from '@/components/Onboarding/InitialProfileWizard.vue'
import PageHeader from '@/components/Shared/PageHeader.vue'
import { getActiveGenerationTask, listGenerationTasks, retryGenerationTask, type GenerationTaskDetail } from '@/api/generation'
import { getLearnerProfile, type LearnerProfileDetail } from '@/api/learners'
import { listResources, type ResourceSummary } from '@/api/resources'
import { useAuthStore } from '@/stores/authStore'
import { useProfileGateStore } from '@/stores/profileGateStore'
import { useDomainStore } from '@/stores/domainStore'
import { getDashboardState } from './dashboardState'

const router = useRouter()
const authStore = useAuthStore()
const profileGate = useProfileGateStore()
const domainStore = useDomainStore()
const loading = ref(true)
const retrying = ref(false)
const switchingDomain = ref(false)
const selectedDomainCode = ref('')
const loadError = ref('')
const profile = ref<LearnerProfileDetail | null>(null)
const activeTask = ref<GenerationTaskDetail | null>(null)
const recentTasks = ref<GenerationTaskDetail[]>([])
const resources = ref<ResourceSummary[]>([])
const currentLearnerId = computed(() => authStore.user?.learner_id || '')
const profileReady = computed(() => profile.value?.profile_status === 'ready')
const dashboardState = computed(() => getDashboardState(activeTask.value, resources.value, recentTasks.value))
const progressValue = computed(() => Math.min(100, Math.max(0, dashboardState.value.kind === 'preparing' ? dashboardState.value.task.progress ?? 0 : 0)))
const visualLabel = computed(() => ({ assessment: '路线已就绪', preparing: '正在处理', resource: '可以开始', failed: '需要重试' })[dashboardState.value.kind])

async function loadDashboard() {
  const learnerId = currentLearnerId.value
  loading.value = true
  loadError.value = ''
  try {
    profile.value = learnerId ? await getLearnerProfile(learnerId) : null
    await domainStore.initialize(profile.value?.domain_code || '')
    selectedDomainCode.value = domainStore.currentDomainCode
    await profileGate.refresh(learnerId)
    if (!profileReady.value || !learnerId) { activeTask.value = null; recentTasks.value = []; resources.value = []; return }
    const domainCode = domainStore.currentDomainCode
    const [active, publishedResources, tasks] = await Promise.all([getActiveGenerationTask(learnerId), listResources({ learnerId, domainCode }), listGenerationTasks({ learnerId, domainCode, limit: 10 })])
    activeTask.value = active
    resources.value = publishedResources
    recentTasks.value = tasks
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
function resourceTypeLabel(type: string) { return ({ lecture: '讲义', practice_guide: '实操指南', graded_quiz: '测试题' } as Record<string, string>)[type] || type }
function profileTypeLabel(type: string) { return ({ beginner: '基础起步型学习者', intermediate: '进阶提升型学习者', advanced: '综合应用型学习者', practice_oriented: '实操导向型学习者' } as Record<string, string>)[type] || '个性化学习画像' }
function directionLabel(value: string) { return ({ llm_application: '大模型应用', prompt_engineering: 'Prompt 工程', rag_knowledge_base: 'RAG 知识库', agent_orchestration: 'Agent 编排' } as Record<string, string>)[value] || value }
onMounted(loadDashboard)
</script>

<style scoped>
.dashboard { display: grid; width: 100%; gap: 18px; }.learning-stage { position: relative; display: grid; grid-template-columns: minmax(0, 1fr) 230px; min-height: 360px; overflow: hidden; border: 1px solid var(--line); border-radius: var(--radius-panel); background: #fff; }.stage-copy { display: grid; align-content: center; justify-items: start; gap: 14px; padding: 48px 54px; }.stage-label { color: var(--blue); font-size: 12px; font-weight: 750; }.stage-copy h2 { max-width: 620px; margin: 0; color: var(--ink); font-size: 30px; line-height: 1.3; text-wrap: balance; }.stage-copy > p { max-width: 560px; margin: 0; color: var(--muted); font-size: 14px; line-height: 1.75; text-wrap: pretty; }.stage-actions { display: flex; flex-wrap: wrap; gap: 9px; margin-top: 8px; }.stage-actions .btn { min-width: 112px; }.stage-primary { min-height: 42px; padding-inline: 18px; }.assessment-facts,.resource-meta { display: flex; flex-wrap: wrap; gap: 8px; }.assessment-facts span,.resource-meta span { border: 1px solid var(--line); border-radius: 6px; background: var(--soft); padding: 5px 8px; color: #405067; font-size: 12px; }.stage-visual { display: grid; place-content: center; gap: 12px; border-left: 1px solid var(--line); background: #f4f7fb; color: #405067; font-size: 12px; font-weight: 700; text-align: center; }.visual-mark { width: 48px; height: 48px; margin: auto; border: 10px solid #dce7ff; border-top-color: var(--blue); border-radius: 50%; }.state-assessment .stage-visual { background: #eef3ff; color: #27457f; }.state-resource .stage-visual { background: #eef8f3; color: #176346; }.state-failed .stage-visual { background: #fff7ed; color: #8b4c0b; }.task-progress { display: grid; grid-template-columns: minmax(180px, 340px) auto; align-items: center; gap: 10px; width: 100%; margin-top: 2px; }.task-progress > span { display: block; height: 7px; overflow: hidden; border-radius: 5px; background: #dce4ee; }.task-progress i { display: block; height: 100%; border-radius: inherit; background: var(--blue); }.task-progress strong { color: #405067; font-size: 12px; }.stage-error { display: block; min-height: 280px; border-color: #edc9c9; background: #fffafa; }.stage-error .stage-label { color: var(--red); }.loading-stage { display: grid; align-content: center; gap: 14px; padding: 48px 54px; }.loading-line { width: min(420px, 76%); height: 14px; border-radius: 5px; background: #e9eef5; }.loading-line.wide { width: min(520px, 92%); height: 32px; }.loading-line.short { width: 132px; height: 40px; margin-top: 10px; background: #dce7ff; }@media (max-width: 760px) { .learning-stage { grid-template-columns: 1fr; min-height: 0; }.stage-copy { padding: 34px 26px; }.stage-copy h2 { font-size: 25px; }.stage-visual { min-height: 96px; border-top: 1px solid var(--line); border-left: 0; }.visual-mark { width: 32px; height: 32px; border-width: 7px; }.task-progress { grid-template-columns: minmax(0, 1fr) auto; } }@media (max-width: 480px) { .dashboard { gap: 16px; }.stage-copy { padding: 28px 20px; }.stage-actions { display: grid; width: 100%; }.stage-actions .btn { width: 100%; min-height: 44px; } }
.domain-picker { display: flex; align-items: center; gap: 8px; color: var(--muted); font-size: 12px; }
.domain-picker select { min-width: 180px; }
</style>
