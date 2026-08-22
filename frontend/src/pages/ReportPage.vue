<template>
  <section class="page report-page">
    <PageHeader title="学习报告" description="能力画像、学习资源与推荐路径，一份报告看清当前水平和下一步学习安排。">
      <template #actions>
        <span class="learner-tag">学习者 {{ learnerId || '-' }}</span>
        <button class="btn" :disabled="loading" @click="loadReport">{{ loading ? '刷新中...' : '刷新报告' }}</button>
      </template>
    </PageHeader>

    <PageState v-if="loading" type="loading" title="正在加载学习报告" />

    <div v-else-if="errorMessage" class="error-state"><strong>报告加载失败</strong><p>{{ errorMessage }}</p><button class="btn" @click="loadReport">重新加载</button></div>

    <div v-else-if="!report" class="card empty-state">
      <div class="empty-icon"><AppIcon name="report" /></div>
      <h2>尚未生成学习报告</h2>
      <p>请先在学习中心完成学习背景建档和首次能力诊断，系统将据此生成能力画像与学习路线。</p>
      <button class="btn primary" @click="router.push('/dashboard')">返回学习中心</button>
    </div>

    <template v-else>
      <!-- 画像身份卡 -->
      <header class="hero">
        <div class="hero-id">
          <span class="hero-kicker">个性化能力画像</span>
          <h2>{{ profileTypeLabel(report.profile_type) }}</h2>
          <p>基于诊断测评生成的能力画像，用于个性化资源生成与学习路径推荐。</p>
          <div class="hero-tags">
            <span v-for="d in directionList" :key="d" class="hero-tag">{{ d }}</span>
            <span class="hero-tag">{{ contextSnapshot.education_level || '未填写' }} · {{ contextSnapshot.major || '未填写专业' }}</span>
            <span v-if="contextSnapshot.experience_years != null" class="hero-tag">{{ contextSnapshot.experience_years }} 年经验</span>
          </div>
        </div>
        <div class="hero-stats">
          <div class="stat"><strong>{{ diagnosticAccuracy }}%</strong><span>诊断正确率</span></div>
          <div class="stat"><strong>{{ weakCount }}</strong><span>薄弱知识点</span></div>
          <div class="stat"><strong>{{ resourceTotal }}</strong><span>已通过资源</span></div>
        </div>
      </header>

      <!-- 能力画像 -->
      <div class="report-grid">
        <section class="card">
          <div class="card-head">
            <div><h2>能力画像</h2><p class="section-note">五项能力维度的当前水平</p></div>
          </div>
          <div class="profile-body">
            <div class="radar-wrap"><RadarChart :values="report.radar" /></div>
            <div class="ability-list">
              <div v-for="item in abilityRows" :key="item.label" class="ability-row">
                <div class="ability-meta"><span>{{ item.label }}</span><strong>{{ item.value }}</strong></div>
                <div class="ability-track"><i :style="{ width: `${item.value}%` }"></i></div>
              </div>
            </div>
          </div>
        </section>

      </div>

      <!-- 薄弱知识点 -->
      <section class="card">
        <div class="card-head">
          <div><h2>薄弱知识点</h2><p class="section-note">按薄弱程度排序，优先处理高等级项目</p></div>
          <span v-if="sortedWeakKnowledge.length" class="weak-count">{{ sortedWeakKnowledge.length }} 项待巩固</span>
        </div>
        <div v-if="sortedWeakKnowledge.length" class="weak-grid">
          <div v-for="(item, index) in sortedWeakKnowledge" :key="item.knowledge_id" class="weak-card" :class="severityLevel(item.weakness_level)">
            <div class="weak-card-head">
              <span class="weak-rank">{{ index + 1 }}</span>
              <div class="weak-title"><h3>{{ item.name }}</h3><span class="category-tag">{{ item.category }}</span></div>
            </div>
            <div class="severity-meter">
              <span class="severity-dots"><i v-for="level in 5" :key="level" :class="{ on: level <= item.weakness_level }"></i></span>
              <span class="severity-badge">{{ weaknessLabel(item.weakness_level) }}</span>
            </div>
          </div>
        </div>
        <div v-else class="weak-empty"><span aria-hidden="true">✓</span><div><strong>当前没有已确认的薄弱知识点</strong><p>继续完成训练与分阶测试，报告会根据有效证据更新。</p></div></div>
      </section>

      <!-- 学习路径 -->
      <section class="card">
        <div class="card-head">
          <div><h2>推荐学习路径</h2><p class="section-note">根据画像与薄弱点动态推荐</p></div>
          <span class="status" :class="report.feedback_summary?.learning_path_needs_refresh ? 'wait' : 'ok'">{{ report.feedback_summary?.learning_path_needs_refresh ? '待刷新' : '当前版本' }}</span>
        </div>
        <div v-if="pathNodes.length" class="path-h">
          <div v-for="(node, index) in pathNodes" :key="node.path_node_id" class="path-h-step" :class="`node-${node.status}`">
            <span class="path-num">{{ index + 1 }}</span>
            <div class="path-node-copy">
              <div class="path-node-title"><h3>{{ node.title }}</h3><span class="node-status">{{ pathStatusLabel(node.status) }}</span></div>
              <p>{{ node.knowledge_id }} · 通过阈值 {{ Math.round(node.completion_condition.threshold * 100) }}%</p>
              <div v-if="node.status === 'current'" class="path-actions">
                <button v-if="node.resource_state === 'ready'" class="btn" @click="openNodeResource(node)">继续学习</button>
                <button v-if="node.resource_state === 'ready'" class="btn primary" :disabled="pathActionLoading" @click="beginAssessment(node.path_node_id)">{{ pathActionLoading ? '正在准备...' : '开始节点验证' }}</button>
                <button v-else-if="node.resource_state === 'generating'" class="btn primary" @click="openNodeResource(node)">查看生成进度</button>
                <button v-else class="btn primary" :disabled="creatingGeneration" @click="generateNodeResources(node)">{{ creatingGeneration ? '正在创建...' : node.resource_state === 'failed' ? '重新生成本节点资源' : '生成本节点资源' }}</button>
              </div>
              <div v-if="assessment?.node_id === node.path_node_id && assessment.status === 'pending'" class="node-assessment">
                <span>节点验证 · 难度 {{ assessment.difficulty }}</span>
                <strong>{{ assessment.stem }}</strong>
                <button v-for="(option, optionIndex) in assessment.options" :key="optionIndex" type="button" :disabled="assessmentSubmitting" @click="submitNodeAnswer(node.path_node_id, optionIndex)">{{ option }}</button>
              </div>
              <p v-if="pathMessage && node.status === 'current'" class="path-message">{{ pathMessage }}</p>
            </div>
          </div>
        </div>
        <div v-else-if="report.path_detail?.length" class="path-h">
          <div v-for="(stage, index) in report.path_detail" :key="index" class="path-h-step">
            <span class="path-num">{{ index + 1 }}</span><div><h3>{{ stage.name }}</h3><p>{{ stage.description || '根据当前画像推荐' }}</p></div>
          </div>
        </div>
        <div v-else class="empty-hint">尚未形成可展示的学习路径。</div>
      </section>

      <!-- 最近资源 -->
      <section v-if="report.resource_summary?.recent?.length" class="card">
          <div class="card-head"><div><h2>最近资源</h2><p class="section-note">已通过自动质量校验的个性化学习资源</p></div></div>
        <div class="table-wrap">
          <table class="resource-table">
            <thead><tr><th>资源</th><th>类型</th><th>难度</th><th>质量状态</th><th>来源</th></tr></thead>
            <tbody>
              <tr v-for="r in report.resource_summary.recent" :key="r.resource_id">
                <td class="cell-title">{{ r.title }}</td>
                <td><span class="tag">{{ r.resource_type_label || r.resource_type }}</span></td>
                <td>{{ r.difficulty }}/5</td>
                <td><span class="status" :class="resourceQualityStatusTone(r.review_status)">{{ resourceQualityStatusLabel(r.review_status) }}</span></td>
                <td>{{ r.source_count }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- 建议下一步 -->
      <section v-if="report.next_actions?.length" class="card next-card">
        <div class="next-copy">
          <h2>建议下一步</h2>
          <p>{{ report.next_actions[0].description }}</p>
        </div>
        <div class="next-actions">
          <button v-for="a in report.next_actions" :key="a.type" class="btn" :class="{ primary: a.type === 'generation' }" :disabled="creatingGeneration && a.type === 'generation'" @click="handleNextAction(a)">{{ creatingGeneration && a.type === 'generation' ? '正在创建学习包...' : a.label }}</button>
        </div>
      </section>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getLearningReport, type LearningReport } from '@/api/reports'
