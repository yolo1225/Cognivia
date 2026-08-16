<template>
  <section class="page">
    <div class="head">
      <div>
        <h1>模型配置</h1>
        <p class="sub">可视化配置模型接入信息，保存后写入数据库并立即生效。</p>
      </div>
      <div class="actions">
        <button class="btn" :disabled="testing" @click="runTest">{{ testing ? '正在测试...' : '测试连接' }}</button>
        <button class="btn primary" :disabled="saving" @click="save">{{ saving ? '正在保存...' : '保存配置' }}</button>
      </div>
    </div>

    <div v-if="errorMessage" class="error-state">
      <strong>模型配置加载失败</strong><p>{{ errorMessage }}</p><button class="btn" @click="load">重新加载</button>
    </div>

    <template v-else>
      <div class="metrics">
        <div class="metric"><div><span>就绪状态</span><span class="status" :class="status.ready_for_live_demo ? 'ok' : 'wait'">{{ status.ready_for_live_demo ? '可演示' : '未就绪' }}</span></div><strong>{{ status.ready_for_live_demo ? '就绪' : '待配置' }}</strong><small>{{ status.ready_for_live_demo ? '真实模型演示可用' : '请补齐网关与双审核模型' }}</small></div>
        <div class="metric"><div><span>模型网关</span></div><strong>{{ status.model_gateway.configured ? '已配置' : '未配置' }}</strong><small>{{ form.openai_api_base || '未填写 API 地址' }}</small></div>
        <div class="metric"><div><span>生成模型</span></div><strong>{{ status.generation_model.model_name || '-' }}</strong><small>{{ status.generation_model.configured ? '已配置' : '未配置' }}</small></div>
        <div class="metric"><div><span>双审核模型</span></div><strong>{{ status.review_models_distinct ? '已区分' : '未就绪' }}</strong><small>主 / 副审核模型必须不同</small></div>
      </div>

      <div v-if="ragHint" class="rag-banner">
        <span>⚠ {{ ragHint }}</span>
        <router-link class="btn small" :to="{ path: '/domain-hub', query: { tab: 'index' } }">去重建索引</router-link>
      </div>

      <div class="panel">
        <div class="panel-head">
          <h2>模型接入</h2>
          <span class="tag">密钥加密存储</span>
        </div>
        <div class="form-grid">
          <label class="wide">API 地址（OpenAI 兼容）
            <input v-model="form.openai_api_base" class="field" placeholder="例如 https://dashscope.aliyuncs.com/compatible-mode/v1" />
          </label>
          <label class="wide">API Key
            <input v-model="form.openai_api_key" class="field" type="password" autocomplete="off" :placeholder="settings.openai_api_key_set ? '已配置，留空保持不变' : '未配置，请输入密钥'" />
            <small class="hint">密钥仅用于校验连接；数据库中以加密形式保存，接口不回显明文。</small>
          </label>
          <label v-if="settings.openai_api_key_set" class="wide">
            <span class="check-row"><input v-model="form.clear_openai_api_key" type="checkbox" /> 清除已保存的密钥</span>
          </label>
        </div>
      </div>

      <div class="panel">
        <div class="panel-head"><h2>模型与 Embedding</h2><span class="tag">最常用项</span></div>
        <div class="form-grid">
          <label>主生成模型
            <input v-model="form.primary_llm_model" class="field" placeholder="例如 qwen-plus" />
          </label>
          <label>Embedding 模型
            <input v-model="form.embedding_model" class="field" placeholder="例如 text-embedding-v3" />
          </label>
          <label>主审核模型
            <input v-model="form.primary_review_model" class="field" placeholder="例如 qwen-max" />
          </label>
          <label>副审核模型
            <input v-model="form.secondary_review_model" class="field" placeholder="与主审核模型不同" />
          </label>
        </div>
        <p v-if="status.review_models_distinct === false && form.primary_review_model && form.secondary_review_model && form.primary_review_model === form.secondary_review_model" class="warn-note">主审核模型与副审核模型相同，双模型交叉校验将失效。</p>
      </div>

      <div v-if="testResult" class="panel test-fail">
        <div class="panel-head"><h2>连接测试结果</h2><span class="status wait">失败</span></div>
        <p class="test-message">{{ testResult.message }}</p>
        <p v-if="testHint" class="test-hint">排查建议：{{ testHint }}</p>
      </div>

      <div class="insight">保存后写入数据库并立即生效，重启后也从数据库恢复；运行中的服务不直接改写 <strong>.env</strong>。若首次启动时因未配置模型跳过了向量化，保存后请在宿主机执行 <strong>./scripts/demo.ps1 rebuild-index</strong> 重建候选索引；如需把配置同步回根目录 .env（作为重置兜底），执行 <strong>./scripts/sync-model-env.ps1</strong>。仅保留最常用的接入项，其余超时、并发等高级参数仍由 .env 控制。</div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  getModelSettings,
  testModelSettings,
  updateModelSettings,
  type IndexRebuildHint,
  type ModelConfigStatus,
  type ModelSettings,
  type ModelTestResult,
} from '@/api/modelSettings'
import { useToast } from '@/composables/useToast'

