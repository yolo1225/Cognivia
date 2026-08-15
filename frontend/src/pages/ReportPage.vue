<template>
  <section class="page">
    <div class="head">
      <div><h1>学习报告</h1><p class="sub">集中查看能力画像、薄弱知识与当前推荐学习路径。</p></div>
      <div class="actions"><span class="tag">当前学习者：{{ learnerId }}</span><button class="btn" :disabled="loading" @click="loadReport">{{ loading ? '刷新中...' : '刷新报告' }}</button></div>
    </div>

    <div v-if="loading" class="panel" style="text-align:center;padding:40px;color:var(--muted)">加载报告中...</div>

    <div v-else-if="errorMessage" class="error-state"><strong>报告加载失败</strong><p>{{ errorMessage }}</p><button class="btn" @click="loadReport">重新加载</button></div>

    <div v-else-if="!report" class="panel" style="text-align:center;padding:60px;color:var(--muted)">
      <div style="font-size:36px;margin-bottom:12px">📋</div>
      <strong style="display:block;color:var(--ink);font-size:17px">尚未生成学习报告</strong>
      <p class="sub" style="margin-top:8px">
        请先完成<span style="color:var(--blue)">诊断训练</span>，系统将根据答题结果分析能力画像，<br>生成个性化学习路径和报告。
      </p>
      <button class="btn primary" style="margin-top:18px" @click="router.push('/diagnostic')">去诊断训练</button>
    </div>

    <template v-else>
      <div class="panel profile-overview">
        <div class="panel-head">
          <div><h2>能力画像</h2><p class="section-note">基于最近一次诊断训练结果生成</p></div>
          <span class="profile-badge">{{ profileTypeLabel(report.profile_type) }}</span>
        </div>
        <div class="profile-layout">
          <div class="radar-wrap"><RadarChart :values="report.radar" /></div>
          <div class="ability-list">
            <div v-for="item in abilityRows" :key="item.label" class="ability-row">
              <div><span>{{ item.label }}</span><strong>{{ item.value }}</strong></div>
              <div class="ability-track" role="progressbar" :aria-label="item.label" aria-valuemin="0" aria-valuemax="100" :aria-valuenow="item.value">
                <i :style="{ width: `${item.value}%` }"></i>
              </div>
            </div>
          </div>
        </div>
        <div v-if="report.diagnostic_summary?.answer_count" class="diagnostic-strip">
          <div><span>已完成题目</span><strong>{{ report.diagnostic_summary.answer_count }}</strong></div>
          <div><span>诊断正确率</span><strong>{{ (report.diagnostic_summary.accuracy || 0).toFixed(0) }}%</strong></div>
          <div><span>当前学习资源</span><strong>{{ report.resource_summary?.total || 0 }}</strong></div>
        </div>
      </div>

      <div class="panel weakness-panel">
        <div class="panel-head">
          <div><h2>薄弱知识点</h2><p class="section-note">按薄弱程度排序，优先处理高等级项目</p></div>
          <span v-if="sortedWeakKnowledge.length" class="weak-count">{{ sortedWeakKnowledge.length }} 项待巩固</span>
        </div>
        <div v-if="sortedWeakKnowledge.length" class="weak-list">
          <div v-for="(item, index) in sortedWeakKnowledge" :key="item.knowledge_id" class="weak-row">
            <div class="weak-rank">{{ String(index + 1).padStart(2, '0') }}</div>
            <div class="weak-main">
              <div class="weak-title"><h3>{{ item.name }}</h3><span class="category-tag">{{ item.category }}</span></div>
              <div class="severity-track" role="progressbar" :aria-label="`${item.name}薄弱程度`" aria-valuemin="1" aria-valuemax="5" :aria-valuenow="item.weakness_level">
                <i v-for="level in 5" :key="level" :class="{ active: level <= item.weakness_level, high: item.weakness_level >= 4 }"></i>
              </div>
            </div>
            <div class="severity-copy" :class="{ high: item.weakness_level >= 4 }">
              <strong>{{ item.weakness_level }}/5</strong><span>{{ weaknessLabel(item.weakness_level) }}</span>
            </div>
          </div>
        </div>
        <div v-else class="weak-empty"><span aria-hidden="true">✓</span><div><strong>当前没有已确认的薄弱知识点</strong><p>继续完成训练与分阶测试，报告会根据有效证据更新。</p></div></div>
      </div>

      <div class="panel">
        <div class="panel-head"><h2>推荐学习路径</h2><span class="status" :class="report.feedback_summary?.learning_path_needs_refresh?'wait':'ok'">{{ report.feedback_summary?.learning_path_needs_refresh?'待刷新':'当前版本' }}</span></div>
        <div v-if="report.path_detail?.length" class="path"><div v-for="(stage,index) in report.path_detail" :key="index" class="node"><div class="node-num">{{ index+1 }}</div><div><h3>{{ stage.name }}</h3><p>{{ stage.description || '根据当前画像推荐' }}</p></div></div></div><div v-else class="empty-hint">尚未形成可展示的学习路径。</div>
      </div>

      <div v-if="report.resource_summary?.recent?.length" class="panel">
        <div class="panel-head"><h2>最近资源</h2></div>
        <table><thead><tr><th>资源</th><th>类型</th><th>难度</th><th>审核状态</th><th>来源数</th></tr></thead>
          <tbody>
            <tr v-for="r in report.resource_summary.recent" :key="r.resource_id">
              <td>{{ r.title }}</td><td><span class="tag">{{ r.resource_type_label || r.resource_type }}</span></td><td>{{ r.difficulty }}/5</td>
              <td><span class="status" :class="r.review_status === 'passed' ? 'ok' : 'wait'">{{ r.review_status }}</span></td>
              <td>{{ r.source_count }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="report.next_actions?.length" class="panel">
        <div class="panel-head"><h2>建议下一步</h2></div>
        <div class="actions">
          <button v-for="a in report.next_actions" :key="a.type" class="btn" :class="{ primary: a.type === 'generate' }" @click="router.push(a.route)">{{ a.label }}</button>
        </div>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getLearningReport, type LearningReport } from '@/api/reports'
