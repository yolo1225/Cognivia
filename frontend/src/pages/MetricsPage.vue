<template>
  <section class="page">
    <div class="head">
      <div><h1>任务记录</h1></div>
      <div class="actions">
        <button class="btn" @click="router.push('/dashboard')">创建生成任务</button>
      </div>
    </div>

    <div class="panel">
      <div class="panel-head"><div><h2>生成任务</h2></div></div>
      <table>
        <thead><tr><th>任务</th><th>状态</th><th>时间</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-if="tasks.length === 0"><td colspan="4" style="text-align:center;color:var(--muted)">暂无任务记录</td></tr>
          <tr v-for="task in tasks" :key="task.task_id" class="task-record-row">
            <td><strong>{{ task.task_id }}</strong></td>
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
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from '@/composables/useToast'

const router = useRouter()
const { showToast } = useToast()

const tasks = ref<Array<{ task_id: string; status: string; time: string }>>([])
</script>
