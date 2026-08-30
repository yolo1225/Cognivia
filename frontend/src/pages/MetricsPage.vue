<template>
  <section class="page journey-page">
    <PageHeader title="学习历程" description="回顾能力变化、系统调整与下一步学习安排。">
      <template #meta>
        <span v-if="domainStore.currentDomainName" class="domain-tag">当前领域：{{ domainStore.currentDomainName }}</span>
      </template>
      <template #actions>
        <button class="btn" :disabled="loading" :aria-busy="loading" @click="loadJourney">{{ loading ? '正在刷新' : '刷新记录' }}</button>
        <button class="btn" @click="router.push('/dashboard')">返回首页</button>
      </template>
    </PageHeader>

    <PageState v-if="loading" type="loading" title="正在加载学习历程" />

    <div v-else-if="errorMessage" class="error-state">
      <strong>学习历程加载失败</strong>
      <p>{{ errorMessage }}</p>
      <button class="btn" @click="loadJourney">重新加载</button>
    </div>

    <template v-else-if="journey">
      <header class="journey-hero" aria-label="学习历程概览">
        <div class="journey-hero-copy">
          <span class="hero-kicker">学习闭环复盘</span>
          <h2>你的学习演进</h2>
          <p>从诊断起点到学习反馈，系统只记录真正影响学习路径与资源安排的关键变化。</p>
        </div>
        <dl class="journey-stats">
          <div><dt>学习进度</dt><dd>{{ pathProgressText }}</dd></div>
          <div><dt>薄弱项改善</dt><dd>{{ journey.overview.improved_knowledge_count }}</dd></div>
          <div><dt>反馈调整</dt><dd>{{ journey.overview.feedback_adjustment_count }}</dd></div>
          <div><dt>累计可用资源</dt><dd>{{ journey.overview.available_resource_count }}</dd></div>
        </dl>
      </header>

      <div v-if="journey.milestones.length === 0" class="card empty-state">
        <div class="empty-icon"><AppIcon name="history" /></div>
        <h2>还没有可回顾的学习历程</h2>
        <p>完成首次诊断后，这里会记录学习路线、资源调整和掌握验证带来的关键变化。</p>
        <button class="btn primary" @click="router.push('/dashboard')">开始首次诊断</button>
      </div>

      <template v-else>
        <section class="card journey-guide">
          <div class="guide-icon">◎</div>
          <div>
            <strong>看懂这条历程</strong>
            <p>每个节点都会说明发生了什么、系统为何调整、带来了什么结果；展开后可直接回到相关学习资源。</p>
          </div>
        </section>

        <section class="timeline" aria-label="关键学习里程碑">
          <article v-for="milestone in journey.milestones" :key="milestone.milestone_id" class="timeline-item">
            <div class="timeline-rail">
              <span class="timeline-dot" :class="`tone-${milestone.type}`" aria-hidden="true">{{ milestoneIcon(milestone.type) }}</span>
            </div>
            <div class="timeline-card" :class="{ expanded: expandedId === milestone.milestone_id, processing: milestone.status === 'in_progress' }">
              <button type="button" class="timeline-toggle" :aria-expanded="expandedId === milestone.milestone_id" @click="toggleMilestone(milestone.milestone_id)">
                <div class="event-head">
                  <div>
                    <span class="event-time">{{ formatDate(milestone.occurred_at) }}</span>
                    <h3>{{ milestone.title }}</h3>
                  </div>
                  <div class="event-state">
                    <span class="status" :class="milestone.status === 'in_progress' ? 'wait' : 'ok'">{{ milestone.status === 'in_progress' ? '处理中' : '已完成' }}</span>
                    <span class="expand-indicator" aria-hidden="true">⌄</span>
                  </div>
                </div>
                <p class="event-summary">{{ milestone.summary }}</p>
              </button>

              <div v-if="expandedId === milestone.milestone_id" class="event-detail">
                <div class="detail-block">
                  <span>这次带来的结果</span>
                  <strong>{{ milestone.outcome }}</strong>
                </div>
                <div v-if="milestone.knowledge_names.length" class="detail-block">
                  <span>关联学习重点</span>
                  <div class="knowledge-chips"><i v-for="name in milestone.knowledge_names" :key="name">{{ name }}</i></div>
                </div>
                <div v-if="milestone.resources.length" class="detail-block">
                  <span>相关学习资源</span>
                  <div class="resource-list">
                    <div v-for="resource in milestone.resources" :key="resource.resource_id" class="resource-row">
                      <div><strong>{{ resource.title }}</strong><small>{{ resource.resource_type_label }} · 难度 {{ resource.difficulty }}</small></div>
                    </div>
                  </div>
                </div>
                <div v-if="milestone.actions.length" class="detail-actions">
                  <button v-for="action in milestone.actions" :key="`${milestone.milestone_id}-${action.type}`" class="btn" :class="{ primary: action.type === 'continue_learning' }" @click="navigate(action.route)">{{ action.label }}</button>
                </div>
              </div>
            </div>
          </article>
        </section>
      </template>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { getLearningJourney, type LearningJourney, type LearningJourneyMilestone } from '@/api/reports'
