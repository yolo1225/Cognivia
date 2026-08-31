<template>
  <section class="page resource-page">
    <PageHeader title="学习资源" description="围绕当前学习节点完成讲义、实操与测验。">
      <template #actions>
        <button type="button" class="icon-btn refresh-btn" :disabled="loading" :aria-busy="loading" :title="loading ? '正在刷新资源' : '刷新资源'" :aria-label="loading ? '正在刷新资源' : '刷新资源'" @click="loadResources"><AppIcon name="refresh" /></button>
        <button v-if="canExportPackage" type="button" class="btn primary" :disabled="exportingPackage" :aria-busy="exportingPackage" @click="packageExportDialog?.open()">{{ exportingPackage ? '正在导出' : '导出学习包' }}</button>
        <button type="button" class="btn report-btn" @click="openReport">查看学情画像</button>
      </template>
    </PageHeader>

    <section v-if="pathNodeTitle || nodeGate" class="learning-overview" aria-label="当前学习单元">
      <div class="overview-head">
        <div>
          <span class="overview-kicker">当前学习单元</span>
          <h2>第 {{ pathNodeOrder }} 节 · {{ pathNodeTitle || '当前学习任务' }}</h2>
        </div>
        <div v-if="nodeGate" class="mastery-count" :class="{ complete: nodeGate.can_advance }">
          <span>{{ nodeGate.can_advance ? '本节已达标' : '核心知识' }}</span>
          <strong>{{ nodeGate.mastered_knowledge_count || 0 }}<small>/{{ nodeGate.core_knowledge_count || 0 }}</small></strong>
        </div>
      </div>
      <MetricStrip
        v-if="packageQuality && resources.length && !isShowingProgress && taskDetail?.status !== 'failed'"
        class="package-quality-strip"
        :items="packageQualityMetrics"
      />
      <details v-if="generationBasis" class="overview-evidence">
        <summary>查看本节学习依据</summary>
        <div>
          <p><strong>核心知识：</strong>{{ generationBasis.core_knowledge.map(item => item.name).join('、') || pathNodeTitle }}</p>
          <p><strong>前置准备：</strong>{{ prerequisiteNames }}</p>
        </div>
      </details>
    </section>

    <div v-if="isShowingProgress" class="panel generation-state">
      <strong>{{ generationStatusTitle }}</strong>
      <p class="sub">{{ generationStatusDescription }}</p>
      <div class="progress-track"><i :style="{ width: `${taskDetail?.progress || 5}%` }"></i></div>
    </div>

    <div v-else-if="taskDetail?.status === 'failed'" class="error-state">
      <strong>{{ generationFailureTitle }}</strong>
      <p>{{ generationFailureDescription }}</p>
      <dl v-if="isContentPolicyFailure" class="failure-details">
        <div v-if="failedResourceLabels"><dt>失败资源</dt><dd>{{ failedResourceLabels }}</dd></div>
        <div v-if="failedFieldPaths"><dt>未通过字段</dt><dd>{{ failedFieldPaths }}</dd></div>
        <div><dt>处理建议</dt><dd>补充与目标知识点相关的实操材料并重建索引，或使用系统的安全概念练习降级。</dd></div>
      </dl>
      <QualityMetrics v-if="taskDetail.package_quality" :metrics="taskDetail.package_quality" />
      <button class="btn primary" :disabled="retrying" @click="retryTask">{{ retrying ? '重新生成中...' : '重新生成' }}</button>
    </div>

    <section v-if="knowledgeImpact && isViewingPackageWithImpact && !isShowingProgress" class="knowledge-impact" :class="knowledgeImpact.status">
      <div>
        <strong>知识库更新影响{{ taskId ? '该学习包' : '' }} {{ knowledgeImpact.affected_resource_count }} 份资源</strong>
        <p v-if="taskId && knowledgeImpact.status === 'resolved'">该学习包的受影响资源已在后续学习包中更新，此处仅保留历史记录。</p>
        <p v-else-if="taskId && !canManageKnowledgeImpact">该学习包受到知识库更新影响，但它已不是当前学习包，此处仅保留历史记录。</p>
        <p v-else-if="knowledgeImpact.index_status === 'updating'">向量索引正在更新，完成后可生成新的学习包。现有资源仍可继续使用。</p>
        <p v-else-if="knowledgeImpact.status === 'dismissed'">你已选择暂不更新；现有资源继续可用，也可以随时生成新的学习包。</p>
        <p v-else>只重新生成受影响资源，未受影响资源将直接继承到新的学习包。</p>
      </div>
      <div v-if="canManageKnowledgeImpact" class="impact-actions">
        <button v-if="knowledgeImpact.status === 'pending'" class="btn" :disabled="impactSubmitting" @click="dismissImpact">暂不更新</button>
        <button class="btn primary" :disabled="impactSubmitting || !knowledgeImpact.refresh_available" @click="refreshImpact">{{ impactSubmitting ? '正在处理...' : knowledgeImpact.index_status === 'updating' ? '等待索引更新' : `更新受影响的 ${knowledgeImpact.affected_resource_count} 份资源` }}</button>
      </div>
    </section>

    <PageState v-if="loading" type="loading" title="正在加载学习资源" />

    <div v-else-if="errorMessage" class="error-state"><strong>资源加载失败</strong><p>{{ errorMessage }}</p><button class="btn" @click="loadResources">重新加载</button></div>

    <div v-else-if="taskDetail?.status !== 'failed' && resources.length === 0" class="empty-card">
      <div class="empty-icon"><AppIcon name="resources" /></div>
      <h2>暂无学习资源</h2>
      <p>请先在首页查看当前学习路线，并按“建议下一步”创建个性化学习包（讲义、实操指南、分阶测试）。</p>
      <button class="btn primary" @click="router.push('/dashboard')">返回首页</button>
    </div>

    <template v-else-if="taskDetail?.status !== 'failed'">
      <nav v-if="resources.length" class="resource-switcher" aria-label="切换学习资源">
        <button
          v-for="(resource, index) in resources"
          :key="resource.resource_id"
          type="button"
          class="resource-switcher-item"
          :class="[`switch-${resource.resource_type}`, { active: selectedIdx === index }]"
          :aria-current="selectedIdx === index ? 'page' : undefined"
          @click="selectedIdx = index"
        >
          <span class="switch-step">{{ resourceStep(resource.resource_type).order }}</span>
          <span class="switch-icon"><ResourceTypeIcon :type="resource.resource_type" /></span>
          <span class="switch-copy">
            <strong>{{ resourceStep(resource.resource_type).label }}</strong>
            <small>{{ resourceStep(resource.resource_type).hint }} · 难度 {{ resource.difficulty }}/5</small>
          </span>
        </button>
      </nav>

      <div v-if="selected" class="reader-shell" :class="{ 'has-toc': showToc }">
        <main class="reader" :class="`reader-${selected.resource_type}`">
          <header class="reader-head">
            <div class="reader-title">
              <span class="reader-icon"><ResourceTypeIcon :type="selected.resource_type" /></span>
              <div>
                <div class="reader-meta">
                  <span>{{ typeLabel(selected.resource_type) }}</span>
                  <span>难度 {{ selected.difficulty }}/5</span>
                  <span>{{ resourceQualityStatusLabel(selected.review_status) }}</span>
                  <span v-if="selected.freshness_status === 'knowledge_changed'">知识库已更新</span>
                  <span v-else-if="selected.membership_type === 'inherited'">沿用上一学习包</span>
                </div>
                <h1>{{ selected.title }}</h1>
              </div>
            </div>
            <div class="reader-tools">
              <button class="tutor-trigger" :disabled="!canTutor" @click="openTutor">
                <span class="tutor-trigger-icon"><AppIcon name="sparkles" /></span>
                <span><strong>AI 导学</strong><small>针对本页资源</small></span>
              </button>
              <button class="btn" @click="exportDialog?.open()">导出</button>
            </div>
          </header>

          <details v-if="selected.quality_metrics" class="resource-assurance">
            <summary>
              <span class="assurance-mark">✓</span>
              <span><strong>本资源已通过质量校验</strong><small>难度适配与知识覆盖均已检查</small></span>
              <span class="assurance-action">查看详情</span>
            </summary>
            <QualityMetrics :metrics="selected.quality_metrics" show-details />
          </details>

          <div class="reader-body">
            <GradedQuizViewer
              v-if="quizContent"
              :key="`${selected.resource_id}:${selected.version || 1}`"
              :content="quizContent"
              :learner-id="currentLearnerId"
              :resource-id="selected.resource_id"
              :resource-version="selected.version"
              :knowledge-labels="knowledgeLabels"
            />
            <ResourceMarkdownViewer v-else-if="bodyContent" :content="bodyContent" collapsible :open-headings="2" @headings="onHeadings" />
          </div>

          <section v-if="sourceDetails.length" class="learning-basis">
            <div class="learning-basis-head">
              <div>
                <span>关联知识点</span>
                <h2>本资源涉及的核心内容</h2>
              </div>
              <small>{{ sourceDetails.length }} 个知识点</small>
            </div>
            <div class="learning-basis-list">
              <div v-for="(source, index) in sourceDetails" :key="source.knowledge_id" class="learning-basis-item">
                <span>{{ String(index + 1).padStart(2, '0') }}</span>
                <strong>{{ source.name }}</strong>
              </div>
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
        <button class="btn primary" :disabled="exportingResource" @click="doExport">{{ exportingResource ? '正在导出...' : '导出资源' }}</button>
      </template>
    </AppDialog>

    <AppDialog ref="packageExportDialog" title="导出学习包" subtitle="讲义、实操指南和无答案测验将使用同一种格式打包为 ZIP。">
      <label v-for="f in formats" :key="f.value" class="export-row">
        <input type="radio" name="package-fmt" :value="f.value" v-model="packageExportFormat" />
        <span><strong>{{ f.label }}</strong><small>{{ f.desc }}</small></span><span class="tag">统一格式</span>
      </label>
      <template #footer>
        <button class="btn" :disabled="exportingPackage" @click="packageExportDialog?.close()">取消</button>
        <button class="btn primary" :disabled="exportingPackage" @click="doExportPackage">{{ exportingPackage ? '正在打包...' : '下载 ZIP 学习包' }}</button>
      </template>
    </AppDialog>

    <AppDrawer v-model="tutorOpen" title="AI 导学" :subtitle="selected?.title || '请选择学习资源'">
      <div :key="tutorSession?.session_id || selected?.resource_id || 'no-resource'" class="tutor-panel-content">
      <div class="tutor-context"><span class="tutor-context-icon"><AppIcon name="resources" /></span><span>{{ pathNodeTitle || '当前节点' }} · {{ selected ? typeLabel(selected.resource_type) : '当前资源' }}导学</span></div>
      <div v-if="tutorLoading" class="tutor-state tutor-loading" role="status"><span></span><span></span><span></span><p>正在加载导学记录</p></div>
      <div v-else-if="tutorError" class="tutor-state tutor-error"><p>{{ tutorError }}</p><button class="btn" @click="openTutor">重新加载</button></div>
      <div v-else-if="tutorMessages.length === 0 && !nodeAssessment" class="tutor-state tutor-empty"><span class="tutor-empty-icon"><AppIcon name="sparkles" /></span><strong>围绕当前资源开始导学</strong><p>概念解释、步骤拆解和练习建议都会保存在本资源的导学记录中。</p><div class="tutor-suggestions"><button type="button" :disabled="tutorSending" @click="askTutor('请用更容易理解的方式解释当前资源的核心内容。')">解释核心内容</button><button type="button" :disabled="tutorSending" @click="askTutor('请带我拆解当前资源中的关键步骤，并说明容易出错的地方。')">拆解关键步骤</button><button type="button" :disabled="tutorSending" @click="askTutor('请针对当前资源出一道练习题，并在我作答后点评。')">来一道练习</button></div></div>
      <div v-else ref="messageList" class="tutor-messages" aria-live="polite">
        <article v-if="nodeAssessment && !assessmentInMessages" class="tutor-message is-agent node-adjustment-message">
          <div class="tutor-message-meta"><span class="tutor-avatar" aria-hidden="true">AI</span><span>节点学习判断</span></div>
          <TutoringAssessmentCard :assessment="nodeAssessment" :submitting="assessmentSubmitting === nodeAssessment.assessment_id" :resource-submitting="resourceDecisionSubmitting === nodeAssessment.adjustment_proposal_id" pending-hint="验证结果将作用于当前节点，不会合并其他资源的对话内容。" @answer="answerAssessment(nodeAssessment, $event)" @resource-decision="decideAssessmentResource(nodeAssessment, $event)" />
        </article>
        <article v-for="message in tutorMessages" :key="message.message_id" class="tutor-message" :class="message.sender === 'learner' ? 'is-learner' : 'is-agent'">
          <div class="tutor-message-meta"><span class="tutor-avatar" aria-hidden="true">{{ message.sender === 'learner' ? '我' : 'AI' }}</span><span>{{ message.sender === 'learner' ? '我' : 'AI 导学' }}</span></div>
          <ResourceMarkdownViewer :content="message.content || (message.stream_status === 'streaming' ? '正在思考…' : '')" />
          <i v-if="message.stream_status === 'streaming'" class="tutor-cursor" aria-label="正在输出" />
          <small v-if="message.stream_status === 'paused'" class="tutor-stream-note">已暂停，保留以上内容。</small>
          <small v-if="message.stream_status === 'interrupted' || message.stream_status === 'failed'" class="tutor-stream-note">回复中断，可继续提问。</small>
          <small v-if="message.sources?.length" class="tutor-sources">依据：{{ message.sources.map(source => source.name).join('、') }}</small>
          <small v-if="message.evidence_reason" class="tutor-stream-note">{{ message.evidence_reason }}</small>
          <TutoringAssessmentCard v-if="message.assessment" :assessment="message.assessment" :submitting="assessmentSubmitting === message.assessment.assessment_id" :resource-submitting="resourceDecisionSubmitting === message.assessment.adjustment_proposal_id" @answer="answerAssessment(message.assessment!, $event)" @resource-decision="decideAssessmentResource(message.assessment!, $event)" />
          <small v-if="message.assessment_unavailable" class="tutor-stream-note">当前知识点暂无可用的正式验证题，画像保持不变。</small>
        </article>
      </div>
      </div>
      <template #footer>
        <div class="tutor-footer-tools">
          <button class="btn" type="button" :disabled="masteryCheckLoading || tutorSending || tutorLoading || !tutorSession?.evidence_scope" @click="requestTutorMasteryCheck">{{ masteryCheckLoading ? '正在准备...' : '申请掌握检查' }}</button>
        </div>
        <form class="tutor-form" @submit.prevent="sendTutorMessage">
          <div class="tutor-composer"><textarea v-model="tutorDraft" rows="3" maxlength="2000" aria-label="输入导学问题" placeholder="输入你想了解的问题" :disabled="tutorSending || tutorLoading" @keydown.enter.exact.prevent="sendTutorMessage" /><small>{{ tutorDraft.length }}/2000</small></div>
          <button v-if="tutorSending" class="btn" type="button" @click="pauseTutorMessage">暂停输出</button>
          <button v-else class="tutor-send" type="submit" title="发送问题" aria-label="发送问题" :disabled="!tutorDraft.trim() || tutorLoading"><AppIcon name="send" /></button>
        </form>
      </template>
    </AppDrawer>
  </section>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useToast } from '@/composables/useToast'