const { showToast } = useToast()
const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const errorMessage = ref('')
const testResult = ref<ModelTestResult | null>(null)
const settings = ref<ModelSettings>({
  openai_api_base: '',
  openai_api_key_set: false,
  primary_llm_model: '',
  primary_review_model: '',
  secondary_review_model: '',
  embedding_model: '',
})
const status = ref<ModelConfigStatus>({
  status: 'degraded',
  ready_for_live_demo: false,
  fixture_enabled: false,
  review_models_distinct: false,
  model_gateway: { configured: false, base_url_configured: false },
  generation_model: { configured: false, model_name: null },
  primary_review_model: { configured: false, model_name: null },
  secondary_review_model: { configured: false, model_name: null },
})
const index = ref<IndexRebuildHint>({ ready: true, reason: null })
const form = reactive({
  openai_api_base: '',
  primary_llm_model: '',
  primary_review_model: '',
  secondary_review_model: '',
  embedding_model: '',
  openai_api_key: '',
  clear_openai_api_key: false,
})

const testHint = computed(() => {
  const code = testResult.value?.code
  if (!code || testResult.value?.ok) return ''
  const hints: Record<string, string> = {
    auth: '确认密钥完整且未过期；部分平台需要「基础密钥 + 模型密钥」两层都正确。',
    not_found: '检查模型名拼写，以及地址是否以 /v1 结尾。',
    rate_limit: '稍后重试，或检查账户额度与限流配置。',
    timeout: '检查网络与防火墙，必要时稍后重试。',
    connection: '容器内访问宿主机不能用 localhost，需使用宿主机内网/局域网 IP；确认地址可达。',
    bad_request: '确认模型名与 API 格式被该服务支持。',
    server_error: '服务端暂时不可用，稍后再试。',
    http_error: '对照返回的 HTTP 状态码排查地址、密钥与模型名。',
    unknown: '请查看后端日志获取更多信息（日志不记录密钥）。',
  }
  return hints[code] || hints.unknown || ''
})

const ragHint = computed(() => {
  if (index.value.ready) return ''
  const reason = index.value.reason || ''
  if (reason === 'embedding_model_mismatch') return 'Embedding 模型已变更，向量索引需要重建。'
  if (reason === 'candidate_index_stale') return '知识库内容已变化，向量索引需要重建。'
  if (reason === 'candidate manifest is missing') return '尚未建立向量索引，请先重建。'
  if (reason === 'embedding_configuration_missing') return '模型配置缺失，无法建立向量索引。'
  if (reason === 'knowledge_items_missing') return '尚无知识点，无法建立向量索引。'
  return '向量索引未就绪，建议重建索引。'
})

async function load() {
  loading.value = true
  errorMessage.value = ''
  try {
    const data = await getModelSettings()
    settings.value = data.settings
    status.value = data.status
    index.value = data.index
    form.openai_api_base = data.settings.openai_api_base
    form.primary_llm_model = data.settings.primary_llm_model
    form.primary_review_model = data.settings.primary_review_model
    form.secondary_review_model = data.settings.secondary_review_model
    form.embedding_model = data.settings.embedding_model
    form.openai_api_key = ''
    form.clear_openai_api_key = false
  } catch {
    errorMessage.value = '无法读取模型配置，请确认后端服务与数据库可用。'
  } finally {
    loading.value = false
  }
}

function payload() {
  return {
    openai_api_base: form.openai_api_base.trim(),
    primary_llm_model: form.primary_llm_model.trim(),
    primary_review_model: form.primary_review_model.trim(),
    secondary_review_model: form.secondary_review_model.trim(),
    embedding_model: form.embedding_model.trim(),
    openai_api_key: form.openai_api_key || null,
    clear_openai_api_key: form.clear_openai_api_key,
  }
}

async function runTest() {
  testing.value = true
  testResult.value = null
  try {
    const result = await testModelSettings(payload())
    if (result.ok) {
      showToast(result.message || '连接成功', 'success')
    } else {
      testResult.value = result
      showToast('连接失败', 'error')
    }
  } catch (error: any) {
    testResult.value = { ok: false, message: error?.response?.data?.detail || '连接测试请求失败' }
    showToast('连接失败', 'error')
  } finally {
    testing.value = false
  }
}

async function save() {
  saving.value = true
  testResult.value = null
  try {
    const data = await updateModelSettings(payload())
    settings.value = data.settings
    status.value = data.status
    index.value = data.index
    form.openai_api_key = ''
    form.clear_openai_api_key = false
    showToast('模型配置已保存并生效', 'success')
  } catch (error: any) {
    showToast(error?.response?.data?.detail || '保存失败，请稍后重试', 'error')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.hint {
  color: var(--muted);
  font-size: 11px;
  line-height: 1.5;
}
.check-row {
  display: flex;
  align-items: center;
  gap: 7px;
  color: #405067;
  font-size: 12px;
}
.warn-note {
  margin-top: 12px;
  border-radius: 8px;
  background: var(--amber2);
  color: var(--amber);
  padding: 9px 11px;
  font-size: 12px;
}
.test-message {
  color: #405067;
  font-size: 13px;
  line-height: 1.7;
}
.test-sample {
  margin-top: 7px;
  color: var(--muted);
  font-size: 12px;
}
.test-hint {
  margin-top: 10px;
  border-left: 3px solid var(--amber);
  background: var(--amber2);
  border-radius: 6px;
  padding: 9px 11px;
  color: #784207;
  font-size: 12px;
  line-height: 1.6;
}
.test-fail {
  border-color: #edc9c9;
  background: #fffafa;
}
.rag-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  border: 1px solid #f0d2ac;
  border-radius: 10px;
  background: var(--amber2);
  color: #784207;
  padding: 12px 14px;
  font-size: 13px;
  line-height: 1.6;
}
.rag-banner .btn {
  flex: 0 0 auto;
}
</style>