import { getLearnerProfile } from '@/api/learners'
import { formatBeijingDateTime } from '@/utils/dateTime'
import AppIcon from '@/components/Shared/AppIcon.vue'
import PageHeader from '@/components/Shared/PageHeader.vue'
import PageState from '@/components/Shared/PageState.vue'
import { useAuthStore } from '@/stores/authStore'
import { useDomainStore } from '@/stores/domainStore'

const router = useRouter()
const authStore = useAuthStore()
const domainStore = useDomainStore()
const journey = ref<LearningJourney | null>(null)
const loading = ref(false)
const errorMessage = ref('')
const expandedId = ref('')

const learnerId = computed(() => String(authStore.user?.learner_id || '').trim())
const pathProgressText = computed(() => {
  if (!journey.value) return '—'
  return `${journey.value.overview.path_completed}/${journey.value.overview.path_total}`
})

function milestoneIcon(type: LearningJourneyMilestone['type']) {
  return ({ initial_diagnosis: '◎', resource_generation: '✦', feedback_adjustment: '↻', path_progress: '✓', knowledge_refresh: '↻', profile_update: '↑' } as const)[type]
}
function formatDate(value: string) { return formatBeijingDateTime(value) }
function toggleMilestone(id: string) { expandedId.value = expandedId.value === id ? '' : id }
function navigate(route: string) { router.push(route) }

async function initializeDomainScope() {
  if (!learnerId.value) throw new Error('LEARNER_NOT_ASSOCIATED')
  const profile = await getLearnerProfile(learnerId.value)
  await domainStore.initialize(profile.domain_code)
}
async function loadJourney() {
  if (!learnerId.value) { errorMessage.value = '当前账号未关联学习者，无法读取学习历程。'; return }
  loading.value = true
  errorMessage.value = ''
  try {
    journey.value = await getLearningJourney(learnerId.value)
    if (!expandedId.value && journey.value.milestones.length) expandedId.value = journey.value.milestones[0].milestone_id
  } catch {
    errorMessage.value = '无法读取学习历程，请确认后端服务可用后重试。'
  } finally {
    loading.value = false
  }
}

watch(() => domainStore.selectionVersion, () => { expandedId.value = ''; loadJourney() })
onMounted(async () => {
  try { await initializeDomainScope() }
  catch { errorMessage.value = '无法确定当前学习领域，请返回首页重新选择。' }
  await loadJourney()
})
</script>

