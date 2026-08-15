<template>
  <section class="page">
    <div class="head"><div><h1>学习报告</h1></div></div>

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
        <table><thead><tr><th>资源</th><th>类型</th><th>难度</th></tr></thead>
          <tbody>
            <tr v-for="r in report.resource_summary.recent" :key="r.resource_id">
              <td>{{ r.title }}</td><td><span class="tag">{{ r.resource_type_label || r.resource_type }}</span></td><td>{{ r.difficulty }}/5</td>
            </tr>
          </tbody>
        </table>
      </div>

    </template>
  </section>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { getLearningReport, type LearningReport } from '@/api/reports'
import { mockReport } from '@/mocks/report'

const router = useRouter()
const report = ref<LearningReport | null>(null)
const loading = ref(false)

onMounted(async () => {
  loading.value = true
  try {
    const data = await getLearningReport('learner_001')
    // 优先使用真实报告；无诊断会话时回退到演示假数据，方便 UI 优化
    report.value = data.diagnostic_summary?.latest_session_id ? data : mockReport
  } catch { report.value = mockReport }
  finally { loading.value = false }
})
</script>
