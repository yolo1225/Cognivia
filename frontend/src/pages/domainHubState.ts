import type { DomainStats, DomainSummary } from "@/api/domains";
import type { KnowledgeItem, QuestionBankItem } from "@/api/knowledge";
import type { KnowledgeDocumentItem } from "@/api/knowledgeDocuments";
import { knowledgeNameLabel } from "@/components/KnowledgeGraph/knowledgeGraph";

export type IndexUiState = "running" | "ready" | "needs_rebuild" | "failed";

export type DomainTaskActionId =
  | "loading"
  | "open_documents"
  | "rebuild_index"
  | "open_questions"
  | "open_validation"
  | "publish_domain"
  | "review_operations";

export type DomainTaskAction = {
  id: DomainTaskActionId;
  label: string;
  title: string;
  description: string;
  tone: "ready" | "warning" | "error" | "info";
};

export type DomainTaskInput = {
  stats: DomainStats | null;
  domainStatus?: string;
  indexState: IndexUiState;
  validationPassed?: boolean;
  missingQuestionKnowledgeCount?: number;
  indexBlockedByQuestionBank?: boolean;
};

export function indexUiState(
  ragReady: boolean | undefined,
  pendingEmbeddings: number,
  jobStatus?: string,
): IndexUiState {
  if (jobStatus === "running") return "running";
  if (jobStatus === "failed" || jobStatus === "interrupted") return "failed";
  if (ragReady === true && pendingEmbeddings === 0) return "ready";
  return "needs_rebuild";
}

export function getDomainTaskAction({
  stats,
  domainStatus,
  indexState,
  validationPassed,
  missingQuestionKnowledgeCount = 0,
  indexBlockedByQuestionBank = false,
}: DomainTaskInput): DomainTaskAction {
  if (!stats) {
    return {
      id: "loading",
      label: "正在加载",
      title: "正在读取领域运行状态",
      description: "完成加载后会显示当前需要处理的事项。",
      tone: "info",
    };
  }

  if (stats.failed_documents > 0) {
    return {
      id: "open_documents",
      label: "处理来源文档",
      title: "有来源文档处理失败",
      description: `当前有 ${stats.failed_documents} 份文档需要重新处理或移除。`,
      tone: "error",
    };
  }

  if (indexState === "running") {
    return {
      id: "review_operations",
      label: "查看运行状态",
      title: "检索索引正在更新",
      description: "索引完成后再执行领域校验，避免基于旧数据发布。",
      tone: "info",
    };
  }

  if (
    !indexBlockedByQuestionBank &&
    (indexState === "failed" || indexState === "needs_rebuild")
  ) {
    return {
      id: "rebuild_index",
      label: "重建检索索引",
      title: indexState === "failed" ? "检索索引更新失败" : "检索索引尚未同步",
      description:
        "知识来源或内容发生变化后，需要完成索引更新才能用于稳定检索。",
      tone: indexState === "failed" ? "error" : "warning",
    };
  }

  if (missingQuestionKnowledgeCount > 0) {
    return {
      id: "open_questions",
      label: "补齐题库覆盖",
      title: "正式题库覆盖不足",
      description: `仍有 ${missingQuestionKnowledgeCount} 个知识点缺少至少一种必需题目用途。`,
      tone: "warning",
    };
  }

  if (validationPassed === false) {
    return {
      id: "open_validation",
      label: "查看校验问题",
      title: "领域校验尚未通过",
      description: "查看未达标项并处理后，再重新执行运行检查。",
      tone: "warning",
    };
  }

  if (domainStatus !== "ready") {
    return {
      id: "publish_domain",
      label: "发布领域",
      title: "领域已具备发布条件",
      description: "发布后，学习者可以在建档与诊断中选择该领域。",
      tone: "ready",
    };
  }

  return {
    id: "review_operations",
    label: "查看运行检查",
    title: "领域运行正常",
    description: "知识资产、检索索引和发布校验均处于可用状态。",
    tone: "ready",
  };
}

export type KnowledgeFilters = {
  keyword: string;
  category: string;
  difficulty: "all" | string;
  indexStatus: "all" | "pending" | "ready";
};

export function filterKnowledgeItems(
  items: KnowledgeItem[],
  filters: KnowledgeFilters,
) {
  const keyword = filters.keyword.trim().toLocaleLowerCase("zh-CN");
  return items.filter((item) => {
    const text =
      `${knowledgeNameLabel(item)} ${item.category} ${item.source_title} ${item.tags.join(" ")}`.toLocaleLowerCase(
        "zh-CN",
      );
    return (
      (!keyword || text.includes(keyword)) &&
      (filters.category === "all" || item.category === filters.category) &&
      (filters.difficulty === "all" ||
        item.difficulty === Number(filters.difficulty)) &&
      (filters.indexStatus === "all" ||
        (filters.indexStatus === "pending"
          ? item.needs_reembedding
          : !item.needs_reembedding))
    );
  });
}

export type QuestionFilters = {
  keyword: string;
  purpose: "all" | QuestionBankItem["question_bank_uses"][number];
  level: "all" | QuestionBankItem["quiz_level"];
  difficulty: "all" | string;
  certification: "all" | QuestionBankItem["certification_status"];
  status: "all" | QuestionBankItem["status"];
};