import RadarChart from '@/components/Charts/RadarChart.vue'
import { useLearnerStore } from '@/stores/learnerStore'

const router = useRouter()
const route = useRoute()
const learnerStore = useLearnerStore()
const learnerId = computed(() => {
  const normalized = String(route.query.learner_id || learnerStore.selectedLearnerId || '').trim()
  return ['null', 'undefined'].includes(normalized.toLowerCase()) ? '' : normalized
})
const report = ref<LearningReport | null>(null)
const loading = ref(false)
const errorMessage = ref('')
const radarLabels = ['理论基础', '实操能力', '问题解决', '知识广度', '学习速度']
const abilityRows = computed(() => radarLabels.map((label, index) => ({
  label,
  value: Math.max(0, Math.min(100, Number(report.value?.radar?.[index] || 0))),
})))
const sortedWeakKnowledge = computed(() => [...(report.value?.weak_knowledge || [])].sort((a, b) => b.weakness_level - a.weakness_level))

function profileTypeLabel(type?: string) {
  return ({ beginner: '基础起步型', intermediate: '进阶提升型', advanced: '综合应用型', practice_oriented: '实操导向型' } as Record<string, string>)[type || ''] || type || '画像待确认'
}

function weaknessLabel(level: number) {
  if (level >= 4) return '优先补强'
  if (level === 3) return '重点巩固'
  return '持续练习'
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
    const data = await getLearningReport(learnerId.value)
    // Only show report if a real diagnostic session was completed
    report.value = data.diagnosis_completed ? data : null
  } catch { report.value = null; errorMessage.value = '无法读取学习报告，请确认后端服务可用。' }
  finally { loading.value = false }
}
watch(() => route.query.learner_id, (value) => {
  const nextLearnerId = String(value || '').trim()
  if (nextLearnerId) learnerStore.setSelectedLearner(nextLearnerId)
  loadReport()
})
onMounted(() => {
  if (learnerId.value) learnerStore.setSelectedLearner(learnerId.value)
  loadReport()
  window.addEventListener('focus', loadReport)
})
onBeforeUnmount(() => window.removeEventListener('focus', loadReport))
</script>

