import type {
  IndexRebuildHint,
  ModelConfigStatus,
  ModelSettings,
  ModelSettingsBody,
} from "@/api/modelSettings";

export type ModelSettingsForm = {
  openai_api_base: string;
  primary_llm_model: string;
  primary_review_model: string;
  secondary_review_model: string;
  embedding_model: string;
  openai_api_key: string;
};

export type ReadinessItem = {
  key: "gateway" | "generation" | "review" | "rag";
  label: string;
  state: "ready" | "warning" | "error";
  detail: string;
};

const trim = (value: string) => value.trim();

export function formFromSettings(settings: ModelSettings): ModelSettingsForm {
  return {
    openai_api_base: settings.openai_api_base,
    primary_llm_model: settings.primary_llm_model,
    primary_review_model: settings.primary_review_model,
    secondary_review_model: settings.secondary_review_model,
    embedding_model: settings.embedding_model,
    openai_api_key: "",
  };
}

export function validateModelSettingsForm(
  form: ModelSettingsForm,
  apiKeyAlreadySet: boolean,
  clearApiKey: boolean,
) {
  const errors: Partial<Record<keyof ModelSettingsForm, string>> = {};
  const base = trim(form.openai_api_base);
  if (!base) errors.openai_api_base = "请填写 OpenAI 兼容 API 地址。";
  else {
    try {
      const url = new URL(base);
      if (!["http:", "https:"].includes(url.protocol))
        errors.openai_api_base = "API 地址必须使用 http 或 https。";
    } catch {
      errors.openai_api_base = "请输入完整有效的 API 地址。";
    }
  }
  if (!trim(form.primary_llm_model))
    errors.primary_llm_model = "请填写主生成模型。";
  if (!trim(form.primary_review_model))
    errors.primary_review_model = "请填写主审核模型。";
  if (!trim(form.secondary_review_model))
    errors.secondary_review_model = "请填写副审核模型。";
  if (!trim(form.embedding_model))
    errors.embedding_model = "请填写 Embedding 模型。";
  if (
    trim(form.primary_review_model) &&
    trim(form.primary_review_model) === trim(form.secondary_review_model)
  ) {
    errors.secondary_review_model = "副审核模型必须与主审核模型不同。";
  }
  if (!apiKeyAlreadySet && !clearApiKey && !trim(form.openai_api_key)) {
    errors.openai_api_key = "首次配置必须填写 API Key。";
  }
  return { valid: Object.keys(errors).length === 0, errors };
}

export function modelSettingsDirty(
  settings: ModelSettings,
  form: ModelSettingsForm,
  clearApiKey: boolean,
) {
  return (
    clearApiKey ||
    Boolean(trim(form.openai_api_key)) ||
    [
      "openai_api_base",
      "primary_llm_model",
      "primary_review_model",
      "secondary_review_model",
      "embedding_model",
    ].some(
      (key) =>
        trim(form[key as keyof ModelSettingsForm]) !==
        trim(settings[key as keyof ModelSettings] as string),
    )
  );
}

export function embeddingModelChanged(
  settings: ModelSettings,
  form: ModelSettingsForm,
) {
  return trim(settings.embedding_model) !== trim(form.embedding_model);
}

export function modelSettingsPayload(
  form: ModelSettingsForm,
  clearApiKey: boolean,
): ModelSettingsBody {
  return {
    openai_api_base: trim(form.openai_api_base),
    primary_llm_model: trim(form.primary_llm_model),
    primary_review_model: trim(form.primary_review_model),
    secondary_review_model: trim(form.secondary_review_model),
    embedding_model: trim(form.embedding_model),
    openai_api_key: trim(form.openai_api_key) || null,
    clear_openai_api_key: clearApiKey,
  };
}

export function readinessItems(
  status: ModelConfigStatus,
  index: IndexRebuildHint,
): ReadinessItem[] {
  const reviewReady =
    status.primary_review_model.configured &&
    status.secondary_review_model.configured &&
    status.review_models_distinct;
  return [
    {
      key: "gateway",
      label: "模型网关",
      state:
        status.model_gateway.configured &&
        status.model_gateway.base_url_configured
          ? "ready"
          : "error",
      detail: status.model_gateway.configured
        ? "API 地址与密钥已配置"
        : "需要配置 API 地址和密钥",
    },
    {
      key: "generation",
      label: "主生成模型",
      state: status.generation_model.configured ? "ready" : "error",
      detail: status.generation_model.model_name || "尚未配置模型名称",
    },
    {
      key: "review",
      label: "双审核模型",
      state: reviewReady ? "ready" : "error",
      detail: reviewReady
        ? "主、副审核模型已区分"
        : status.review_models_distinct
          ? "审核模型配置不完整"
          : "主、副审核模型必须不同",
    },
    {
      key: "rag",
      label: "Candidate RAG",
      state: index.ready ? "ready" : "warning",
      detail: index.ready
        ? "活动索引可用于生成"
        : indexReasonText(index.reason),
    },
  ];
}

export function indexReasonText(reason: string | null) {
  const messages: Record<string, string> = {
    embedding_model_mismatch: "Embedding 模型与活动索引不一致",
    candidate_index_stale: "知识内容变化，活动索引已过期",
    "candidate manifest is missing": "尚未建立 Candidate RAG 索引",
    embedding_configuration_missing: "Embedding 配置不完整",
    knowledge_items_missing: "当前领域没有可索引知识点",
    question_bank_total_insufficient: "正式题库数量不足，索引本身无需重建",
    question_bank_question_invalid: "正式题库存在未通过认证的题目",
    question_bank_distribution_insufficient: "正式题库题型、难度或层级分布不足",
    question_bank_knowledge_coverage_insufficient: "正式题库未覆盖全部知识点",
    question_source_binding_invalid: "题库来源绑定已失效",
  };
  return messages[reason || ""] || "Candidate RAG 索引当前不可用";
}

export function connectionTestHint(code?: string) {
  const hints: Record<string, string> = {
    auth: "确认密钥完整、未过期，并具备调用该模型的权限。",
    not_found: "检查主生成模型名称，以及 API 地址是否包含正确的 /v1 路径。",
    rate_limit: "稍后重试，或检查账户额度和服务限流。",
    timeout: "检查网络、防火墙和服务响应时间。",
    connection:
      "容器内不能用 localhost 访问宿主机服务，请使用可从容器访问的地址。",
    bad_request: "确认主生成模型支持 OpenAI Chat Completions 格式。",
    server_error: "模型服务暂时不可用，请稍后重试。",
    http_error: "根据 HTTP 状态检查地址、密钥和模型名称。",
  };
  return (
    hints[code || ""] || "查看后端日志中的错误类型，普通日志不会记录密钥。"
  );
}