export function filterQuestionBank(
  items: QuestionBankItem[],
  filters: QuestionFilters,
) {
  const keyword = filters.keyword.trim().toLocaleLowerCase("zh-CN");
  return items.filter((item) => {
    const text = `${item.knowledge_name} ${item.stem} ${item.source_ref_ids.join(" ")}`.toLocaleLowerCase(
      "zh-CN",
    );
    return (
      (!keyword || text.includes(keyword)) &&
      (filters.purpose === "all" ||
        item.question_bank_uses.includes(filters.purpose)) &&
      (filters.level === "all" || item.quiz_level === filters.level) &&
      (filters.difficulty === "all" ||
        item.difficulty === Number(filters.difficulty)) &&
      (filters.certification === "all" ||
        item.certification_status === filters.certification) &&
      (filters.status === "all" || item.status === filters.status)
    );
  });
}

export type DocumentFilters = {
  keyword: string;
  status: "all" | "attention" | "processing" | "ready";
  fileType: "all" | KnowledgeDocumentItem["file_type"];
};

export function documentStatusGroup(
  status: KnowledgeDocumentItem["status"],
): DocumentFilters["status"] {
  if (status === "ready") return "ready";
  if (
    [
      "needs_attention",
      "failed",
      "withdrawn",
      "cancel_requested",
      "cancelled",
    ].includes(status)
  )
    return "attention";
  return "processing";
}

export function filterAndSortDocuments(
  items: KnowledgeDocumentItem[],
  filters: DocumentFilters,
) {
  const keyword = filters.keyword.trim().toLocaleLowerCase("zh-CN");
  const priority: Record<Exclude<DocumentFilters["status"], "all">, number> = {
    attention: 0,
    processing: 1,
    ready: 2,
  };
  return items
    .filter((item) => {
      const text = `${item.original_name} ${item.source_title}`.toLocaleLowerCase(
        "zh-CN",
      );
      const group = documentStatusGroup(item.status);
      return (
        (!keyword || text.includes(keyword)) &&
        (filters.status === "all" || group === filters.status) &&
        (filters.fileType === "all" || item.file_type === filters.fileType)
      );
    })
    .sort((left, right) => {
      const groupOrder =
        priority[documentStatusGroup(left.status) as Exclude<DocumentFilters["status"], "all">] -
        priority[documentStatusGroup(right.status) as Exclude<DocumentFilters["status"], "all">];
      if (groupOrder !== 0) return groupOrder;
      return (
        new Date(right.created_at || 0).getTime() -
        new Date(left.created_at || 0).getTime()
      );
    });
}

export function domainReadiness(
  stats: DomainStats | null,
  ragReady: boolean | undefined,
  indexRunning = false,
  indexFailed = false,
) {
  if (!stats) return [];
  return [
    {
      key: "knowledge",
      label: "知识点规模",
      actual: stats.knowledge_items,
      target: 50,
      state: stats.knowledge_items >= 50 ? "ready" : "warning",
    },
    {
      key: "questions",
      label: "诊断题规模",
      actual: stats.diagnostic_questions,
      target: 60,
      state: stats.diagnostic_questions >= 60 ? "ready" : "warning",
    },
    {
      key: "index",
      label: "Candidate RAG 索引",
      actual: ragReady ? 1 : 0,
      target: 1,
      state: indexFailed
        ? "error"
        : indexRunning
          ? "running"
          : ragReady
            ? "ready"
            : "error",
    },
    {
      key: "documents",
      label: "来源文档处理",
      actual: stats.failed_documents,
      target: 0,
      state: stats.failed_documents === 0 ? "ready" : "error",
    },
  ] as const;
}

export function configList(domain: DomainSummary | null) {
  const config = domain?.config || {};
  const configuredAbilities = Array.isArray(config.ability_dimensions)
    ? config.ability_dimensions.map(String)
    : [];
  const configuredResources = Array.isArray(config.resource_types)
    ? config.resource_types.map(String)
    : [];
  const configuredTargets =
    config.readiness_policy && typeof config.readiness_policy === "object"
      ? (config.readiness_policy as Record<string, unknown>)
      : config.mvp_targets && typeof config.mvp_targets === "object"
        ? (config.mvp_targets as Record<string, unknown>)
        : {};
  const primary = domain?.domain_code === "ai_app_dev";
  const targets = {
    minimum_published_knowledge:
      configuredTargets.minimum_published_knowledge ??
      configuredTargets.knowledge_items ??
      (primary ? 50 : 10),
    minimum_diagnostic_questions:
      configuredTargets.minimum_diagnostic_questions ??
      configuredTargets.diagnostic_questions ??
      (primary ? 60 : 10),
  };
  return {
    abilityDimensions: configuredAbilities.length
      ? configuredAbilities
      : ["理论基础", "实操能力", "问题解决", "知识广度", "学习速度"],
    resourceTypes: configuredResources.length
      ? configuredResources
      : ["lecture", "practice_guide", "graded_quiz"],
    mvpTargets: Object.entries(targets),
    learningDirections: domain?.learning_directions || [],
    sources: {
      abilityDimensions: configuredAbilities.length ? "领域配置" : "系统默认",
      resourceTypes: configuredResources.length ? "领域配置" : "系统默认",
      mvpTargets: Object.keys(configuredTargets).length ? "领域配置" : "系统默认",
      learningDirections: domain?.learning_directions?.length
        ? "文档自动生成 / 人工调整"
        : "等待文档导入",
    },
  };
}
