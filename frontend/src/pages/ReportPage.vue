<template>
  <section class="page">
    <div class="head"><div><h1>学习报告</h1><p class="sub">完成诊断测评后，系统将生成学习报告和个性化学习路径。</p></div></div>

    <div v-if="loading" class="panel" style="text-align:center;padding:40px;color:var(--muted)">加载报告中...</div>

    <div v-else-if="!report" class="panel" style="text-align:center;padding:60px;color:var(--muted)">
      <div style="font-size:36px;margin-bottom:12px">📋</div>
      <strong style="display:block;color:var(--ink);font-size:17px">尚未生成学习报告</strong>
      <p class="sub" style="margin-top:8px">
        请先完成<span style="color:var(--blue)">诊断测评</span>，系统将根据答题结果分析能力画像，<br>生成个性化学习路径和报告。
      </p>
      <button class="btn primary" style="margin-top:18px" @click="router.push('/diagnostic')">去诊断测评</button>
    </div>

    <template v-else>
      <div class="panel">
        <div class="panel-head"><h2>闭环状态</h2><span class="status" :class="report.feedback_summary?.learning_path_needs_refresh ? 'wait' : 'ok'">{{ report.feedback_summary?.learning_path_needs_refresh ? '路径待刷新' : '已同步' }}</span></div>
        <div class="mastery" style="grid-template-columns:repeat(3,1fr)">
          <div><span>诊断</span><strong :style="{ color: report.loop_status?.diagnosis === 'complete' ? 'var(--green)' : 'var(--amber)' }">{{ report.loop_status?.diagnosis || '-' }}</strong></div>
          <div><span>画像</span><strong :style="{ color: report.loop_status?.profile === 'complete' ? 'var(--green)' : 'var(--amber)' }">{{ report.loop_status?.profile || '-' }}</strong></div>
          <div><span>生成</span><strong :style="{ color: report.loop_status?.generation === 'complete' ? 'var(--green)' : 'var(--amber)' }">{{ report.loop_status?.generation || '-' }}</strong></div>
        </div>
      </div>

      <div v-if="report.diagnostic_summary?.answer_count" class="panel">
        <div class="panel-head"><h2>诊断统计</h2></div>
        <div class="metrics" style="grid-template-columns:repeat(3,1fr)">
          <div class="metric"><div><span>答题数</span></div><strong>{{ report.diagnostic_summary.answer_count }}</strong></div>
          <div class="metric"><div><span>正确率</span></div><strong>{{ ((report.diagnostic_summary.accuracy || 0) * 100).toFixed(0) }}%</strong></div>
          <div class="metric"><div><span>资源数</span></div><strong>{{ report.resource_summary?.total || 0 }}</strong></div>
        </div>
      </div>

      <div v-if="report.weak_knowledge?.length" class="panel">
        <div class="panel-head"><h2>薄弱知识点</h2></div>
        <div class="path">
          <div v-for="w in report.weak_knowledge" :key="w.knowledge_id" class="node">
            <div class="node-num">{{ w.weakness_level }}</div>
            <div><h3>{{ w.name }}</h3><p>{{ w.category }} · 弱点等级 {{ w.weakness_level }}</p></div>
          </div>
        </div>
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
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { getLearningReport, type LearningReport } from '@/api/reports'

const router = useRouter()
const report = ref<LearningReport | null>(null)
const loading = ref(false)

onMounted(async () => {
  loading.value = true
  try {
    const data = await getLearningReport('learner_001')
    // Only show report if a real diagnostic session was completed
    report.value = data.diagnostic_summary?.latest_session_id ? data : null
  } catch { report.value = null }
  finally { loading.value = false }
})
</script>
