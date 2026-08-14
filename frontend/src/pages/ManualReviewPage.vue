<template>
  <section class="page">
    <div class="head"><div><h1>人工复核</h1></div></div>

    <div v-if="pendingCount > 0" class="review-banner">
      <div><strong>{{ pendingCount }} 项等待人工决定</strong><p style="margin-top:5px;font-size:12px">请在详情中逐一复核。</p></div>
      <span class="status wait">待处理</span>
    </div>

    <div class="panel">
      <div class="panel-head"><div><h2>复核列表</h2></div><div class="filterbar">
          <select class="field" v-model="statusFilter" @change="load"><option value="">全部状态</option><option value="pending">待处理</option><option value="approved">已批准</option><option value="rejected">已驳回</option></select>
          <button class="btn" @click="load" :disabled="loading">刷新</button>
      </div></div>
      <table><thead><tr><th>复核ID</th><th>任务ID</th><th>原因</th><th>状态</th><th>决定</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-if="loading"><td colspan="6" style="text-align:center;color:var(--muted)">加载中...</td></tr>
          <tr v-else-if="reviews.length === 0"><td colspan="6" style="text-align:center;color:var(--muted)">暂无数据</td></tr>
          <tr v-for="r in reviews" :key="r.manual_review_id">
            <td>{{ r.manual_review_id?.slice(0,8) }}</td>
            <td>{{ r.task_id?.slice(0,12) }}</td>
            <td>{{ r.trigger_reason }}</td>
            <td><span class="status" :class="r.status === 'pending' ? 'wait' : 'ok'">{{ r.status }}</span></td>
            <td>{{ r.decision || '-' }}</td>
            <td>
              <button v-if="r.status === 'pending'" class="btn primary small" @click="openDecision(r)">复核</button>
              <span v-else>{{ r.reviewed_by || '-' }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="deciding" class="panel cols" style="margin-top:14px">
      <div class="panel">
        <h2>管理员决定</h2>
        <p class="sub">复核意见将写入原任务并沿同一 task_id 恢复执行。</p>
        <textarea v-model="comment" placeholder="填写复核依据，必填"></textarea>
        <div class="actions" style="margin-top:10px">
          <button class="btn" @click="decide('reject')" :disabled="submitting">驳回资源</button>
          <button class="btn" @click="decide('request_revision')" :disabled="submitting">要求修订</button>
          <button class="btn primary" @click="decide('approve')" :disabled="submitting">批准发布</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useToast } from '@/composables/useToast'
import { listManualReviews, decideManualReview, type ManualReviewItem } from '@/api/manualReviews'

const { showToast } = useToast()
const reviews = ref<ManualReviewItem[]>([])
const loading = ref(false)
const submitting = ref(false)
const statusFilter = ref('')
const deciding = ref<ManualReviewItem | null>(null)
const comment = ref('')
const pendingCount = ref(0)

async function load() {
  loading.value = true
  try {
    reviews.value = await listManualReviews(statusFilter.value || undefined)
    pendingCount.value = reviews.value.filter(r => r.status === 'pending').length
  } catch { showToast('加载复核列表失败') }
  finally { loading.value = false }
}

function openDecision(r: ManualReviewItem) { deciding.value = r; comment.value = '' }

async function decide(d: 'approve' | 'request_revision' | 'reject') {
  if (!deciding.value || !comment.value) { showToast('请填写复核依据'); return }
  submitting.value = true
  try {
    await decideManualReview(deciding.value.manual_review_id, d, comment.value)
    showToast('复核决定已保存，原任务正在恢复执行')
    deciding.value = null
    await load()
  } catch { showToast('操作失败') }
  finally { submitting.value = false }
}

onMounted(load)
</script>