import { answerPathNodeAssessment, startPathNodeAssessment, type LearningPathNode, type PathNodeAssessment } from '@/api/learningPaths'
import { useToast } from '@/composables/useToast'
import { resourceQualityStatusLabel, resourceQualityStatusTone } from '@/utils/resourceQualityStatus'
import { createGenerationTask } from '@/api/generation'
import { getDomainReadiness } from '@/api/domains'
import RadarChart from '@/components/Charts/RadarChart.vue'
import AppIcon from '@/components/Shared/AppIcon.vue'
import PageHeader from '@/components/Shared/PageHeader.vue'
import PageState from '@/components/Shared/PageState.vue'
import { useAuthStore } from '@/stores/authStore'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const { showToast } = useToast()
const taskId = computed(() => String(route.query.task_id || '').trim())
const isAdminTaskContext = computed(() => authStore.role === 'admin' && Boolean(taskId.value))
const learnerId = computed(() => {
  const source = isAdminTaskContext.value
    ? route.query.learner_id
    : authStore.user?.learner_id
  const normalized = String(source || '').trim()
  return ['null', 'undefined'].includes(normalized.toLowerCase()) ? '' : normalized
})
const report = ref<LearningReport | null>(null)
const loading = ref(false)
const errorMessage = ref('')
const creatingGeneration = ref(false)
const pathActionLoading = ref(false)
const assessmentSubmitting = ref(false)
const assessment = ref<PathNodeAssessment | null>(null)
const pathMessage = ref('')

