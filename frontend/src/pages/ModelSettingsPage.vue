<template>
  <section class="page model-settings-page">
    <PageHeader title="模型配置" description="配置模型网关与四类模型角色，检查真实演示条件以及对 Candidate RAG 的影响。">
      <template #status>
          <span
            class="overall-status"
            :class="status.ready_for_live_demo ? 'ready' : 'warning'"
            ><i />{{
              status.ready_for_live_demo ? "真实模型已就绪" : "需要完成配置"
            }}</span
          >
      </template>
      <template #actions>
        <button
          class="btn"
          :disabled="loading || testing || !canTest"
          @click="runTest"
        >
          {{ testing ? "正在测试..." : "测试连接" }}
        </button>
        <button
          class="btn primary"
          :disabled="loading || saving || !canSave"
          @click="requestSave"
        >
          {{ saving ? "正在保存..." : "保存配置" }}
        </button>
      </template>
    </PageHeader>

    <div
      v-if="loading && !loaded"
      class="settings-skeleton"
      aria-label="正在加载模型配置"
    >
      <i /><i /><i /><i />
    </div>
    <div v-else-if="errorMessage && !loaded" class="error-state" role="alert">
      <strong>模型配置加载失败</strong>
      <p>{{ errorMessage }}</p>
      <button class="btn" @click="load">重新加载</button>
    </div>

    <template v-else>
      <ReadinessList class="readiness-panel" aria-label="模型演示就绪度">
        <div v-for="item in readiness" :key="item.key" class="readiness-item">
          <span class="readiness-mark" :class="item.state">{{
            item.state === "ready" ? "✓" : "!"
          }}</span>
          <div>
            <strong>{{ item.label }}</strong
            ><small>{{ item.detail }}</small>
          </div>
          <StatusBadge
            :label="
              item.state === 'ready'
                ? '已就绪'
                : item.state === 'warning'
                  ? '需处理'
                  : '待配置'
            "
            :type="item.state === 'ready' ? 'ok' : 'wait'"
          />
        </div>
      </ReadinessList>

      <div v-if="errorMessage" class="inline-error" role="alert">
        <span>{{ errorMessage }}</span
        ><button class="btn text" @click="load">重新加载</button>
      </div>

      <InlineNotice v-if="isDirty" type="warning" class="unsaved-banner">
        <div>
          <strong>存在未保存的配置</strong>
          <p>当前运行服务仍使用上一次保存的设置。</p>
        </div>
        <button class="btn text" :disabled="saving" @click="resetForm">
          撤销修改
        </button>
      </InlineNotice>

      <div
        v-if="!index.ready || embeddingChanged"
        class="index-banner"
        :class="{ changed: embeddingChanged }"
      >
        <span class="index-icon">!</span>
        <div>
          <strong>{{
            embeddingChanged
              ? "Embedding 模型变更将使当前索引失效"
              : "Candidate RAG 需要处理"
          }}</strong>
          <p>
            {{
              embeddingChanged
                ? `保存后需使用 ${form.embedding_model || "新模型"} 重建 Candidate RAG 索引，保存操作本身不会自动重建。`
                : indexMessage
            }}
          </p>
        </div>
        <router-link
          class="btn"
          :to="{ path: '/domain-hub', query: { tab: 'operations' } }"
          >前往运行检查</router-link
        >
      </div>

      <div class="settings-grid">
        <section class="panel gateway-panel">
          <div class="section-head">
            <div>
              <h2>模型网关</h2>
              <p>所有生成、审核和 Embedding 请求共用此 OpenAI 兼容接入。</p>
            </div>
            <span class="security-badge">密钥加密存储</span>
          </div>
          <div class="settings-form">
            <label
              >API 地址<span class="field-help"
                >应包含服务要求的版本路径，例如 /v1</span
              ><input
                v-model="form.openai_api_base"
                class="field"
                autocomplete="url"
                placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1"
                @input="invalidateTest"
              /><small
                v-if="fieldError('openai_api_base')"
                class="field-error"
                >{{ fieldError("openai_api_base") }}</small
              ></label
            >
            <label
              >API Key<span class="field-help"
                >接口不会回显明文，留空表示继续使用已保存密钥</span
              >
              <div class="key-field">
                <input
                  v-model="form.openai_api_key"
                  class="field"
                  type="password"
                  autocomplete="new-password"
                  :disabled="clearApiKey"
                  :placeholder="
                    settings.openai_api_key_set
                      ? '密钥已保存，输入新值可替换'
                      : '请输入 API Key'
                  "
                  @input="invalidateTest"
                /><span
                  v-if="settings.openai_api_key_set && !clearApiKey"
                  class="key-state"
                  >已保存</span
                >
              </div>
              <small v-if="fieldError('openai_api_key')" class="field-error">{{
                fieldError("openai_api_key")
              }}</small></label
            >
          </div>
          <div class="credential-actions">
            <template v-if="settings.openai_api_key_set && !clearApiKey"
              ><p>保存新密钥会覆盖旧值，旧密钥无法从页面恢复。</p>
              <button
                class="btn danger-action clear-key-button"
                type="button"
                @click="clearDialog?.open()"
              >
                清除密钥
              </button></template
            ><template v-else-if="clearApiKey"
              ><p class="clear-pending">
                保存后将清除当前密钥，模型调用会立即变为不可用。
              </p>
              <button class="btn text" type="button" @click="cancelClearKey">
                取消清除
              </button></template
            >
            <p v-else>首次保存前需要填写可用的 API Key。</p>
          </div>
        </section>

        <section class="panel roles-panel">
          <div class="section-head">
            <div>
              <h2>模型角色</h2>
              <p>模型名称必须与当前网关实际提供的名称一致。</p>
            </div>
            <span class="role-count">4 个角色</span>
          </div>
          <div class="role-list">
            <label class="role-row"
              ><span class="role-icon generate">生</span
              ><span class="role-copy"
                ><strong>主生成模型</strong
                ><small>生成讲义、实操指南和分阶测试</small></span
              ><span class="role-input"
                ><input
                  v-model="form.primary_llm_model"
                  class="field"
                  placeholder="例如 qwen-plus"
                  @input="invalidateTest"
                /><small
                  v-if="fieldError('primary_llm_model')"
                  class="field-error"
                  >{{ fieldError("primary_llm_model") }}</small
                ></span
              ></label
            >
            <label class="role-row"
              ><span class="role-icon review">审</span
              ><span class="role-copy"
                ><strong>主审核模型</strong
                ><small>独立检查事实准确性与来源可追溯性</small></span
              ><span class="role-input"
                ><input
                  v-model="form.primary_review_model"
                  class="field"
                  placeholder="例如 qwen-max"
                /><small
                  v-if="fieldError('primary_review_model')"
                  class="field-error"
                  >{{ fieldError("primary_review_model") }}</small
                ></span
              ></label
            >
            <label class="role-row"
              ><span class="role-icon review secondary">复</span
              ><span class="role-copy"
                ><strong>副审核模型</strong
                ><small>与主审核模型交叉验证，必须使用不同模型</small></span
              ><span class="role-input"
                ><input
                  v-model="form.secondary_review_model"
                  class="field"
                  placeholder="例如 qwen-plus"
                /><small
                  v-if="fieldError('secondary_review_model')"
                  class="field-error"
                  >{{ fieldError("secondary_review_model") }}</small
                ></span
              ></label
            >
            <label class="role-row embedding-row"
              ><span class="role-icon embedding">向</span
              ><span class="role-copy"
                ><strong>Embedding 模型</strong
                ><small>构建 Candidate RAG 索引，修改后必须重建</small></span
              ><span class="role-input"
                ><input
                  v-model="form.embedding_model"
                  class="field"
                  placeholder="例如 text-embedding-v3"
                /><small
                  v-if="fieldError('embedding_model')"
                  class="field-error"
                  >{{ fieldError("embedding_model") }}</small
                ></span
              ></label
            >
          </div>
        </section>
      </div>

      <section v-if="testResult && !testResult.ok" class="panel test-panel">
        <div class="section-head">
          <div>
            <h2>连接测试失败</h2>
            <p>
              本次测试仅调用主生成模型，以下信息用于定位网关、密钥或模型名称问题。
            </p>
          </div>
        </div>
        <div class="test-result" :class="['failed', { stale: testStale }]">
          <span class="test-result-icon">!</span>
          <div>
            <div class="test-result-title">
              <strong>连接失败</strong><span v-if="testStale">结果已过期</span>
            </div>
            <p>{{ testResult.message }}</p>
            <small>测试对象：{{ testedModel || "主生成模型" }}</small>
            <p class="test-advice">排查建议：{{ testAdvice }}</p>
          </div>
        </div>
      </section>

      <details class="config-notes">
        <summary>配置来源与重启说明</summary>
        <div>
          <p>
            保存后配置写入数据库并立即应用于运行服务，重启后仍从数据库恢复；页面不会修改根目录
            <code>.env</code>。
          </p>
          <p>
            宿主机需要同步兜底配置时可执行
            <code>./scripts/sync-model-env.ps1</code>。超时、并发、Token
            上限和重试参数继续由环境配置管理。
          </p>
        </div>
      </details>
    </template>

    <AppDialog
      ref="clearDialog"
      title="清除已保存的 API Key"
      subtitle="保存配置后生效"
      ><div class="confirm-message danger-message">
        <span>!</span>
        <p>
          清除后，生成、审核和 Embedding
          调用都会停止工作，直到重新保存有效密钥。
        </p>
      </div>
      <template #footer
        ><button class="btn" @click="clearDialog?.close()">取消</button
        ><button class="btn danger-action" @click="confirmClearKey">
          标记为清除
        </button></template
      ></AppDialog
    >
    <AppDialog
      ref="embeddingDialog"
      title="保存并使当前索引失效"
      :subtitle="`${settings.embedding_model || '未配置'} → ${form.embedding_model || '未配置'}`"
      ><div class="confirm-message">
        <span>!</span>
        <p>
          模型配置会立即保存，但 Candidate RAG
          不会自动重建。完成重建前，新的资源生成任务将被阻止。
        </p>
      </div>
      <template #footer
        ><button
          class="btn"
          :disabled="saving"
          @click="embeddingDialog?.close()"
        >
          取消</button
        ><button class="btn primary" :disabled="saving" @click="performSave">
          {{ saving ? "正在保存..." : "保存配置" }}
        </button></template
      ></AppDialog
    >
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import AppDialog from "@/components/Shared/AppDialog.vue";
import StatusBadge from "@/components/Shared/StatusBadge.vue";
import PageHeader from "@/components/Shared/PageHeader.vue";
import ReadinessList from "@/components/Shared/ReadinessList.vue";
import InlineNotice from "@/components/Shared/InlineNotice.vue";
import {
  getModelSettings,
  testModelSettings,
  updateModelSettings,
  type IndexRebuildHint,
  type ModelConfigStatus,
  type ModelSettings,
  type ModelTestResult,
} from "@/api/modelSettings";
import { useToast } from "@/composables/useToast";
import {
  connectionTestHint,
  embeddingModelChanged,
  formFromSettings,
  indexReasonText,
  modelSettingsDirty,
  modelSettingsPayload,
  readinessItems,
  validateModelSettingsForm,
  type ModelSettingsForm,
} from "./modelSettingsState";

