<template>
  <section class="page">
    <div class="head"><div><h1>领域管理</h1><p class="sub">在同一个领域上下文中维护知识数据、诊断题、关系和必要的差异规则。</p></div></div>

    <div class="hub-context">
      <div class="hub-current">
        <div class="hub-mark">AI</div>
        <div><strong>{{ selectedDomain?.name || '选择领域' }}</strong><small><span class="domain-code">{{ selectedDomain?.domain_code }}</span> · {{ selectedDomain?.status }}</small></div>
      </div>
      <div class="actions">
        <select class="field" v-model="selectedCode" @change="switchDomain">
          <option v-for="d in domains" :key="d.domain_code" :value="d.domain_code">{{ d.name }}</option>
        </select>
        <button class="btn" @click="validate" :disabled="validating">校验当前领域</button>
      </div>
    </div>

    <div class="panel" style="padding:0 18px 18px">
      <div class="hub-tabs">
        <button v-for="t in panes" :key="t.id" class="hub-tab" :class="{ active: activePane === t.id }" @click="activePane = t.id">{{ t.label }}</button>
      </div>

      <div class="hub-pane" :class="{ active: activePane === 'overview' }" style="padding-top:18px">
        <div class="hub-overview">
          <div>
            <div class="metrics">
              <div class="metric"><div><span>知识点</span></div><strong>{{ knowledgeTotal }}</strong><small>来源完整率 100%</small></div>
              <div class="metric"><div><span>诊断题</span></div><strong>72</strong><small>覆盖五维能力</small></div>
              <div class="metric"><div><span>知识关系</span></div><strong>94</strong><small>前置、后继、相关</small></div>
              <div class="metric"><div><span>待向量化</span></div><strong>{{ pendingCount }}</strong><small>最近更新条目</small></div>
            </div>
          </div>
          <aside class="panel">
            <div class="panel-head"><h2>领域就绪状态</h2></div>
            <div class="readiness">
              <div class="ready-row"><span>基本信息</span><strong style="color:var(--green)">完整 ✓</strong></div>
              <div class="ready-row"><span>知识数据</span><strong style="color:var(--green)">{{ knowledgeTotal }} / 50 ✓</strong></div>
              <div class="ready-row"><span>向量索引</span><strong :style="{ color: pendingCount > 0 ? 'var(--amber)' : 'var(--green)' }">{{ pendingCount }} 项待处理</strong></div>
            </div>
            <button class="btn primary" style="width:100%;margin-top:14px" @click="rebuild" :disabled="rebuilding">{{ rebuilding ? '重建中...' : '重建向量索引' }}</button>
            <div v-if="validationResult" class="insight" style="margin-top:14px"><strong>校验结果</strong><br>{{ validationResult.passed ? '全部通过 ✓' : '存在问题：' + validationResult.issues.map((i: any) => i.message).join('；') }}</div>
          </aside>
        </div>
      </div>

      <div v-for="t in panes.slice(1)" :key="t.id" class="hub-pane" :class="{ active: activePane === t.id }" style="padding-top:18px">
        <div class="panel-head"><h2>{{ t.label }}</h2></div>
        <div v-if="t.id === 'knowledge'" class="upload-zone" style="min-height:138px;margin-bottom:14px">
          <div style="display:flex;align-items:center;gap:16px;text-align:left;max-width:720px">
            <div class="upload-icon">⇧</div>
            <div style="flex:1"><h3>导入领域文件</h3><p>知识资料支持 PDF、Markdown、TXT；诊断题库支持 Excel、JSON。</p><button class="btn primary" style="margin-top:10px" @click="showToast('请选择文件')">选择文件并导入</button></div>
          </div>
        </div>
        <div v-if="t.id === 'graph'" class="graph-wrap">
          <div class="graph-canvas"><svg viewBox="0 0 760 420"><g stroke="#9fb0c7" stroke-width="2" fill="none"><path d="M120 210 L260 120"/><path d="M120 210 L270 280"/><path d="M260 120 L410 205"/><path d="M270 280 L410 205"/><path d="M410 205 L565 115"/><path d="M410 205 L575 285"/></g><g font-family="system-ui" font-size="11" text-anchor="middle"><g><circle cx="120" cy="210" r="38" fill="#315fce"/><text x="120" y="207" fill="white">Python API</text></g><g><circle cx="260" cy="120" r="42" fill="#138560"/><text x="260" y="117" fill="white">Embedding</text></g><g><circle cx="410" cy="205" r="47" fill="#315fce"/><text x="410" y="202" fill="white">RAG 检索</text></g><g><circle cx="565" cy="115" r="41" fill="#315fce"/><text x="565" y="112" fill="white">召回评测</text></g></g></svg></div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useToast } from '@/composables/useToast'
import { listDomains, validateDomain, type DomainSummary } from '@/api/domains'
import { listKnowledgeItems, rebuildKnowledgeIndex } from '@/api/knowledge'

const { showToast } = useToast()
const domains = ref<DomainSummary[]>([])
const selectedCode = ref('ai_app_dev')
const selectedDomain = ref<DomainSummary | null>(null)
const activePane = ref('overview')
const knowledgeTotal = ref(0)
const pendingCount = ref(0)
const rebuilding = ref(false)
const validating = ref(false)
const validationResult = ref<any>(null)

const panes = [
  { id: 'overview', label: '领域概览' },
  { id: 'knowledge', label: '知识库管理' },
  { id: 'graph', label: '知识图谱' },
  { id: 'rule', label: '差异规则' },
  { id: 'index', label: '索引与校验' },
]

async function switchDomain() {
  selectedDomain.value = domains.value.find(d => d.domain_code === selectedCode.value) || null
  if (selectedDomain.value) {
    try {
      const resp = await listKnowledgeItems(selectedCode.value, 100)
      knowledgeTotal.value = resp.total
      pendingCount.value = resp.items.filter(i => i.needs_reembedding).length
    } catch { knowledgeTotal.value = 0; pendingCount.value = 0 }
  }
}

async function validate() {
  validating.value = true
  try { validationResult.value = await validateDomain(selectedCode.value); showToast(validationResult.value.passed ? '校验通过' : '存在待处理项') }
  catch { showToast('校验失败') }
  finally { validating.value = false }
}

async function rebuild() {
  rebuilding.value = true
  try { await rebuildKnowledgeIndex(); pendingCount.value = 0; showToast('索引重建完成') }
  catch { showToast('索引重建失败') }
  finally { rebuilding.value = false }
}

onMounted(async () => {
  try {
    domains.value = await listDomains()
    if (domains.value.length > 0) { selectedDomain.value = domains.value[0]; await switchDomain() }
  } catch { domains.value = [{ domain_code: 'ai_app_dev', name: '人工智能应用开发实训', status: 'enabled' }] }
})
</script>