<style scoped>
.section-note { margin-top: 4px; color: var(--muted); font-size: 11px; line-height: 1.5; }
.profile-badge, .weak-count {
  border-radius: 999px;
  background: var(--blue2);
  color: var(--blue);
  padding: 6px 10px;
  font-size: 12px;
  font-weight: 750;
}
.profile-layout { display: grid; grid-template-columns: minmax(320px, .9fr) minmax(300px, 1.1fr); gap: 28px; align-items: center; }
.radar-wrap { min-width: 0; }
.ability-list { display: grid; gap: 17px; }
.ability-row > div:first-child { display: flex; justify-content: space-between; gap: 12px; font-size: 13px; }
.ability-row span { color: var(--muted); }
.ability-row strong { font-size: 14px; }
.ability-track { height: 7px; margin-top: 7px; border-radius: 999px; background: #e8edf3; overflow: hidden; }
.ability-track i { display: block; height: 100%; border-radius: inherit; background: var(--blue); }
.diagnostic-strip { display: grid; grid-template-columns: repeat(3, 1fr); margin-top: 8px; border-top: 1px solid var(--line); padding-top: 18px; }
.diagnostic-strip div { padding: 0 18px; border-right: 1px solid var(--line); }
.diagnostic-strip div:first-child { padding-left: 0; }
.diagnostic-strip div:last-child { border-right: 0; }
.diagnostic-strip span { color: var(--muted); font-size: 11px; }
.diagnostic-strip strong { display: block; margin-top: 5px; font-size: 20px; }
.weak-count { background: var(--amber2); color: var(--amber); }
.weak-list { border-top: 1px solid var(--line); }
.weak-row { display: grid; grid-template-columns: 38px minmax(0, 1fr) auto; gap: 14px; align-items: center; padding: 16px 2px; border-bottom: 1px solid #edf0f4; }
.weak-row:last-child { border-bottom: 0; padding-bottom: 2px; }
.weak-rank { color: #8a97a9; font: 700 12px Consolas, monospace; }
.weak-title { display: flex; align-items: center; gap: 9px; min-width: 0; }
.weak-title h3 { min-width: 0; overflow-wrap: anywhere; }
.category-tag { flex: 0 0 auto; border-radius: 6px; background: var(--soft); color: var(--muted); padding: 3px 7px; font-size: 10px; }
.severity-track { display: grid; grid-template-columns: repeat(5, minmax(20px, 58px)); gap: 5px; margin-top: 9px; }
.severity-track i { height: 5px; border-radius: 999px; background: #e5eaf0; }
.severity-track i.active { background: var(--amber); }
.severity-track i.active.high { background: var(--red); }
.severity-copy { min-width: 72px; color: var(--amber); text-align: right; }
.severity-copy.high { color: var(--red); }
.severity-copy strong, .severity-copy span { display: block; }
.severity-copy strong { font-size: 16px; }
.severity-copy span { margin-top: 3px; font-size: 10px; }
.weak-empty { display: flex; align-items: center; gap: 12px; border-radius: 10px; background: var(--green2); padding: 16px; color: var(--green); }
.weak-empty > span { width: 30px; height: 30px; display: grid; place-items: center; border-radius: 50%; background: #fff; font-weight: 800; }
.weak-empty p { margin-top: 4px; color: #3f735f; font-size: 11px; }
@media (max-width: 900px) { .profile-layout { grid-template-columns: 1fr; gap: 4px; } }
@media (max-width: 600px) {
  .diagnostic-strip { grid-template-columns: 1fr; }
  .diagnostic-strip div, .diagnostic-strip div:first-child { padding: 10px 0; border-right: 0; border-bottom: 1px solid var(--line); }
  .diagnostic-strip div:last-child { border-bottom: 0; }
  .weak-row { grid-template-columns: 28px minmax(0, 1fr); }
  .severity-copy { grid-column: 2; display: flex; gap: 6px; align-items: baseline; text-align: left; }
}
</style>