const { showToast } = useToast();
const loading = ref(false),
  loaded = ref(false),
  saving = ref(false),
  testing = ref(false),
  errorMessage = ref(""),
  showValidation = ref(false);
const testResult = ref<ModelTestResult | null>(null),
  testedFingerprint = ref(""),
  testedModel = ref("");
const clearApiKey = ref(false),
  clearDialog = ref<InstanceType<typeof AppDialog> | null>(null),
  embeddingDialog = ref<InstanceType<typeof AppDialog> | null>(null);
const settings = ref<ModelSettings>({
  openai_api_base: "",
  openai_api_key_set: false,
  primary_llm_model: "",
  primary_review_model: "",
  secondary_review_model: "",
  embedding_model: "",
});
const status = ref<ModelConfigStatus>({
  status: "degraded",
  ready_for_live_demo: false,
  fixture_enabled: false,
  review_models_distinct: false,
  model_gateway: { configured: false, base_url_configured: false },
  generation_model: { configured: false, model_name: null },
  primary_review_model: { configured: false, model_name: null },
  secondary_review_model: { configured: false, model_name: null },
});
const index = ref<IndexRebuildHint>({ ready: true, reason: null });
const form = reactive<ModelSettingsForm>(formFromSettings(settings.value));

const validation = computed(() =>
  validateModelSettingsForm(
    form,
    settings.value.openai_api_key_set,
    clearApiKey.value,
  ),
);
const isDirty = computed(() =>
  modelSettingsDirty(settings.value, form, clearApiKey.value),
);
const canSave = computed(
  () => loaded.value && isDirty.value && validation.value.valid,
);
const embeddingChanged = computed(() =>
  embeddingModelChanged(settings.value, form),
);
const readiness = computed(() => readinessItems(status.value, index.value));
const indexMessage = computed(() => indexReasonText(index.value.reason));
const testFingerprint = computed(() =>
  [
    form.openai_api_base.trim(),
    form.primary_llm_model.trim(),
    form.openai_api_key,
    clearApiKey.value,
  ].join("|"),
);
const testStale = computed(() =>
  Boolean(
    testResult.value && testedFingerprint.value !== testFingerprint.value,
  ),
);
const canTest = computed(() => {
  const baseError = validateModelSettingsForm(
    {
      ...form,
      primary_review_model: "a",
      secondary_review_model: "b",
      embedding_model: "embed",
    },
    settings.value.openai_api_key_set,
    clearApiKey.value,
  ).errors;
  return (
    !baseError.openai_api_base &&
    !baseError.primary_llm_model &&
    !baseError.openai_api_key &&
    !clearApiKey.value
  );
});
const testAdvice = computed(() => connectionTestHint(testResult.value?.code));