import { downloadResourceExport, listResources, exportResource, submitFeedback, type ResourceSummary } from '@/api/resources'
import { resourceQualityStatusLabel } from '@/utils/resourceQualityStatus'
import { masteryCheckErrorMessage } from '@/utils/masteryCheckError'
import { generationFailureCopy } from '@/utils/generationFailure'
import { dismissKnowledgeImpact, exportLearningPackage, getCurrentLearningPackage, getLearningPackage, refreshAffectedResources, type LearningPackage, type LearningPackageExportFormat } from '@/api/learningPackages'
import { getActiveGenerationTask, getGenerationTask, retryGenerationTask, type GenerationTaskDetail } from '@/api/generation'
import { getLearnerProfile } from '@/api/learners'
import { useDomainStore } from '@/stores/domainStore'
import QualityMetrics from '@/components/ResourceViewer/QualityMetrics.vue'
import AppDialog from '@/components/Shared/AppDialog.vue'
import AppDrawer from '@/components/Shared/AppDrawer.vue'
import AppIcon from '@/components/Shared/AppIcon.vue'
import PageHeader from '@/components/Shared/PageHeader.vue'
import PageState from '@/components/Shared/PageState.vue'
import MetricStrip from '@/components/Shared/MetricStrip.vue'
import { answerTutoringAssessment, createTutoringSession, getTutoringSession, pauseTutoringMessage, requestMasteryCheck, streamTutoringMessage, type TutoringAssessment, type TutoringSession } from '@/api/tutoring'
import { decideLearningAdjustmentResource } from '@/api/learningAdjustments'
import ResourceMarkdownViewer from '@/components/ResourceViewer/ResourceMarkdownViewer.vue'
import GradedQuizViewer from '@/components/ResourceViewer/GradedQuizViewer.vue'
import ResourceTypeIcon from '@/components/ResourceViewer/ResourceTypeIcon.vue'
import TutoringAssessmentCard from '@/components/ResourceViewer/TutoringAssessmentCard.vue'
import { useAuthStore } from '@/stores/authStore'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const domainStore = useDomainStore()
const { showToast } = useToast()
const loading = ref(false)
const resources = ref<ResourceSummary[]>([])
const selectedIdx = ref(0)
const headings = ref<HeadingItem[]>([])
const exportFormat = ref('markdown')
const exportDialog = ref<InstanceType<typeof AppDialog> | null>(null)
const packageExportFormat = ref<LearningPackageExportFormat>('markdown')
const packageExportDialog = ref<InstanceType<typeof AppDialog> | null>(null)
const exportingResource = ref(false)
const exportingPackage = ref(false)
const errorMessage = ref('')
const feedbackSubmitting = ref(false)
const retrying = ref(false)
const taskDetail = ref<GenerationTaskDetail | null>(null)
const currentPackage = ref<LearningPackage | null>(null)
const impactSubmitting = ref(false)
const tutorOpen = ref(false)
const tutorLoading = ref(false)
const tutorSending = ref(false)
const tutorError = ref('')
const tutorDraft = ref('')
const tutorSession = ref<TutoringSession | null>(null)
const messageList = ref<HTMLElement | null>(null)
let streamController: AbortController | null = null
let activeReplyId = ''
let tutorOpenRequestId = 0
const assessmentSubmitting = ref('')
const masteryCheckLoading = ref(false)
const resourceDecisionSubmitting = ref('')
const feedbackOptions = [{ value: 'too_hard', label: '内容太难' }, { value: 'too_easy', label: '内容太简单' }, { value: 'confusing', label: '解释不清楚' }, { value: 'incorrect', label: '内容可能有误' }, { value: 'helpful', label: '对我有帮助' }]
const formats = [
  { value: 'markdown', label: 'Markdown', desc: '保留标题、表格、代码块和知识来源结构。', tag: '源格式' },
  { value: 'pdf', label: 'PDF', desc: '排版美观，适合阅读、打印和提交。', tag: '推荐' },
  { value: 'word', label: 'Word', desc: '可编辑的 .docx 文档，方便二次修改。', tag: '可编辑' },
]

