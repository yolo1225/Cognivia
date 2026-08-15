<template>
  <section class="page">
    <div class="head"><div><h1>领域管理与配置</h1></div></div>

    <div class="domain-workspace">
      <aside class="panel">
        <div class="panel-head"><div><h2>领域列表</h2><p class="sub">{{ domains.length }} 个领域</p></div><button class="btn" @click="loadDomains">刷新</button></div>
        <div class="domain-list">
          <button v-for="d in domains" :key="d.domain_code" class="domain-item" :class="{ active: selected?.domain_code === d.domain_code }" @click="selectDomain(d)">
            <strong>{{ d.name }}</strong>
            <span class="status" :class="d.status === 'enabled' ? 'ok' : 'wait'">{{ d.status === 'enabled' ? '已启用' : d.status }}</span>
            <small><span class="domain-code">{{ d.domain_code }}</span></small>
          </button>
        </div>
      </aside>

      <div v-if="selected" class="panel">
        <div class="domain-detail-head">
          <div><h2>{{ selected.name }}</h2>
            <div class="domain-meta"><span class="tag">{{ selected.domain_code }}</span><span class="status" :class="selected.status === 'enabled' ? 'ok' : ''">{{ selected.status }}</span></div>
          </div>
          <div class="actions"><button class="btn" @click="validateDomainFn">校验配置</button></div>
        </div>
        <div class="config-list">
          <div class="config-row"><div><h3>领域基本信息</h3></div><div><strong>{{ selected.name }}</strong><p>代码：{{ selected.domain_code }} · 状态：{{ selected.status }}</p></div></div>
          <div class="config-row"><div><h3>能力模型</h3></div><div class="chips"><span class="tag">理论基础</span><span class="tag">实操能力</span><span class="tag">问题解决</span><span class="tag">知识广度</span><span class="tag">学习速度</span></div></div>
          <div class="config-row"><div><h3>审核规则</h3></div><div><strong>事实、来源、难度、核心覆盖</strong><p>分差 &gt; 10 或结论冲突时触发仲裁</p></div></div>
        </div>
        <div v-if="validation" class="insight" style="margin-top:14px"><strong>校验结果</strong><br>{{ validation.passed ? '全部通过 ✓' : '存在问题：' + validation.issues.map((i:any)=>i.message).join('；') }}</div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useToast } from '@/composables/useToast'
import { listDomains, validateDomain, type DomainSummary } from '@/api/domains'

const { showToast } = useToast()
const domains = ref<DomainSummary[]>([])
const selected = ref<DomainSummary | null>(null)
const validation = ref<any>(null)

async function loadDomains() {
  try { domains.value = await listDomains(); if (!selected.value && domains.value.length) selected.value = domains.value[0] }
  catch { showToast('加载领域列表失败') }
}
async function selectDomain(d: DomainSummary) { selected.value = d; validation.value = null }
async function validateDomainFn() {
  if (!selected.value) return
  try { validation.value = await validateDomain(selected.value.domain_code); showToast(validation.value.passed ? '校验通过' : '存在问题') }
  catch { showToast('校验失败') }
}

onMounted(loadDomains)
</script>
