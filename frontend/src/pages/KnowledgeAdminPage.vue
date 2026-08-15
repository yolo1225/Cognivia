<template>
  <section class="page">
    <div class="head"><div><h1>知识库管理</h1></div>
      <div class="actions">
        <button class="btn" @click="showImport = !showImport">{{ showImport ? '取消' : '新增知识点' }}</button>
        <button class="btn primary" @click="loadItems" :disabled="loading">刷新列表</button>
      </div>
    </div>

    <div class="metrics">
      <div class="metric"><div><span>知识点总数</span></div><strong>{{ items.length }}</strong><small>目标 ≥ 50</small></div>
      <div class="metric"><div><span>知识关系</span></div><strong>94</strong><small>前置、后继、相关</small></div>
      <div class="metric"><div><span>待向量化</span></div><strong>{{ pendingCount }}</strong><small>最近更新的知识点</small></div>
      <div class="metric"><div><span>受影响路径</span></div><strong>2</strong><small>打开报告时局部刷新</small></div>
    </div>

    <div v-if="showImport" class="panel" style="margin-bottom:14px">
      <div class="panel-head"><h2>新增知识点</h2></div>
      <div class="form-grid">
        <label>名称<input class="field" v-model="form.name" /></label>
        <label>分类<input class="field" v-model="form.category" /></label>
        <label>难度 (1-5)<input class="field" type="number" min="1" max="5" v-model.number="form.difficulty" /></label>
        <label>来源<input class="field" v-model="form.source_title" /></label>
        <label class="wide">内容<textarea v-model="form.content" style="margin-top:0"></textarea></label>
      </div>
      <div class="actions" style="margin-top:12px"><button class="btn primary" @click="createItem" :disabled="creating">{{ creating ? '保存中...' : '保存知识点' }}</button></div>
    </div>

    <div class="admin-grid">
      <div class="panel">
        <div class="panel-head"><div><h2>知识点列表</h2></div><div class="filterbar"><input class="field" v-model="searchQuery" placeholder="搜索知识点" @keyup.enter="search" /><button class="btn" @click="search">搜索</button></div></div>
        <table><thead><tr><th>知识点</th><th>分类</th><th>难度</th><th>来源</th><th>向量状态</th></tr></thead>
          <tbody>
            <tr v-if="loading"><td colspan="5" style="text-align:center;color:var(--muted)">加载中...</td></tr>
            <tr v-else-if="items.length === 0"><td colspan="5" style="text-align:center;color:var(--muted)" @click="loadItems">点击加载</td></tr>
            <tr v-for="item in items" :key="item.knowledge_id">
              <td><strong>{{ item.name }}</strong><br><small style="color:var(--muted)">{{ item.knowledge_id }}</small></td>
              <td>{{ item.category }}</td><td>{{ item.difficulty }}/5</td><td>{{ item.source_title }}</td>
              <td><span class="status" :class="item.needs_reembedding ? 'wait' : 'ok'">{{ item.needs_reembedding ? '待向量化' : '已就绪' }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>
      <aside class="panel">
        <div class="panel-head"><h2>索引与影响</h2><span class="status" :class="pendingCount > 0 ? 'wait' : 'ok'">{{ pendingCount }} 项待处理</span></div>
        <div class="index-summary"><div><span>待重建</span><strong>{{ pendingCount }}</strong></div><div><span>路径影响</span><strong>2</strong></div><div><span>资源待复核</span><strong>1</strong></div></div>
        <button class="btn primary" style="width:100%;margin-top:12px" @click="rebuild" :disabled="rebuilding">{{ rebuilding ? '重建中...' : '重建待处理索引' }}</button>
        <div v-if="searchMatches.length" style="margin-top:16px">
          <h3>搜索结果</h3>
          <div v-for="m in searchMatches" :key="m.knowledge_id" class="source"><strong>{{ m.name }}</strong><span>{{ m.source_title }} · 相似度 {{ m.similarity?.toFixed(3) }}</span></div>
        </div>
      </aside>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useToast } from '@/composables/useToast'
import { listKnowledgeItems, searchKnowledge, createKnowledgeItem, rebuildKnowledgeIndex, type KnowledgeItem } from '@/api/knowledge'

const { showToast } = useToast()
const items = ref<KnowledgeItem[]>([])
const loading = ref(false)
const creating = ref(false)
const rebuilding = ref(false)
const showImport = ref(false)
const searchQuery = ref('RAG 文档切片')
const searchMatches = ref<any[]>([])
const pendingCount = ref(0)
const form = ref({ name: '', category: 'RAG', difficulty: 3, source_title: '', content: '' })

async function loadItems() {
  loading.value = true
  try {
    const resp = await listKnowledgeItems('ai_app_dev', 100)
    items.value = resp.items
    pendingCount.value = resp.items.filter(i => i.needs_reembedding).length
  } catch { showToast('加载知识点失败') }
  finally { loading.value = false }
}

async function search() {
  if (!searchQuery.value) return
  try {
    const resp = await searchKnowledge(searchQuery.value, 'ai_app_dev', 5)
    searchMatches.value = resp.matches
  } catch { showToast('搜索失败') }
}

async function createItem() {
  creating.value = true
  try {
    await createKnowledgeItem({ ...form.value, domain_code: 'ai_app_dev', tags: [], source_url: null, license_note: 'imported' })
    showImport.value = false
    showToast('知识点已保存，待重建索引')
    await loadItems()
  } catch { showToast('保存失败') }
  finally { creating.value = false }
}

async function rebuild() {
  rebuilding.value = true
  try { await rebuildKnowledgeIndex(); pendingCount.value = 0; showToast('索引重建完成'); await loadItems() }
  catch { showToast('索引重建失败') }
  finally { rebuilding.value = false }
}

onMounted(loadItems)
</script>