interface HeadingItem { level: number; text: string; id: string }

const RESOURCE_TYPE_LABELS: Record<string, string> = {
  lecture: '讲义',
  practice_guide: '实训指导',
  graded_quiz: '分级测验',
}
function typeLabel(type: string) { return RESOURCE_TYPE_LABELS[type] || type }
function resourceStep(type: string) {
  return ({
    lecture: { order: '01', label: '阅读讲义', hint: '理解核心概念' },
    practice_guide: { order: '02', label: '完成实操', hint: '按步骤练习' },
    graded_quiz: { order: '03', label: '参加测验', hint: '检验当前掌握' },
  } as Record<string, { order: string; label: string; hint: string }>)[type] || { order: '--', label: typeLabel(type), hint: '学习资源' }
}
function formatPercent(value: number) {
  return `${Number(value || 0).toFixed(1)}%`
}
function onHeadings(items: HeadingItem[]) { headings.value = items }
function scrollToHeading(id: string) {
  const el = document.getElementById(id)
  if (!el) return
  const section = el.closest('details.md-section')
  if (section) (section as HTMLDetailsElement).open = true
  el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

const selected = computed(() => resources.value[selectedIdx.value] || null)
const sourceDetails = computed(() => {
  const seen = new Set<string>()
  return (selected.value?.source_details || []).filter((source) => {
    const name = source.name.trim()
    const key = name && name !== '关联知识点'
      ? `name:${name.toLocaleLowerCase()}`
      : `id:${source.knowledge_id}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
})
const knowledgeLabels = computed(() => Object.fromEntries(
  sourceDetails.value.map(source => [source.knowledge_id, source.name]),
))
const knowledgeImpact = computed(() => currentPackage.value?.knowledge_impact || null)
const pathNodeTitle = computed(() => taskDetail.value?.path_node_title || currentPackage.value?.path_node_title || '')
const pathNodeOrder = computed(() => taskDetail.value?.path_node_order || currentPackage.value?.path_node_order || '-')
const generationBasis = computed(() => taskDetail.value?.generation_basis || currentPackage.value?.generation_basis || null)
const nodeGate = computed(() => currentPackage.value?.node_gate || null)
const packageQuality = computed(() => (
  taskDetail.value?.package_quality
  || currentPackage.value?.package_quality
  || resources.value[0]?.package_quality
  || null
))
const packageQualityMetrics = computed(() => {
  if (!packageQuality.value) return []
  return [
    {
      label: '本学习包审核幻觉率',
      value: formatPercent(packageQuality.value.hallucination_rate),
      description: '达标线 < 5%',
    },
    {
      label: '难度适配',
      value: formatPercent(packageQuality.value.difficulty_match_score),
      description: '达标线 >= 85%',
    },
    {
      label: '核心知识覆盖',
      value: formatPercent(packageQuality.value.core_knowledge_coverage),
      description: '达标线 >= 90%',
    },
  ]
})
const prerequisiteNames = computed(() => generationBasis.value?.prerequisite_knowledge.length
  ? generationBasis.value.prerequisite_knowledge.map(item => item.name).join('、')
  : '无需额外前置复习')
// 页面用知识点名称呈现学习依据，隐藏 Markdown 中的内部 Chunk 审计标识。
const bodyContent = computed(() => {
  const content = selected.value?.content || ''
  const marker = '\n## 知识来源'
  const index = content.lastIndexOf(marker)
  const withoutSourceIndex = index >= 0 ? content.slice(0, index).trimEnd() : content
  return withoutSourceIndex
    .split('\n')
    .filter(line => !/^\s*(?:[-*]\s*)?来源：.*::chunk::\d+\s*$/.test(line))
    .join('\n')
    .replace(/\n{3,}/g, '\n\n')
    .trimEnd()
})
const canTutor = computed(() => Boolean(selected.value && selected.value.review_status === 'passed'))
const quizContent = computed(() => {
  const structured = selected.value?.structured_content
  return structured && structured.resource_type === 'graded_quiz' ? structured : null
})
const isGradedQuiz = computed(() => Boolean(quizContent.value))
const showToc = computed(() => !isGradedQuiz.value && headings.value.length > 1)
const tutorMessages = computed(() => tutorSession.value?.messages || [])
// Scored checks are rendered only on the tutoring message that created them.
// This avoids presenting a historical adjustment from another session as a new answer result.
const nodeAssessment = computed(() => tutorSession.value?.pending_assessment || null)
const assessmentInMessages = computed(() => Boolean(nodeAssessment.value && tutorMessages.value.some(message => message.assessment?.assessment_id === nodeAssessment.value?.assessment_id)))
const taskId = computed(() => String(route.query.task_id || '').trim())
const currentLearnerId = computed(() => {
  if (taskId.value) return String(taskDetail.value?.learner_id || route.query.learner_id || '').trim()
  return String(authStore.user?.learner_id || '').trim()
})
const isTaskTerminal = computed(() => ['completed', 'failed'].includes(taskDetail.value?.status || ''))
const isShowingProgress = computed(() => Boolean(taskDetail.value && !isTaskTerminal.value))
const isViewingPackageWithImpact = computed(() => Boolean(
  currentPackage.value && (!taskId.value || currentPackage.value.task_id === taskId.value),
))
const canManageKnowledgeImpact = computed(() => Boolean(
  currentPackage.value?.is_current_package
  && !isShowingProgress.value
  && knowledgeImpact.value?.status !== 'refreshing'
  && knowledgeImpact.value?.status !== 'resolved',
))
const canExportPackage = computed(() => {
  const packageData = currentPackage.value
  if (!packageData || packageData.status !== 'completed') return false
  const approvedTypes = new Set(
    packageData.resources
      .filter(resource => resource.review_status === 'passed')
      .map(resource => resource.resource_type),
  )
  return ['lecture', 'practice_guide', 'graded_quiz'].every(type => approvedTypes.has(type))
})
const generationStatusTitle = computed(() => {
  if (taskDetail.value?.decision === 'revision_required') return '正在自动修订资源'
  if (taskDetail.value?.event_type === 'knowledge_refresh') {
    return `正在更新 ${taskDetail.value.resource_types?.length || 1} 份受影响资源`
  }
  return '正在生成个性化学习资源'
})
const generationStatusDescription = computed(() => (
  taskDetail.value?.event_type === 'knowledge_refresh'
    ? '当前学习包仍可继续使用，受影响资源通过质量校验后将统一切换。'
    : '三类资源将在全部达到质量门槛后统一发布。'
))
const isContentPolicyFailure = computed(() => (
  taskDetail.value?.failure_details?.failure_code === 'generated_content_policy_invalid'
  || taskDetail.value?.failure_reason === 'generated_content_policy_invalid'
))
const generationFailure = computed(() => generationFailureCopy(
  taskDetail.value?.failure_details?.failure_code || taskDetail.value?.failure_reason,
))
const generationFailureTitle = computed(() => generationFailure.value.title)
const generationFailureDescription = computed(() => generationFailure.value.description)
const failedResourceLabels = computed(() => (
  (taskDetail.value?.failure_details?.resource_types || []).map(typeLabel).join('、')
))
const failedFieldPaths = computed(() => (
  (taskDetail.value?.failure_details?.field_paths || []).join('、')
))
let taskTimer: number | null = null
let pollingTaskId = ''

function clearTaskTimer() {
  if (taskTimer !== null) window.clearTimeout(taskTimer)
  taskTimer = null
  pollingTaskId = ''
}

function scrollTutorToLatest() {
  nextTick(() => {
    if (messageList.value) messageList.value.scrollTop = messageList.value.scrollHeight
  })
}

async function openTutor() {
  if (!canTutor.value || !selected.value) return
  const resourceId = selected.value.resource_id
  const requestId = ++tutorOpenRequestId
  streamController?.abort()
  streamController = null
  activeReplyId = ''
  tutorSending.value = false
  tutorOpen.value = true
  tutorLoading.value = true
  tutorError.value = ''
  tutorSession.value = null
  try {
    const session = await createTutoringSession(resourceId, currentLearnerId.value || undefined)
    if (requestId !== tutorOpenRequestId || !tutorOpen.value || selected.value?.resource_id !== resourceId) return
    tutorSession.value = session
    scrollTutorToLatest()
  } catch {
    if (requestId === tutorOpenRequestId && tutorOpen.value && selected.value?.resource_id === resourceId) {
      tutorError.value = '无法打开导学会话，请稍后重试。'
    }
  } finally {
    if (requestId === tutorOpenRequestId) tutorLoading.value = false
  }
}

function clearTutorContext() {
  tutorOpenRequestId += 1
  streamController?.abort()
  streamController = null
  activeReplyId = ''
  tutorLoading.value = false
  tutorSending.value = false
  tutorError.value = ''
  tutorDraft.value = ''
  tutorSession.value = null
}

async function sendTutorMessage() {
  const content = tutorDraft.value.trim()
  if (!content || !tutorSession.value || tutorSending.value) return
  const sessionId = tutorSession.value.session_id
  const controller = new AbortController()
  tutorSending.value = true
  tutorError.value = ''
  const pendingId = `pending_${Date.now()}`
  tutorSession.value.messages.push({ message_id: pendingId, sender: 'learner', message_type: 'question', content, created_at: null, stream_status: 'completed' })
  tutorDraft.value = ''
  scrollTutorToLatest()
  streamController = controller
  try {
    await streamTutoringMessage(sessionId, content, event => {
      if (tutorSession.value?.session_id !== sessionId || streamController !== controller) return
      if (event.type === 'accepted') {
        activeReplyId = event.reply_message_id
        const learner = tutorSession.value.messages.find(item => item.message_id === pendingId)
        if (learner) learner.message_id = event.learner_message_id
        tutorSession.value.messages.push({ message_id: activeReplyId, sender: 'tutoring_agent', message_type: 'explanation', content: '', created_at: null, stream_status: 'streaming' })
      } else if (event.type !== 'agent_status') {
        const reply = tutorSession.value.messages.find(item => item.message_id === event.reply_message_id)
        if (event.type === 'delta' && reply) reply.content += event.content
        if (event.type === 'completed' && reply) { reply.content = event.content; reply.sources = event.sources; reply.scope_status = event.scope_status; reply.assessment = event.assessment; reply.assessment_unavailable = event.assessment_unavailable; reply.evidence_accepted = event.evidence_accepted; reply.evidence_reason = event.evidence_reason; reply.stream_status = 'completed'; tutorSession.value.node_adjustment_state = event.node_adjustment_state; tutorSession.value.pending_assessment = event.pending_assessment || event.assessment; tutorSession.value.node_adjustment_result = event.node_adjustment_result; tutorSession.value.evidence_scope = event.evidence_scope; showToast(event.decision_reason); if (event.task_id) showToast('已触发后续学习调整，可前往任务记录查看进度。') }
        if (event.type === 'paused' && reply) { reply.content = event.content; reply.stream_status = 'paused' }
        if (event.type === 'error' && reply) reply.stream_status = event.recoverable ? 'interrupted' : 'failed'
      }
      scrollTutorToLatest()
    }, controller.signal)
    if (tutorSession.value?.session_id === sessionId) tutorSession.value.turn_count += 1
  } catch (error) {
    if ((error as Error).name !== 'AbortError' && tutorSession.value?.session_id === sessionId) await recoverTutorSession()
  } finally {
    if (streamController === controller) {
      tutorSending.value = false
      streamController = null
      activeReplyId = ''
    }
  }
}

function askTutor(prompt: string) {
  tutorDraft.value = prompt
  void sendTutorMessage()
}

async function answerAssessment(assessment: TutoringAssessment, answer: number) {
  if (!tutorSession.value || assessmentSubmitting.value) return
  assessmentSubmitting.value = assessment.assessment_id
  try {
    const result = await answerTutoringAssessment(tutorSession.value.session_id, assessment.assessment_id, answer)
    Object.assign(assessment, result, { status: 'scored' })
    tutorSession.value.pending_assessment = null
    tutorSession.value.node_adjustment_state = ['confirmed_mastery', 'confirmed_support_need'].includes(result.decision || '') ? 'confirmed' : 'none'
    tutorSession.value.node_adjustment_result = assessment
    showToast(result.decision_reason)
  } catch {
    showToast('验证答案提交失败，请刷新后重试。')
  } finally {
    assessmentSubmitting.value = ''
  }
}

async function requestTutorMasteryCheck() {
  if (!tutorSession.value || masteryCheckLoading.value) return
  masteryCheckLoading.value = true
  try {
    await requestMasteryCheck(tutorSession.value.session_id)
    tutorSession.value = await getTutoringSession(tutorSession.value.session_id)
    scrollTutorToLatest()
  } catch (error) { showToast(masteryCheckErrorMessage(error), 'info') }
  finally { masteryCheckLoading.value = false }
}

async function decideAssessmentResource(assessment: TutoringAssessment, decision: 'generate' | 'skip') {
  const proposalId = assessment.adjustment_proposal_id
  if (!proposalId || resourceDecisionSubmitting.value) return
  resourceDecisionSubmitting.value = proposalId
  try {
    const result = await decideLearningAdjustmentResource(proposalId, decision)
    assessment.resource_decision = decision
    if (result.task_id) {
      await router.push({ path: '/resources', query: { task_id: result.task_id, ...(currentLearnerId.value ? { learner_id: currentLearnerId.value } : {}) } })
    } else {
      showToast('已暂不生成资源，画像与路线调整保持生效。', 'info')
    }
  } catch { showToast('资源选择保存失败，路线可能已更新，请刷新后重试。', 'error') }
  finally { resourceDecisionSubmitting.value = '' }
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
  clearTutorContext()
  if (tutorOpen.value) tutorOpen.value = false
})
watch(tutorOpen, (open) => {
  if (open) return
  clearTutorContext()
})

async function loadResources() {
  loading.value = true
  errorMessage.value = ''
  try {
    if (taskId.value) {
      const [latestPackage, requestedPackage, taskResources] = await Promise.all([
        getCurrentLearningPackage(taskDetail.value?.domain_code || domainStore.currentDomainCode, currentLearnerId.value || undefined),
        getLearningPackage(taskId.value),
        listResources({ taskId: taskId.value, learnerId: currentLearnerId.value || undefined, domainCode: taskDetail.value?.domain_code }),
      ])
      currentPackage.value = requestedPackage
      const isRefreshingLatestPackage = Boolean(
        taskDetail.value
        && !isTaskTerminal.value
        && taskDetail.value.event_type === 'knowledge_refresh'
        && taskDetail.value.source_task_id === latestPackage?.task_id,
      )
      resources.value = isRefreshingLatestPackage
        ? latestPackage?.resources || []
        : requestedPackage.resources.length ? requestedPackage.resources : taskResources
    } else {
      currentPackage.value = await getCurrentLearningPackage(taskDetail.value?.domain_code || domainStore.currentDomainCode, currentLearnerId.value || undefined)
      resources.value = currentPackage.value?.resources || []
    }
  } catch {
    errorMessage.value = '无法读取学习资源，请确认后端服务可用。'
  } finally {
    loading.value = false
  }
}

async function dismissImpact() {
  if (!currentPackage.value) return
  impactSubmitting.value = true
  try {
    currentPackage.value = await dismissKnowledgeImpact(currentPackage.value.task_id)
    resources.value = currentPackage.value.resources
    showToast('已暂不更新，现有资源仍可继续使用。')
  } catch { showToast('暂时无法保存选择') }
  finally { impactSubmitting.value = false }
}

async function refreshImpact() {
  if (!currentPackage.value || !knowledgeImpact.value?.refresh_available) return
  impactSubmitting.value = true
  try {
    const result = await refreshAffectedResources(currentPackage.value.task_id)
    await router.push({ path: '/resources', query: { task_id: result.task_id, ...(currentLearnerId.value ? { learner_id: currentLearnerId.value } : {}) } })
  } catch { showToast('无法创建局部更新任务，请确认向量索引已就绪。') }
  finally { impactSubmitting.value = false }
}

async function pollTask(targetTaskId: string) {
  clearTaskTimer()
  pollingTaskId = targetTaskId
  try {
    const detail = await getGenerationTask(targetTaskId)
    if (pollingTaskId !== targetTaskId) return
    taskDetail.value = detail
    if (isTaskTerminal.value) {
      await loadResources()
      return
    }
    taskTimer = window.setTimeout(() => pollTask(targetTaskId), 1500)
  } catch { errorMessage.value = '无法读取生成任务状态。' }
}

async function initializePage() {
  clearTaskTimer()
  taskDetail.value = null
  selectedIdx.value = 0
  if (currentLearnerId.value && !domainStore.currentDomainCode) {
    const profile = await getLearnerProfile(currentLearnerId.value)
    await domainStore.initialize(profile.domain_code)
  }
  if (taskId.value) {
    try {
      taskDetail.value = await getGenerationTask(taskId.value)
      await loadResources()
      if (!isTaskTerminal.value) await pollTask(taskId.value)
    } catch { errorMessage.value = '无法读取生成任务状态。' }
    return
  }

  await loadResources()
  try {
    const activeTask = await getActiveGenerationTask(currentLearnerId.value || undefined)
    if (activeTask) {
      taskDetail.value = activeTask
      await pollTask(activeTask.task_id)
    }
  } catch {
    // 资源仍可正常阅读，仅暂时无法恢复进度状态。
  }
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
  try {
    taskDetail.value = await retryGenerationTask(taskId.value)
    const successorTaskId = taskDetail.value.task_id
    await router.replace({ query: { ...route.query, task_id: successorTaskId } })
    await pollTask(successorTaskId)
  }
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
  exportingResource.value = true
  try {
    const r = await exportResource(selected.value.resource_id, exportFormat.value as 'markdown' | 'pdf' | 'word')
    await downloadExportFile(r.download_url, r.file_name)
    exportDialog.value?.close()
    showToast(`已下载：${r.file_name}`)
  } catch { showToast('导出失败') }
  finally { exportingResource.value = false }
}

async function doExportPackage() {
  if (!currentPackage.value || exportingPackage.value) return
  exportingPackage.value = true
  try {
    const result = await exportLearningPackage(currentPackage.value.task_id, packageExportFormat.value)
    await downloadExportFile(result.download_url, result.file_name)
    packageExportDialog.value?.close()
    showToast(`已下载学习包：${result.file_name}`)
  } catch {
    showToast('学习包导出失败，请确认三类资源均已完成审核。')
  } finally {
    exportingPackage.value = false
  }
}

async function downloadExportFile(downloadUrl: string, fileName: string) {
  const blob = await downloadResourceExport(downloadUrl)
  const blobUrl = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = blobUrl
  anchor.download = fileName
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(blobUrl)
}

watch(
  () => [route.query.task_id, route.query.learner_id],
  () => { void initializePage() },
)
onMounted(initializePage)
onUnmounted(clearTaskTimer)
</script>

<style scoped>
.resource-page { gap: 18px; max-width: 1080px; margin: 0 auto; }
.refresh-btn { display: grid; width: 42px; min-width: 42px; min-height: 36px; place-items: center; border: 1px solid var(--line); border-radius: var(--radius-control); background: var(--panel); color: var(--body); padding: 0; cursor: pointer; transition: border-color var(--transition-fast), background var(--transition-fast), color var(--transition-fast); }
.refresh-btn:hover:not(:disabled) { border-color: var(--line-strong); background: var(--soft); color: var(--blue); }
.refresh-btn:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
.refresh-btn:disabled { cursor: not-allowed; opacity: .58; }
.refresh-btn[aria-busy="true"] .app-icon { animation: refresh-spin .8s linear infinite; }
.refresh-btn .app-icon { width: 18px; height: 18px; }
@keyframes refresh-spin { to { transform: rotate(360deg); } }
.learning-overview { border: 1px solid var(--line); border-left: 3px solid var(--blue); border-radius: 10px; background: var(--panel); padding: 18px 20px 0; box-shadow: var(--shadow-card); }
.overview-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; }
.overview-kicker { color: var(--blue); font-size: 11px; font-weight: 750; }
.overview-head h2 { margin: 5px 0 0; color: var(--ink); font-size: 19px; line-height: 1.45; }
.mastery-count { display: grid; min-width: 74px; gap: 2px; border-left: 1px solid var(--line); padding-left: 18px; text-align: right; }
.mastery-count span { color: var(--muted); font-size: 11px; }
.mastery-count strong { color: var(--blue); font-size: 24px; line-height: 1; }
.mastery-count strong small { color: var(--muted); font-size: 12px; font-weight: 650; }
.mastery-count.complete strong { color: var(--green); }
.package-quality-strip { margin: 18px -20px 0; border-radius: 0; border-inline: 0; }
.overview-evidence { margin: 0 -20px; border-top: 1px solid var(--line); }
.overview-evidence summary { padding: 10px 20px; color: var(--muted); cursor: pointer; font-size: 11px; font-weight: 700; }
.overview-evidence[open] summary { color: var(--blue); }
.overview-evidence > div { display: grid; gap: 5px; border-top: 1px solid var(--line); background: var(--soft); padding: 11px 20px 13px; }
.overview-evidence p { margin: 0; color: var(--body); font-size: 12px; line-height: 1.6; }
.overview-evidence p strong { color: var(--ink); }
.package-quality-strip { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.knowledge-impact { display: flex; align-items: center; justify-content: space-between; gap: 18px; border: 1px solid var(--line-warning); border-radius: 12px; background: var(--amber2); padding: 16px 18px; }
.knowledge-impact strong { color: var(--text-warning-strong); font-size: 14px; }
.knowledge-impact p { margin-top: 5px; color: var(--text-warning-strong); font-size: 12.5px; line-height: 1.6; }
.knowledge-impact.dismissed { border-color: var(--line); background: var(--soft); }
.knowledge-impact.dismissed strong { color: var(--ink); }
.knowledge-impact.dismissed p { color: var(--muted); }
.impact-actions { display: flex; gap: 8px; flex-shrink: 0; }

/* 空态 */
.empty-card { display: grid; justify-items: center; gap: 8px; max-width: 560px; margin: 40px auto; border: 1px dashed var(--line); border-radius: 16px; background: var(--panel); padding: 48px 32px; text-align: center; }
.empty-icon { font-size: 40px; }
.empty-card h2 { color: var(--ink); font-size: 18px; }
.empty-card p { max-width: 420px; color: var(--muted); font-size: 13px; line-height: 1.7; }
.empty-card .btn { margin-top: 12px; }

/* 资源切换 */
.resource-switcher { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.resource-switcher-item { display: flex; align-items: center; gap: 10px; min-width: 0; border: 1px solid var(--line); border-radius: 10px; background: var(--panel); padding: 13px 14px; color: var(--ink); text-align: left; cursor: pointer; transition: border-color var(--transition-fast), box-shadow var(--transition-fast), transform var(--transition-fast); }
.resource-switcher-item:hover { border-color: var(--line-strong); box-shadow: var(--shadow-hover); transform: translateY(-1px); }
.resource-switcher-item:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
.resource-switcher-item.active { border-color: var(--type); box-shadow: 0 0 0 1px var(--type-soft); }
.switch-step { color: var(--type); font-size: 10px; font-weight: 800; }
.switch-icon { display: grid; width: 36px; height: 36px; flex-shrink: 0; place-items: center; border-radius: 9px; background: var(--type-soft); color: var(--type); font-size: 20px; }
.switch-copy { display: grid; min-width: 0; gap: 4px; }
.switch-copy strong { overflow: hidden; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.switch-copy small { overflow: hidden; color: var(--muted); font-size: 11.5px; text-overflow: ellipsis; white-space: nowrap; }
.switch-lecture { --type: var(--blue); --type-soft: var(--blue2); }
.switch-practice_guide { --type: var(--green); --type-soft: var(--green2); }
.switch-graded_quiz { --type: var(--amber); --type-soft: var(--amber2); }

/* 阅读区：正文恒宽 780px，目录作为固定右侧栏、不压缩正文 */
.reader-shell { display: grid; grid-template-columns: minmax(0, 780px); max-width: 780px; margin: 0 auto; }
.reader-shell.has-toc { grid-template-columns: minmax(0, 780px) 220px; max-width: 1030px; gap: 30px; justify-content: center; }
.reader { min-width: 0; border: 1px solid var(--line); border-top: 3px solid var(--type); border-radius: 16px; background: var(--panel); padding: 28px 32px 34px; box-shadow: var(--shadow-card); }
.reader-lecture { --type: var(--blue); --type-soft: var(--blue2); }
.reader-practice_guide { --type: var(--green); --type-soft: var(--green2); }
.reader-graded_quiz { --type: var(--amber); --type-soft: var(--amber2); }

.reader-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; padding-bottom: 18px; border-bottom: 1px solid var(--line); }
.reader-title { display: flex; align-items: flex-start; gap: 13px; min-width: 0; }
.reader-icon { width: 44px; height: 44px; flex-shrink: 0; display: grid; place-items: center; border-radius: 12px; background: var(--type-soft, var(--soft)); color: var(--type, var(--blue)); font-size: 24px; }
.reader-meta { display: flex; flex-wrap: wrap; gap: 6px; }
.reader-meta span { border-radius: 5px; background: var(--soft); padding: 3px 7px; color: var(--muted); font-size: 11px; font-weight: 650; line-height: 1.35; }
.reader-meta span:first-child { background: var(--type-soft); color: var(--type); }
.reader-title h1 { margin-top: 5px; color: var(--ink); font-size: 21px; line-height: 1.35; }
.reader-tools { display: flex; gap: 8px; flex-shrink: 0; }
.tutor-trigger { display: flex; align-items: center; gap: 8px; min-height: 42px; border: 1px solid var(--blue); border-radius: 9px; background: var(--blue); color: #fff; padding: 5px 11px 5px 6px; box-shadow: var(--shadow-card); text-align: left; transition: transform var(--transition-fast), box-shadow var(--transition-fast), background var(--transition-fast); }
.tutor-trigger:hover:not(:disabled) { background: var(--text-info-strong); box-shadow: var(--shadow-hover); transform: translateY(-1px); }
.tutor-trigger:disabled { border-color: var(--line); background: var(--track); color: var(--muted); box-shadow: none; }
.tutor-trigger-icon { display: grid; width: 30px; height: 30px; place-items: center; border-radius: 7px; background: rgb(255 255 255 / .18); font-size: 16px; }
.tutor-trigger > span:last-child { display: grid; gap: 1px; }
.tutor-trigger strong { font-size: 12px; line-height: 1.2; }
.tutor-trigger small { color: rgb(255 255 255 / .78); font-size: 10px; line-height: 1.2; }
.tutor-trigger:disabled small { color: var(--muted); }
.resource-assurance { margin-top: 18px; border: 1px solid var(--line-success); border-radius: 9px; background: var(--green2); }
.resource-assurance summary { display: flex; align-items: center; gap: 9px; padding: 11px 13px; color: var(--text-success-strong); cursor: pointer; list-style: none; }
.resource-assurance summary::-webkit-details-marker { display: none; }
.assurance-mark { display: grid; width: 20px; height: 20px; flex-shrink: 0; place-items: center; border-radius: 50%; background: var(--green); color: #fff; font-size: 12px; font-weight: 800; }
.resource-assurance summary > span:nth-child(2) { display: grid; gap: 1px; min-width: 0; }
.resource-assurance strong { font-size: 12px; }
.resource-assurance small { color: var(--muted); font-size: 11px; }
.assurance-action { margin-left: auto; color: var(--muted); font-size: 11px; white-space: nowrap; }
.resource-assurance[open] .assurance-action { font-size: 0; }
.resource-assurance[open] .assurance-action::after { content: '收起详情'; font-size: 11px; }
.resource-assurance :deep(.quality-grid) { margin: 0 -1px -1px; border-radius: 0 0 8px 8px; }
.reader-body { margin-top: 22px; }

.learning-basis { margin-top: 28px; border-top: 1px solid var(--line); padding-top: 22px; }
.learning-basis-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 14px; }
.learning-basis-head > div { display: grid; gap: 4px; }
.learning-basis-head span { color: var(--type); font-size: 11px; font-weight: 750; }
.learning-basis h2 { margin: 0; color: var(--ink); font-size: 16px; line-height: 1.4; }
.learning-basis-head > small { color: var(--muted); font-size: 11px; white-space: nowrap; }
.learning-basis-list { display: grid; gap: 8px; margin-top: 14px; }
.learning-basis-item { display: flex; align-items: center; gap: 10px; min-width: 0; border: 1px solid var(--line); border-radius: 8px; background: var(--soft); padding: 10px 12px; }
.learning-basis-item > span { display: grid; width: 24px; height: 24px; flex-shrink: 0; place-items: center; border-radius: 6px; background: var(--panel); color: var(--type); font-size: 10px; font-weight: 800; }
.learning-basis-item strong { overflow: hidden; color: var(--ink); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.reader-feedback { margin-top: 22px; border: 1px solid var(--line); border-radius: 12px; background: var(--soft); padding: 18px; }
.reader-feedback h2 { color: var(--ink); font-size: 15px; }
.reader-feedback p { margin-top: 6px; color: var(--muted); font-size: 12.5px; line-height: 1.6; }

/* 目录 */
.reader-toc { position: sticky; top: 96px; display: grid; gap: 2px; align-content: start; max-height: calc(100vh - 130px); overflow-y: auto; padding: 4px 0 4px 18px; border-left: 1px solid var(--line); }
.toc-title { margin-bottom: 8px; color: var(--muted); font-size: 11px; font-weight: 700; letter-spacing: .04em; }
.toc-link { border: 0; background: transparent; padding: 5px 8px; text-align: left; color: var(--muted); font-size: 12.5px; line-height: 1.5; border-radius: 7px; cursor: pointer; }
.toc-link:hover { background: var(--soft); color: var(--ink); }
.toc-h1 { font-weight: 700; color: var(--ink); }
.toc-h2 { padding-left: 4px; }
.toc-h3 { padding-left: 16px; color: var(--muted); font-size: 12px; }
.toc-h4 { padding-left: 24px; color: var(--muted); font-size: 11.5px; }

/* 生成中 */
.generation-state { margin-bottom: 0; }
.failure-details { display: grid; gap: 8px; margin: 14px 0; }
.failure-details > div { display: grid; grid-template-columns: 76px minmax(0, 1fr); gap: 10px; }
.failure-details dt { color: var(--muted); font-size: 12px; font-weight: 700; }
.failure-details dd { margin: 0; color: var(--body); font-size: 12px; overflow-wrap: anywhere; }
.progress-track { height: 8px; margin-top: 16px; overflow: hidden; border-radius: 4px; background: var(--soft); }
.progress-track i { display: block; height: 100%; background: var(--blue); transition: width .25s ease; }

/* AI 导学抽屉 */
.tutor-error p { margin: 0; }
@keyframes tutor-blink { 50% { opacity: 0; } }

@media (max-width: 1100px) {
  .reader-shell.has-toc { grid-template-columns: minmax(0, 1fr); max-width: 780px; }
  .reader-toc { display: none; }
}
@media (max-width: 900px) {
  .resource-switcher { grid-template-columns: 1fr; }
  .knowledge-impact { align-items: stretch; flex-direction: column; }
  .impact-actions { display: grid; }
}
@media (max-width: 640px) {
  .resource-page :deep(.rp-head-actions) { grid-template-columns: 42px minmax(0, 1fr); }
  .refresh-btn { min-height: 44px; }
  .report-btn { grid-column: 1 / -1; }
}
@media (max-width: 480px) {
  .reader { padding: 20px 18px 26px; }
  .reader-head { flex-direction: column; }
  .learning-overview { padding: 16px 16px 0; }
  .overview-head { align-items: flex-start; }
  .overview-head h2 { font-size: 17px; }
  .mastery-count { min-width: 62px; padding-left: 12px; }
  .package-quality-strip { margin-inline: -16px; }
  .overview-evidence { margin-inline: -16px; }
  .overview-evidence summary, .overview-evidence > div { padding-inline: 16px; }
  .learning-basis-head { align-items: flex-start; flex-direction: column; gap: 5px; }
  .resource-assurance summary { align-items: flex-start; }
}

:global(.drawer) { width: min(500px, 95vw); }
:global(.drawer-head) { padding: 18px 20px 16px; background: var(--panel); }
:global(.drawer-body) { padding: 16px 18px 20px; background: var(--bg); }
:global(.drawer-foot) { padding: 14px 18px 18px; background: var(--panel); }

.tutor-context {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
  color: var(--body);
  padding: 9px 10px;
  font-size: 12px;
  font-weight: 650;
  line-height: 1.6;
}
.tutor-context-icon,
.tutor-empty-icon {
  display: grid;
  place-items: center;
  border-radius: 7px;
  background: var(--blue2);
  color: var(--blue);
}
.tutor-context-icon { width: 25px; height: 25px; font-size: 14px; }
.tutor-state {
  min-height: 220px;
  display: grid;
  align-content: center;
  justify-items: center;
  gap: 10px;
  border: 1px dashed var(--line);
  border-radius: 10px;
  background: var(--panel);
  color: var(--muted);
  padding: 28px;
  text-align: center;
  font-size: 13px;
  line-height: 1.65;
}
.tutor-state p { max-width: 280px; margin: 0; }
.tutor-loading { grid-template-columns: 1fr; justify-items: stretch; gap: 9px; }
.tutor-loading span {
  height: 10px;
  border-radius: 5px;
  background: var(--track);
}
.tutor-loading span:nth-child(2) { width: 82%; }
.tutor-loading span:nth-child(3) { width: 58%; }
.tutor-loading p { justify-self: center; margin-top: 8px; }
.tutor-empty-icon { width: 40px; height: 40px; font-size: 20px; }
.tutor-empty strong { color: var(--ink); font-size: 14px; }
.tutor-suggestions { display: flex; flex-wrap: wrap; justify-content: center; gap: 7px; margin-top: 3px; }
.tutor-suggestions button { border: 1px solid var(--line-info); border-radius: 999px; background: var(--blue2); color: var(--blue); padding: 6px 9px; font-size: 11px; line-height: 1.3; }
.tutor-suggestions button:hover:not(:disabled) { border-color: var(--blue); background: var(--surface-selected); }
.tutor-suggestions button:disabled { opacity: .62; cursor: not-allowed; }
.tutor-error { border-style: solid; border-color: var(--red); color: var(--red); }
.tutor-messages {
  display: grid;
  align-content: start;
  gap: 16px;
  min-height: 260px;
  max-height: calc(100vh - 316px);
  overflow-y: auto;
  padding: 2px 3px 8px;
}
.tutor-message { width: min(92%, 390px); max-width: 92%; display: grid; gap: 5px; }
.tutor-message.is-learner { justify-self: end; }
.tutor-message-meta { display: flex; align-items: center; gap: 6px; color: var(--muted); font-size: 11px; font-weight: 650; }
.tutor-message.is-learner .tutor-message-meta { flex-direction: row-reverse; justify-content: flex-start; }
.tutor-avatar {
  width: 22px;
  height: 22px;
  display: grid;
  place-items: center;
  border-radius: 7px;
  background: var(--blue2);
  color: var(--blue);
  font-size: 10px;
  font-weight: 800;
}
.tutor-message.is-learner .tutor-avatar { background: var(--blue); color: #fff; }
.tutor-message :deep(.markdown-body) {
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--panel);
  padding: 11px 13px;
  color: var(--ink);
  font-size: 13px;
  line-height: 1.7;
  overflow-wrap: anywhere;
}
.tutor-message.is-learner :deep(.markdown-body) { border-color: var(--blue); background: var(--blue2); color: var(--ink); }
.tutor-cursor { width: 5px; height: 13px; display: inline-block; margin: 7px 0 0 12px; border-radius: 2px; background: var(--blue); animation: tutor-blink 1s steps(2, start) infinite; vertical-align: middle; }
.tutor-stream-note,
.tutor-sources { display: block; margin-left: 6px; color: var(--muted); font-size: 11px; line-height: 1.55; }
.tutor-sources { color: var(--body); }
.tutor-footer-tools { display: flex; justify-content: flex-start; margin-bottom: 8px; }
.tutor-form { display: grid; grid-template-columns: minmax(0, 1fr) 42px; align-items: stretch; gap: 10px; }
.tutor-composer { position: relative; min-width: 0; }
.tutor-form textarea {
  width: 100%;
  min-height: 86px;
  resize: vertical;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--soft);
  padding: 11px 12px 25px;
  color: var(--ink);
  font-size: 13px;
  line-height: 1.5;
}
.tutor-form textarea:focus { border-color: var(--blue); background: var(--panel); }
.tutor-composer small { position: absolute; right: 10px; bottom: 8px; color: var(--muted); font-size: 10px; pointer-events: none; }
.tutor-send {
  width: 42px;
  height: 42px;
  align-self: end;
  display: grid;
  place-items: center;
  border: 0;
  border-radius: 8px;
  background: var(--blue);
  color: #fff;
  font-size: 18px;
  transition: background var(--transition-fast), transform var(--transition-fast);
}
.tutor-send:hover:not(:disabled) { background: var(--text-info-strong); transform: translateY(-1px); }
.tutor-send:disabled { background: var(--track); color: var(--muted); }
.tutor-pause { align-self: end; min-height: 42px; }

@media (max-width: 480px) {
  :global(.drawer) { width: 100vw; }
  .tutor-messages { max-height: calc(100vh - 328px); }
  .tutor-message { width: 96%; }
  .tutor-form { grid-template-columns: 1fr; }
}
</style>
