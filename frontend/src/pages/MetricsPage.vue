<template>
  <section class="page">
    <div class="head">
      <div><h1>任务记录</h1><p class="sub">查看每次个性化生成任务做了什么、产生了哪些资源，以及该次审核与评测结果。</p></div>
      <div class="actions">
        <button class="btn" @click="router.push('/dashboard')">创建生成任务</button>
      </div>
    </div>

    <div class="metrics">
      <div class="metric"><div><span>任务总数</span></div><strong>{{ tasks.length }}</strong><small>成功 {{ tasks.filter(t => t.status === 'completed').length }}</small></div>
      <div class="metric" v-if="evalSummary">
        <div><span>平均事实准确率</span><b :style="{ color: evalSummary.status === 'passed' ? 'var(--green)' : 'var(--amber)' }">{{ evalSummary.status === 'passed' ? '达标' : '待评估' }}</b></div>
        <strong>{{ evalSummary.metrics.hallucination_rate ? (100 - (evalSummary.metrics.hallucination_rate.ratio || 0) * 100).toFixed(1) : '-' }}%</strong>
        <small>目标 &lt; 5% 幻觉率</small>
      </div>
      <div class="metric" v-if="evalSummary">
        <div><span>难度匹配</span></div>
        <strong>{{ evalSummary.metrics.difficulty_match_accuracy?.ratio ? (evalSummary.metrics.difficulty_match_accuracy.ratio * 100).toFixed(1) : '-' }}%</strong>
        <small>目标 ≥ 85%</small>
      </div>
      <div class="metric" v-if="evalSummary">
        <div><span>核心覆盖</span></div>
        <strong>{{ evalSummary.metrics.core_knowledge_coverage?.ratio ? (evalSummary.metrics.core_knowledge_coverage.ratio * 100).toFixed(1) : '-' }}%</strong>
        <small>目标 ≥ 90%</small>
      </div>
    </div>

    <div class="panel">
      <div class="panel-head"><div><h2>生成任务</h2></div></div>
      <table>
        <thead><tr><th>任务</th><th>用户</th><th>状态</th><th>时间</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-if="tasks.length === 0"><td colspan="5" style="text-align:center;color:var(--muted)" @click="loadTasks">点击刷新加载任务</td></tr>
          <tr v-for="task in tasks" :key="task.task_id" class="task-record-row">
            <td><strong>{{ task.task_id }}</strong></td>
            <td>{{ task.learner_id || '-' }}</td>
            <td><span class="status" :class="task.status === 'completed' ? 'ok' : 'wait'">{{ task.status }}</span></td>
            <td>{{ task.time }}</td>
            <td><button class="btn text" @click="showToast('已打开任务详情')">查看详情</button></td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from '@/composables/useToast'
import { getEvaluationSummary, type EvaluationSummary } from '@/api/evaluations'

const router = useRouter()
const { showToast } = useToast()

const tasks = ref<Array<{ task_id: string; learner_id?: string; status: string; time: string }>>([])
const evalSummary = ref<EvaluationSummary | null>(null)

async function loadTasks() {
  try {
    const summary = await getEvaluationSummary('live')
    evalSummary.value = summary
  } catch {
    // evaluation may not have been run yet
  }
}

onMounted(loadTasks)
</script>