function applyLoadedSettings(data: {
  settings: ModelSettings;
  status: ModelConfigStatus;
  index: IndexRebuildHint;
}) {
  settings.value = data.settings;
  status.value = data.status;
  index.value = data.index;
  Object.assign(form, formFromSettings(data.settings));
  clearApiKey.value = false;
  showValidation.value = false;
}
async function load() {
  loading.value = true;
  errorMessage.value = "";
  try {
    applyLoadedSettings(await getModelSettings());
    loaded.value = true;
  } catch {
    errorMessage.value = "无法读取模型配置，请确认后端服务与数据库可用。";
  } finally {
    loading.value = false;
  }
}
function fieldError(field: keyof ModelSettingsForm) {
  return showValidation.value ? validation.value.errors[field] || "" : "";
}
function resetForm() {
  Object.assign(form, formFromSettings(settings.value));
  clearApiKey.value = false;
  showValidation.value = false;
  testResult.value = null;
  testedFingerprint.value = "";
}
function invalidateTest() {
  /* testStale 通过表单指纹自动计算 */
}
function confirmClearKey() {
  clearApiKey.value = true;
  form.openai_api_key = "";
  clearDialog.value?.close();
  invalidateTest();
}
function cancelClearKey() {
  clearApiKey.value = false;
  invalidateTest();
}
function requestSave() {
  showValidation.value = true;
  if (!validation.value.valid) {
    showToast("请先修正配置项");
    return;
  }
  if (!isDirty.value) return;
  if (embeddingChanged.value) embeddingDialog.value?.open();
  else performSave();
}
async function performSave() {
  saving.value = true;
  errorMessage.value = "";
  try {
    const data = await updateModelSettings(
      modelSettingsPayload(form, clearApiKey.value),
    );
    applyLoadedSettings(data);
    embeddingDialog.value?.close();
    testResult.value = null;
    testedFingerprint.value = "";
    showToast("模型配置已保存并生效", "success");
  } catch (error: any) {
    showToast(error?.response?.data?.detail || "保存失败，请稍后重试", "error");
  } finally {
    saving.value = false;
  }
}
async function runTest() {
  if (!canTest.value) {
    showValidation.value = true;
    showToast("请先补齐网关、密钥和主生成模型");
    return;
  }
  testing.value = true;
  testResult.value = null;
  const fingerprint = testFingerprint.value;
  const model = form.primary_llm_model.trim();
  try {
    testResult.value = await testModelSettings(
      modelSettingsPayload(form, false),
    );
    testedFingerprint.value = fingerprint;
    testedModel.value = model;
    showToast(
      testResult.value.ok ? "连接测试成功" : "连接测试失败",
      testResult.value.ok ? "success" : "error",
    );
  } catch (error: any) {
    testResult.value = {
      ok: false,
      message: error?.response?.data?.detail || "连接测试请求失败",
      code: "unknown",
    };
    testedFingerprint.value = fingerprint;
    testedModel.value = model;
    showToast("连接测试失败", "error");
  } finally {
    testing.value = false;
  }
}
onMounted(load);
</script>

