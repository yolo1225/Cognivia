<template>
  <section class="page">
    <div class="head">
      <div><h1>用户管理</h1></div>
    </div>

    <div class="metrics">
      <div class="metric"><div><span>用户总数</span><b style="color:var(--green)">多领域档案</b></div><strong>{{ learners.length }}</strong><small>{{ learners.length }} 个有效用户</small></div>
      <div class="metric"><div><span>已完成诊断</span><b style="color:var(--green)">75%</b></div><strong>{{ learners.filter(l => l.profile_status === 'ready').length }}</strong><small>{{ learners.filter(l => l.profile_status !== 'ready').length }} 人等待首次诊断</small></div>
      <div class="metric"><div><span>学习档案已更新</span></div><strong>{{ learners.filter(l => l.profile_status === 'ready').length }}</strong><small>领域画像保留证据与版本</small></div>
      <div class="metric"><div><span>账号状态</span><b style="color:var(--green)">运行正常</b></div><strong>{{ learners.length }}</strong><small>全部已启用</small></div>
    </div>

    <div class="panel">
      <div class="panel-head">
        <div><h2>用户列表</h2><p class="sub">来自后端 /api/v1/learners</p></div>
        <button class="btn" @click="loadLearners">刷新列表</button>
      </div>
      <table>
        <thead><tr><th>用户</th><th>领域学习概况</th><th>已加入领域</th><th>最近领域状态</th><th>最近学习</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-if="loading"><td colspan="6" style="text-align:center;color:var(--muted)">加载中...</td></tr>
          <tr v-else-if="learners.length === 0"><td colspan="6" style="text-align:center;color:var(--muted)">暂无用户数据</td></tr>
          <tr v-for="user in learners" :key="user.learner_id">
            <td>
              <div class="learner-name">
                <span class="mini-avatar">{{ user.learner_id.slice(-1).toUpperCase() }}</span>
                <span><strong>{{ user.learner_id }} <span v-if="user.learner_id === 'learner_001'" class="tag">当前账号</span></strong><small>{{ user.profile_type || 'Python 基础' }}</small></span>
              </div>
            </td>
            <td>{{ user.target_domain || 'AI 应用开发' }}</td>
            <td><span class="tag">1 个领域</span></td>
            <td><span class="status" :class="user.profile_status === 'ready' ? 'ok' : 'wait'">{{ user.profile_status === 'ready' ? '已诊断' : '待诊断' }}</span></td>
            <td>{{ user.updated_at ? user.updated_at.slice(0, 10) : '-' }}</td>
            <td>
              <button class="btn text" @click="showToast('已打开用户档案')">查看用户档案</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useToast } from '@/composables/useToast'
import { listLearners, type LearnerSummary } from '@/api/learners'

const { showToast } = useToast()
const learners = ref<LearnerSummary[]>([])
const loading = ref(false)

async function loadLearners() {
  loading.value = true
  try {
    const data = await listLearners()
    learners.value = data
  } catch (e) {
    showToast('加载用户列表失败')
  } finally {
    loading.value = false
  }
}

onMounted(loadLearners)
</script>