const radarLabels = ['理论基础', '实操能力', '问题解决', '知识广度', '学习速度']
const DIRECTION_LABELS: Record<string, string> = {
  llm_application: '大模型应用开发',
  prompt_engineering: 'Prompt 工程',
  rag_knowledge_base: 'RAG 知识库构建',
  agent_orchestration: 'Agent 编排',
}

const abilityRows = computed(() => radarLabels.map((label, index) => ({
  label,
  value: Math.max(0, Math.min(100, Number(report.value?.radar?.[index] || 0))),
})))
const sortedWeakKnowledge = computed(() => [...(report.value?.weak_knowledge || [])].sort((a, b) => b.weakness_level - a.weakness_level))
const contextSnapshot = computed<Record<string, unknown>>(() => report.value?.context_snapshot || {})
const directionList = computed(() => {
  const tags = (Array.isArray(contextSnapshot.value.direction_tags) ? contextSnapshot.value.direction_tags : report.value?.direction_tags) || []
  return tags.map(value => DIRECTION_LABELS[String(value)] || String(value))
})
const diagnosticAccuracy = computed(() => Math.round(Number(report.value?.diagnostic_summary?.accuracy || 0)))
const weakCount = computed(() => sortedWeakKnowledge.value.length)
const resourceTotal = computed(() => report.value?.resource_summary?.total || 0)
const pathNodes = computed<LearningPathNode[]>(() => report.value?.learning_path?.nodes || [])

function pathStatusLabel(status: LearningPathNode['status']) {
  return ({ locked: '未解锁', current: '当前学习', completed: '已完成', skipped: '已跳过' } as const)[status]
}

async function beginAssessment(nodeId: string) {
  const pathId = report.value?.learning_path?.path_id
  if (!pathId) return
  pathActionLoading.value = true
  pathMessage.value = ''
  try {
    assessment.value = await startPathNodeAssessment(pathId, nodeId)
  } catch {
    pathMessage.value = '节点验证失败，请稍后重试。'
  } finally { pathActionLoading.value = false }
}

async function submitNodeAnswer(nodeId: string, answer: number) {
  const pathId = report.value?.learning_path?.path_id
  if (!pathId || !assessment.value) return
  assessmentSubmitting.value = true
  try {
    const result = await answerPathNodeAssessment(pathId, nodeId, assessment.value.assessment_id, answer)
    assessment.value = null
    pathMessage.value = result.passed ? '验证通过，系统已自动推进到下一节点。' : '本次尚未通过，当前节点保持不变，可继续学习后再次验证。'
    showToast(result.passed ? '节点验证通过，路线已自动推进。' : '本次验证未通过，继续巩固当前节点。', result.passed ? 'success' : 'info')
    await loadReport()
  } catch { showToast('验证提交失败，请刷新后重试。', 'error') }
  finally { assessmentSubmitting.value = false }
}