<style scoped>
.model-settings-page {
  gap: 16px;
}
.title-line {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.overall-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border-radius: 999px;
  padding: 5px 9px;
  font-size: 11px;
  font-weight: 700;
}
.overall-status i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
}
.overall-status.ready {
  background: var(--green2);
  color: var(--green);
}
.overall-status.warning {
  background: var(--amber2);
  color: var(--amber);
}
.readiness-panel {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  border: 1px solid var(--line);
  border-radius: 12px;
  background: #fff;
}
.readiness-item {
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  padding: 14px;
  border-right: 1px solid var(--line);
}
.readiness-item:last-child {
  border-right: 0;
}
.readiness-item strong,
.readiness-item small {
  display: block;
}
.readiness-item small {
  margin-top: 4px;
  color: var(--muted);
  font-size: 10px;
  line-height: 1.4;
}
.readiness-mark {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--green2);
  color: var(--green);
  font-size: 11px;
  font-weight: 800;
}
.readiness-mark.warning {
  background: var(--amber2);
  color: var(--amber);
}
.readiness-mark.error {
  background: #fff0f0;
  color: var(--red);
}
.inline-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-radius: 8px;
  background: #fff0f0;
  color: var(--red);
  padding: 10px 12px;
  font-size: 12px;
}
.unsaved-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  border: 1px solid #cdd9ed;
  border-radius: 9px;
  background: #f4f7fd;
  padding: 10px 13px;
  color: #27457f;
}
.unsaved-banner p {
  margin: 3px 0 0;
  font-size: 11px;
}
.index-banner {
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr) auto;
  gap: 11px;
  align-items: center;
  border: 1px solid #f0d2ac;
  border-radius: 10px;
  background: var(--amber2);
  padding: 12px 14px;
  color: #784207;
}
.index-icon {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: #f8deb8;
  font-weight: 800;
}
.index-banner p {
  margin: 4px 0 0;
  font-size: 11px;
  line-height: 1.5;
}
.settings-grid {
  display: grid;
  grid-template-columns: minmax(300px, 0.8fr) minmax(520px, 1.35fr);
  gap: 16px;
}
.section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
}
.section-head p {
  margin: 5px 0 0;
  color: var(--muted);
  font-size: 11px;
  line-height: 1.55;
}
.security-badge,
.role-count {
  border-radius: 999px;
  background: var(--soft);
  color: var(--muted);
  padding: 5px 8px;
  font-size: 10px;
  font-weight: 700;
  white-space: nowrap;
}
.settings-form {
  display: grid;
  gap: 16px;
  margin-top: 18px;
}
.settings-form label {
  display: grid;
  gap: 6px;
  color: #405067;
  font-size: 12px;
  font-weight: 680;
}
.field-help {
  color: var(--muted);
  font-size: 10px;
  font-weight: 400;
  line-height: 1.45;
}
.key-field {
  position: relative;
}
.key-field input {
  width: 100%;
  padding-right: 70px;
}
.key-state {
  position: absolute;
  top: 50%;
  right: 9px;
  transform: translateY(-50%);
  border-radius: 999px;
  background: var(--green2);
  color: var(--green);
  padding: 4px 7px;
  font-size: 10px;
  font-weight: 700;
}
.field-error {
  display: block;
  color: var(--red);
  font-size: 10px;
  line-height: 1.45;
}
.credential-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-top: 18px;
  border-top: 1px solid var(--line);
  padding-top: 13px;
}
.credential-actions p {
  margin: 0;
  color: var(--muted);
  font-size: 10px;
  line-height: 1.5;
}
.credential-actions .clear-pending {
  color: var(--red);
}
.clear-key-button {
  flex: 0 0 auto;
  background: #fff;
}
.clear-key-button:hover {
  border-color: var(--red);
  background: #fff7f7;
}
.role-list {
  display: grid;
  margin-top: 12px;
}
.role-row {
  display: grid;
  grid-template-columns: 34px minmax(170px, 0.75fr) minmax(210px, 1fr);
  gap: 11px;
  align-items: center;
  padding: 13px 0;
  border-bottom: 1px solid #edf0f4;
}
.role-row:last-child {
  border-bottom: 0;
}
.role-icon {
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  background: var(--blue2);
  color: var(--blue);
  font-size: 11px;
  font-weight: 800;
}
.role-icon.review {
  background: #f0ecff;
  color: #6950b5;
}
.role-icon.secondary {
  background: #e8f5f3;
  color: #27776d;
}
.role-icon.embedding {
  background: var(--amber2);
  color: var(--amber);
}
.role-copy strong,
.role-copy small {
  display: block;
}
.role-copy small {
  margin-top: 4px;
  color: var(--muted);
  font-size: 10px;
  line-height: 1.45;
}
.role-input {
  display: block;
}
.role-input input {
  width: 100%;
}
.embedding-row {
  background: linear-gradient(90deg, transparent, #fffbf5);
}
.test-panel {
  padding-bottom: 16px;
}
.test-empty {
  display: flex;
  align-items: center;
  gap: 9px;
  margin-top: 14px;
  border-radius: 8px;
  background: var(--soft);
  padding: 13px;
  color: var(--muted);
  font-size: 11px;
}
.test-empty span {
  width: 24px;
  height: 24px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: #fff;
  color: var(--blue);
}
.test-empty p {
  margin: 0;
}
.test-result {
  display: grid;
  grid-template-columns: 32px 1fr;
  gap: 11px;
  margin-top: 14px;
  border-radius: 9px;
  padding: 13px;
}
.test-result.success {
  background: var(--green2);
  color: var(--green);
}
.test-result.failed {
  background: #fff0f0;
  color: var(--red);
}
.test-result.stale {
  filter: saturate(0.35);
  opacity: 0.72;
}
.test-result-icon {
  width: 31px;
  height: 31px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: rgb(255 255 255/0.7);
  font-weight: 800;
}
.test-result-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.test-result-title span {
  border-radius: 999px;
  background: rgb(255 255 255/0.7);
  padding: 3px 6px;
  font-size: 9px;
  font-weight: 700;
}
.test-result p {
  margin: 4px 0;
  font-size: 11px;
  line-height: 1.55;
}
.test-result small {
  opacity: 0.8;
  font-size: 9px;
}
.test-advice {
  border-top: 1px solid currentColor;
  padding-top: 7px;
  opacity: 0.9;
}
.config-notes {
  border: 1px solid var(--line);
  border-radius: 9px;
  background: #fff;
}
.config-notes summary {
  cursor: pointer;
  padding: 12px 14px;
  color: #405067;
  font-size: 11px;
  font-weight: 680;
}
.config-notes > div {
  border-top: 1px solid var(--line);
  padding: 11px 14px;
}
.config-notes p {
  margin: 0 0 6px;
  color: var(--muted);
  font-size: 10px;
  line-height: 1.6;
}
.config-notes p:last-child {
  margin-bottom: 0;
}
.config-notes code {
  color: #405067;
}
.confirm-message {
  display: grid;
  grid-template-columns: 32px 1fr;
  gap: 10px;
  align-items: start;
  padding: 12px 0;
}
.confirm-message > span {
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--amber2);
  color: var(--amber);
  font-weight: 800;
}
.danger-message > span {
  background: #fff0f0;
  color: var(--red);
}
.confirm-message p {
  margin: 4px 0;
  color: #405067;
  font-size: 12px;
  line-height: 1.65;
}
.settings-skeleton {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
.settings-skeleton i {
  height: 82px;
  border-radius: 10px;
  background: linear-gradient(90deg, #eef1f5 25%, #f7f9fb 50%, #eef1f5 75%);
  background-size: 200% 100%;
  animation: skeleton 1.2s linear infinite;
}
@keyframes skeleton {
  to {
    background-position: -200% 0;
  }
}
@media (max-width: 1100px) {
  .readiness-panel {
    grid-template-columns: 1fr 1fr;
  }
  .readiness-item:nth-child(2) {
    border-right: 0;
  }
  .readiness-item:nth-child(-n + 2) {
    border-bottom: 1px solid var(--line);
  }
  .settings-grid {
    grid-template-columns: 1fr;
  }
  .settings-skeleton {
    grid-template-columns: 1fr 1fr;
  }
}
@media (max-width: 700px) {
  .readiness-panel {
    grid-template-columns: 1fr;
  }
  .readiness-item {
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }
  .readiness-item:last-child {
    border-bottom: 0;
  }
  .index-banner {
    grid-template-columns: 30px 1fr;
  }
  .index-banner .btn {
    grid-column: 1/-1;
  }
  .role-row {
    grid-template-columns: 34px 1fr;
  }
  .role-input {
    grid-column: 1/-1;
  }
  .credential-actions {
    align-items: flex-start;
    flex-direction: column;
  }
  .section-head {
    align-items: flex-start;
    flex-direction: column;
  }
  .section-head > .btn {
    width: 100%;
  }
  .settings-skeleton {
    grid-template-columns: 1fr 1fr;
  }
}
@media (max-width: 480px) {
  .title-line {
    align-items: flex-start;
    flex-direction: column;
  }
  .readiness-item {
    grid-template-columns: 30px 1fr;
  }
  .readiness-item > .status {
    grid-column: 2;
    justify-self: start;
  }
  .unsaved-banner {
    align-items: flex-start;
    flex-direction: column;
  }
  .settings-skeleton {
    grid-template-columns: 1fr;
  }
}
@media (prefers-reduced-motion: reduce) {
  .settings-skeleton i {
    animation: none;
  }
}
</style>