<style scoped>
.journey-page { gap: 18px; max-width: 1080px; margin: 0 auto; }
.card { border: 1px solid var(--line); border-radius: 16px; background: var(--panel); padding: 24px 26px; box-shadow: var(--shadow-card); }
.domain-tag { display: inline-flex; margin-top: 9px; border-radius: 6px; background: var(--soft); color: var(--body); padding: 5px 8px; font-size: 12px; white-space: nowrap; }
.error-state { display: grid; justify-items: center; gap: 8px; padding: 48px 32px; border: 1px solid var(--line-danger); border-radius: 16px; background: var(--red2); color: var(--red); text-align: center; }.error-state p { color: inherit; font-size: 13px; }.error-state .btn { margin-top: 8px; }
.empty-state { display: grid; justify-items: center; gap: 8px; padding: 48px 32px; text-align: center; }.empty-icon { font-size: 40px; }.empty-state h2 { color: var(--ink); font-size: 18px; }.empty-state p { max-width: 450px; color: var(--muted); font-size: 13px; line-height: 1.7; }.empty-state .btn { margin-top: 12px; }
.journey-hero { display: flex; align-items: center; justify-content: space-between; gap: 24px; border: 1px solid #e2e8f2; border-radius: 16px; padding: 24px 26px; background: linear-gradient(135deg, #eef3ff 0%, #f8fafc 55%, #eef8f3 100%); }.journey-hero-copy { min-width: 0; }.hero-kicker { color: var(--blue); font-size: 12px; font-weight: 750; }.journey-hero h2 { margin-top: 6px; color: var(--ink); font-size: 22px; }.journey-hero p { max-width: 530px; margin-top: 6px; color: var(--muted); font-size: 13px; line-height: 1.7; }
.journey-stats { display: grid; grid-template-columns: repeat(2, minmax(96px, 1fr)); gap: 8px; flex: 0 0 252px; margin: 0; }.journey-stats div { min-width: 0; display: grid; gap: 4px; border: 1px solid rgb(255 255 255 / .8); border-radius: 10px; background: rgb(255 255 255 / .75); padding: 13px 14px; text-align: center; }.journey-stats dt { color: var(--muted); font-size: 11px; }.journey-stats dd { margin: 0; color: var(--ink); font-size: 24px; font-weight: 760; line-height: 1; }
.journey-guide { display: flex; align-items: center; gap: 13px; padding: 15px 18px; }.guide-icon { width: 32px; height: 32px; display: grid; flex: 0 0 auto; place-items: center; border-radius: 50%; background: var(--blue2); color: var(--blue); font-size: 18px; font-weight: 750; }.journey-guide strong { color: var(--ink); font-size: 13px; }.journey-guide p { margin-top: 3px; color: var(--muted); font-size: 12px; line-height: 1.6; }
.timeline { display: grid; gap: 0; }.timeline-item { display: grid; grid-template-columns: 40px minmax(0, 1fr); gap: 14px; }.timeline-rail { display: flex; justify-content: center; position: relative; }.timeline-rail::before { position: absolute; top: 0; bottom: -16px; left: 50%; width: 2px; background: var(--track); content: ''; transform: translateX(-50%); }.timeline-item:last-child .timeline-rail::before { display: none; }.timeline-dot { position: relative; z-index: 1; width: 34px; height: 34px; display: grid; place-items: center; border: 1px solid var(--line); border-radius: 50%; background: var(--panel); color: var(--muted); font-size: 15px; font-weight: 750; }.tone-initial_diagnosis,.tone-resource_generation,.tone-profile_update { border-color: #cbd9f4; background: var(--blue2); color: var(--blue); }.tone-feedback_adjustment,.tone-path_progress { border-color: #bfe4d2; background: var(--green2); color: var(--green); }.tone-knowledge_refresh { border-color: #f0d2ac; background: var(--amber2); color: var(--amber); }
.timeline-card { min-width: 0; margin-bottom: 16px; overflow: hidden; border: 1px solid var(--line); border-radius: 14px; background: var(--panel); transition: border-color var(--transition-fast), box-shadow var(--transition-fast); }.timeline-card:hover,.timeline-card.expanded { border-color: #9db6ee; box-shadow: 0 2px 6px rgb(31 48 75 / .08); }.timeline-card.processing { border-style: dashed; }.timeline-toggle { width: 100%; border: 0; background: transparent; color: inherit; padding: 16px 18px; font: inherit; text-align: left; cursor: pointer; }.timeline-toggle:focus-visible { outline: 0; box-shadow: inset 0 0 0 3px rgb(49 95 206 / .18); }.event-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }.event-time { display: block; color: var(--muted); font-size: 11px; }.event-head h3 { margin-top: 3px; color: var(--ink); font-size: 15px; }.event-state { display: flex; align-items: center; gap: 8px; flex: 0 0 auto; }.expand-indicator { color: var(--muted); font-size: 17px; line-height: 1; transition: transform var(--transition-fast); }.timeline-card.expanded .expand-indicator { transform: rotate(180deg); }.event-summary { margin-top: 8px; color: var(--body); font-size: 12.5px; line-height: 1.65; }
.event-detail { display: grid; gap: 15px; border-top: 1px solid var(--line); padding: 16px 18px 18px; }.detail-block { display: grid; gap: 7px; }.detail-block > span { color: var(--muted); font-size: 11px; }.detail-block > strong { color: var(--ink); font-size: 13px; line-height: 1.6; }.knowledge-chips { display: flex; flex-wrap: wrap; gap: 6px; }.knowledge-chips i { border-radius: 999px; background: var(--soft); color: var(--body); padding: 4px 9px; font-size: 11px; font-style: normal; }.resource-list { display: grid; gap: 7px; }.resource-row { border: 1px solid #edf1f6; border-radius: 9px; padding: 9px 11px; }.resource-row div { display: grid; gap: 3px; }.resource-row strong { color: var(--ink); font-size: 12.5px; }.resource-row small { color: var(--muted); font-size: 11px; }.detail-actions { display: flex; flex-wrap: wrap; gap: 8px; padding-top: 2px; }
.app.theme-dark .journey-hero { border-color: var(--line); background: var(--surface-raised); }.app.theme-dark .journey-stats div { border-color: var(--line); background: var(--panel); }.app.theme-dark .timeline-card:hover,.app.theme-dark .timeline-card.expanded { border-color: var(--line-info); }.app.theme-dark .resource-row { border-color: var(--line); }
/* These styles apply on both themes; the variables supply the active palette. */
.journey-hero { border-color: var(--line); background: var(--surface-raised); }
.journey-stats div { border-color: var(--line); background: var(--surface-raised); }
.tone-initial_diagnosis,.tone-resource_generation,.tone-profile_update { border-color: var(--line-info); }
.tone-feedback_adjustment,.tone-path_progress { border-color: var(--line-success); }
.tone-knowledge_refresh { border-color: var(--line-warning); }
.timeline-card:hover,.timeline-card.expanded { border-color: var(--line-info); box-shadow: var(--shadow-card); }
.timeline-toggle:focus-visible { box-shadow: inset 0 0 0 3px var(--focus-ring); }
.resource-row { border-color: var(--line-subtle); }
@media (max-width: 700px) { .journey-hero { align-items: flex-start; flex-direction: column; }.journey-stats { width: 100%; flex-basis: auto; } }
@media (max-width: 560px) { .timeline-item { grid-template-columns: 28px minmax(0, 1fr); gap: 8px; }.timeline-dot { width: 28px; height: 28px; font-size: 12px; }.timeline-toggle,.event-detail { padding: 14px; }.event-head { align-items: stretch; flex-direction: column; }.event-state { justify-content: space-between; } }
</style>