function openNodeResource(node: LearningPathNode) {
  router.push({ path: '/resources', query: node.resource_task_id ? { task_id: node.resource_task_id } : {} })
}

async function generateNodeResources(node: LearningPathNode) {
  const pathId = report.value?.learning_path?.path_id
  if (!pathId || !report.value?.profile_id || !learnerId.value) return
  creatingGeneration.value = true
  try {
    const task = await createGenerationTask(report.value.domain_code, report.value.profile_id, learnerId.value, `学习路径第 ${node.path_order} 节：${node.title}`, { pathId, nodeId: node.path_node_id })
    router.push({ path: '/resources', query: { learner_id: learnerId.value, task_id: task.task_id } })
  } catch { showToast('创建节点学习包失败，路线可能已更新，请刷新后重试。', 'error') }
  finally { creatingGeneration.value = false }
}

function profileTypeLabel(type?: string) {
  return ({ beginner: '基础起步型学习者', intermediate: '进阶提升型学习者', advanced: '综合应用型学习者', practice_oriented: '实操导向型学习者' } as Record<string, string>)[type || ''] || type || '画像待确认'
}

function weaknessLabel(level: number) {
  if (level >= 4) return '优先补强'
  if (level === 3) return '重点巩固'
  return '持续练习'
}

function severityLevel(level: number) {
  if (level >= 4) return 'high'
  if (level === 3) return 'mid'
  return 'low'
}

async function loadReport() {
  if (!learnerId.value) {
    report.value = null
    errorMessage.value = '当前账号未关联有效学习者，请重新登录或联系管理员。'
    return
  }
  loading.value = true
  errorMessage.value = ''
  try {
    const data = await getLearningReport(learnerId.value, taskId.value || undefined)
    report.value = data.profile_ready ? data : null
  } catch { report.value = null; errorMessage.value = '无法读取学习报告，请确认后端服务可用。' }
  finally { loading.value = false }
}

async function handleNextAction(action: LearningReport['next_actions'][number]) {
  if (action.type !== 'generation') { router.push(action.route); return }
  if (!report.value?.profile_id || !learnerId.value) return
  creatingGeneration.value = true
  try {
    const readiness = await getDomainReadiness(report.value.domain_code)
    if (!readiness.generation_ready) {
      showToast(`当前领域尚未满足生成条件：${readiness.runtime_reasons?.join('、') || 'Candidate RAG 未就绪'}`, 'error')
      return
    }
    const task = await createGenerationTask(report.value.domain_code, report.value.profile_id, learnerId.value)
    router.push({ path: '/resources', query: { learner_id: learnerId.value, task_id: task.task_id } })
  } catch {
    showToast('创建学习包失败，请确认画像状态和生成环境后重试。', 'error')
  } finally { creatingGeneration.value = false }
}
watch(() => [route.query.learner_id, route.query.task_id], () => {
  loadReport()
})
onMounted(() => {
  loadReport()
  window.addEventListener('focus', loadReport)
})
onBeforeUnmount(() => window.removeEventListener('focus', loadReport))
</script>

<style scoped>
.report-page { gap: 20px; max-width: 1080px; margin: 0 auto; }

/* 通用卡片 */
.card { border: 1px solid var(--line); border-radius: 16px; background: #fff; padding: 24px 26px; box-shadow: 0 1px 2px rgb(16 24 40 / .03); }
.card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 18px; }
.card-head h2 { color: var(--ink); font-size: 17px; }
.section-note { margin-top: 4px; color: var(--muted); font-size: 12px; line-height: 1.5; }
.empty-state { display: grid; justify-items: center; gap: 8px; padding: 48px 32px; text-align: center; }
.empty-icon { font-size: 40px; }
.empty-state h2 { color: var(--ink); font-size: 18px; }
.empty-state p { max-width: 420px; color: var(--muted); font-size: 13px; line-height: 1.7; }
.empty-state .btn { margin-top: 12px; }

