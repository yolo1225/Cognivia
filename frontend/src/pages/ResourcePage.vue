<template>
  <section class="page">
    <div class="head">
      <div><h1>个性化学习资源</h1><p class="sub">完成诊断测评后，系统将根据画像生成个性化学习资源。</p></div>
      <div class="actions">
        <button class="btn" @click="loadResources" :disabled="loading">刷新资源</button>
        <button class="btn primary" @click="router.push('/diagnostic')">去诊断测评</button>
      </div>
    </div>

    <div v-if="loading" class="panel" style="text-align:center;padding:40px;color:var(--muted)">加载中...</div>

    <div v-else-if="resources.length === 0" class="panel" style="text-align:center;padding:60px;color:var(--muted)">
      <div style="font-size:36px;margin-bottom:12px">📚</div>
      <strong style="display:block;color:var(--ink);font-size:17px">暂无学习资源</strong>
      <p class="sub" style="margin-top:8px">
        请先完成<span style="color:var(--blue)">诊断测评</span>，系统将根据你的答题情况分析知识薄弱点，<br>然后<span style="color:var(--blue)">生成个性化学习资源</span>（讲义、实操指南、分阶测试）。
      </p>
      <button class="btn primary" style="margin-top:18px" @click="router.push('/diagnostic')">开始诊断测评</button>
    </div>

    <template v-else>
      <div class="panel" style="margin-bottom:14px">
        <div class="panel-head"><div><h2>学习资源列表</h2><p class="sub">针对诊断结果生成的个性化资源</p></div><span class="status ok">{{ resources.length }} 份</span></div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <button v-for="(r,i) in resources" :key="r.resource_id" class="resource-tab" :class="{ active: selectedIdx === i }" style="flex:1;min-width:180px" @click="selectedIdx = i">
            <strong>{{ r.title }}</strong><small>{{ r.resource_type }} · 难度 {{ r.difficulty }}</small>
          </button>
        </div>
      </div>

      <article v-if="selected" class="panel">
        <div class="trust">
          <span class="status" :class="selected.review_status === 'passed' ? 'ok' : 'wait'">{{ selected.review_status === 'passed' ? '✓ 已通过审核' : '待审核' }}</span>
          <span class="tag">难度 {{ selected.difficulty }}/5</span>
          <span class="tag">引用 {{ selected.sources.length }} 条</span>
          <span class="tag">资源 v{{ selected.version || 1 }}</span>
        </div>
        <div class="article">
          <h1 style="font-size:24px;margin-top:18px">{{ selected.title }}</h1>
          <p class="sub">资源类型：{{ selected.resource_type }} · 审核状态：{{ selected.review_status }} · 生成任务：{{ selected.generation_task_id || '-' }}</p>
          <h2>知识来源</h2>
          <div v-for="s in selected.source_details || []" :key="s.knowledge_id" class="source">
            <strong>{{ s.name }}</strong><span>{{ s.source_title }}</span>
          </div>
          <div v-if="selected.content" v-html="selected.content" style="margin-top:16px;line-height:1.8;font-size:13px;color:#3e4e63"></div>
        </div>
      </article>
    </template>

    <AppDialog ref="exportDialog" title="导出资源" :subtitle="selected?.title || ''">
      <label v-for="f in formats" :key="f.value" class="export-row">
        <input type="radio" name="fmt" :value="f.value" v-model="exportFormat" />
        <span><strong>{{ f.label }}</strong><small>{{ f.desc }}</small></span><span class="tag">{{ f.tag }}</span>
      </label>
      <template #footer>
        <button class="btn" @click="exportDialog?.close()">取消</button>
        <button class="btn primary" @click="doExport">导出资源</button>
      </template>
    </AppDialog>
  </section>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from '@/composables/useToast'
import { listResources, exportResource, type ResourceSummary } from '@/api/resources'
import { getActiveGenerationTask } from '@/api/generation'
import AppDialog from '@/components/Shared/AppDialog.vue'

const router = useRouter()
const { showToast } = useToast()
const loading = ref(false)
const resources = ref<ResourceSummary[]>([])
const selectedIdx = ref(0)
const exportFormat = ref('markdown')
const exportDialog = ref<InstanceType<typeof AppDialog> | null>(null)
const formats = [
  { value: 'markdown', label: 'Markdown', desc: '保留标题、表格、代码块和知识来源结构。', tag: '源格式' },
  { value: 'pdf', label: 'PDF', desc: '适合阅读、打印和提交。', tag: '推荐' },
]

const selected = computed(() => resources.value[selectedIdx.value] || null)

async function loadResources() {
  loading.value = true
  try {
    // Only load resources when there's an active/completed generation task
    const task = await getActiveGenerationTask('learner_001')
    if (task && task.resources?.length) {
      // Load full resource list to get details
      const all = await listResources()
      resources.value = all
    } else {
      resources.value = []
    }
  } catch {
    resources.value = []
  } finally {
    loading.value = false
  }
}

async function doExport() {
  if (!selected.value) return
  try {
    const r = await exportResource(selected.value.resource_id, exportFormat.value as 'markdown' | 'pdf')
    exportDialog.value?.close()
    showToast(`已导出：${r.file_name}`)
  } catch { showToast('导出失败') }
}

onMounted(loadResources)
</script>