/* Hero 身份卡 */
.hero { display: flex; align-items: center; justify-content: space-between; gap: 24px; border: 1px solid #e2e8f2; border-radius: 16px; padding: 26px 28px; background: linear-gradient(135deg, #eef3ff 0%, #f8fafc 55%, #eef8f3 100%); }
.hero-kicker { color: var(--blue); font-size: 12px; font-weight: 750; }
.hero-id h2 { margin-top: 6px; color: var(--ink); font-size: 24px; }
.hero-id p { margin-top: 6px; color: var(--muted); font-size: 13px; line-height: 1.7; }
.hero-tags { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 14px; }
.hero-tag { border: 1px solid #dbe4f0; border-radius: 999px; background: rgb(255 255 255 / .7); color: #405067; padding: 5px 11px; font-size: 12px; }
.hero-stats { display: flex; gap: 12px; flex-shrink: 0; }
.hero-stats .stat { min-width: 92px; display: grid; gap: 4px; border: 1px solid rgb(255 255 255 / .8); border-radius: 12px; background: rgb(255 255 255 / .75); padding: 14px 16px; text-align: center; }
.hero-stats strong { color: var(--ink); font-size: 24px; line-height: 1; }
.hero-stats span { color: var(--muted); font-size: 11px; }

/* 两列网格 */
.report-grid { display: grid; grid-template-columns: 1fr; gap: 20px; align-items: start; }

/* 能力画像 */
.profile-body { display: grid; grid-template-columns: minmax(300px, 1fr) minmax(240px, .85fr); gap: 24px; align-items: center; }
.radar-wrap { min-width: 0; }
.ability-list { display: grid; gap: 16px; }
.ability-meta { display: flex; justify-content: space-between; gap: 12px; font-size: 13px; }
.ability-meta span { color: var(--muted); }
.ability-meta strong { color: var(--ink); font-size: 14px; }
.ability-track { height: 8px; margin-top: 7px; border-radius: 999px; background: #e8edf3; overflow: hidden; }
.ability-track i { display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg, #6a8bc0, var(--blue)); }

/* 学习闭环 */
.loop-progress { border-radius: 999px; background: var(--blue2); color: var(--blue); padding: 6px 10px; font-size: 12px; font-weight: 700; }
.loop-list { display: grid; gap: 10px; }
.loop-step { display: grid; grid-template-columns: 30px minmax(0, 1fr) auto; gap: 12px; align-items: center; border: 1px solid #edf1f6; border-radius: 12px; padding: 12px 14px; }
.loop-num { width: 28px; height: 28px; display: grid; place-items: center; border-radius: 8px; background: var(--soft); color: var(--muted); font-size: 13px; font-weight: 700; }
.loop-body strong { display: block; color: var(--ink); font-size: 13.5px; }
.loop-body small { display: block; margin-top: 2px; color: var(--muted); font-size: 11.5px; }
.loop-badge { border-radius: 6px; padding: 3px 8px; font-size: 11px; font-weight: 650; }
.loop-step.done .loop-num { background: var(--green2); color: var(--green); }
.loop-step.done .loop-badge { background: var(--green2); color: var(--green); }
.loop-step.stale .loop-num { background: var(--amber2); color: var(--amber); }
.loop-step.stale .loop-badge { background: var(--amber2); color: var(--amber); }
.loop-step.pending .loop-num { background: var(--soft); color: #9aa7b8; }
.loop-step.pending .loop-badge { background: var(--soft); color: #9aa7b8; }

/* 薄弱知识点 */
.weak-count { border-radius: 999px; background: var(--amber2); color: var(--amber); padding: 6px 10px; font-size: 12px; font-weight: 750; }
.weak-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; }
.weak-card { border: 1px solid #edf1f6; border-radius: 12px; background: var(--soft); padding: 14px 16px; }
.weak-card-head { display: flex; align-items: flex-start; gap: 10px; }
.weak-rank { width: 26px; height: 26px; flex-shrink: 0; display: grid; place-items: center; border-radius: 8px; background: #fff; color: var(--muted); font-size: 12px; font-weight: 700; }
.weak-title { min-width: 0; display: grid; gap: 6px; }
.weak-title h3 { min-width: 0; color: var(--ink); font-size: 13.5px; overflow-wrap: anywhere; }
.category-tag { justify-self: start; border-radius: 6px; background: #fff; color: var(--muted); padding: 3px 7px; font-size: 10px; }
.severity-meter { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: 14px; padding-top: 12px; border-top: 1px solid #e4eaf2; }
.severity-dots { display: inline-flex; gap: 4px; }
.severity-dots i { width: 22px; height: 5px; border-radius: 999px; background: #dfe5ed; }
.severity-badge { border-radius: 6px; padding: 3px 8px; font-size: 11px; font-weight: 650; }
.weak-card.high { border-color: #f0cfcf; background: #fff7f7; }
.weak-card.high .weak-rank { color: var(--red); }
.weak-card.high .severity-dots i.on { background: var(--red); }
.weak-card.high .severity-badge { background: #ffe4e4; color: var(--red); }
.weak-card.mid { border-color: #f0e0c2; background: #fffaf1; }
.weak-card.mid .weak-rank { color: var(--amber); }
.weak-card.mid .severity-dots i.on { background: var(--amber); }
.weak-card.mid .severity-badge { background: var(--amber2); color: var(--amber); }
.weak-card.low { border-color: #d6e9de; background: #f4fbf7; }
.weak-card.low .weak-rank { color: var(--green); }
.weak-card.low .severity-dots i.on { background: var(--green); }
.weak-card.low .severity-badge { background: var(--green2); color: var(--green); }
.weak-empty { display: flex; align-items: center; gap: 12px; border-radius: 12px; background: var(--green2); padding: 16px; color: var(--green); }
.weak-empty > span { width: 30px; height: 30px; display: grid; place-items: center; border-radius: 50%; background: #fff; font-weight: 800; }
.weak-empty p { margin-top: 4px; color: #3f735f; font-size: 11px; }

/* 学习路径 */
.path-h { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; }
.path-h-step { display: flex; align-items: flex-start; gap: 11px; border: 1px solid #edf1f6; border-radius: 12px; background: var(--soft); padding: 14px 15px; }
.path-node-copy { min-width: 0; flex: 1; }
.path-node-title { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.node-status { flex-shrink: 0; border-radius: 6px; padding: 3px 7px; background: #fff; color: var(--muted); font-size: 10px; }
.node-current { border-color: #b9caeb; background: #f5f8ff; }
.node-current .node-status { color: var(--blue); }
.node-completed { border-color: #cfe7d8; background: #f4fbf7; }
.node-completed .path-num { background: var(--green); }
.node-completed .node-status { color: var(--green); }
.node-locked { opacity: .72; }
.path-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.node-assessment { display: grid; gap: 9px; margin-top: 14px; border-top: 1px solid var(--line); padding-top: 14px; }
.node-assessment > span { color: var(--blue); font-size: 11px; font-weight: 700; }
.node-assessment > strong { color: var(--ink); font-size: 13px; line-height: 1.6; }
.node-assessment > button { width: 100%; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); color: var(--body); padding: 9px 11px; text-align: left; cursor: pointer; }
.node-assessment > button:hover { border-color: var(--blue); color: var(--blue); }
.node-assessment > button:disabled { cursor: wait; opacity: .6; }
.path-message { color: var(--blue) !important; }
.path-num { width: 30px; height: 30px; flex-shrink: 0; display: grid; place-items: center; border-radius: 50%; background: var(--blue); color: #fff; font-size: 13px; font-weight: 700; }
.path-h-step h3 { color: var(--ink); font-size: 13.5px; }
.path-h-step p { margin-top: 4px; color: var(--muted); font-size: 12px; line-height: 1.6; }

/* 最近资源 */
.table-wrap { width: 100%; overflow-x: auto; }
.resource-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.resource-table th { padding: 9px 12px; text-align: left; color: var(--muted); font-size: 12px; font-weight: 700; border-bottom: 1px solid var(--line); }
.resource-table td { padding: 11px 12px; border-bottom: 1px solid #edf0f4; color: #405067; }
.resource-table tr:last-child td { border-bottom: 0; }
.cell-title { color: var(--ink); font-weight: 600; }

/* 下一步 */
.next-card { display: flex; align-items: center; justify-content: space-between; gap: 20px; border-color: #cbd9f4; background: linear-gradient(135deg, #f5f8ff, #fafcff); }
.next-copy h2 { color: var(--ink); font-size: 17px; }
.next-copy p { margin-top: 5px; color: var(--muted); font-size: 13px; }
.next-actions { display: flex; gap: 8px; flex-shrink: 0; }

@media (max-width: 900px) {
  .profile-body { grid-template-columns: 1fr; }
}
@media (max-width: 640px) {
  .hero { flex-direction: column; align-items: flex-start; }
  .hero-stats { width: 100%; }
  .hero-stats .stat { flex: 1; }
  .next-card { flex-direction: column; align-items: flex-start; }
}
</style>
