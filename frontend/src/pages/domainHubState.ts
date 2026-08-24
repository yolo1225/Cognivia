import type { DomainStats, DomainSummary } from "@/api/domains";
import type { KnowledgeItem } from "@/api/knowledge";
import { knowledgeNameLabel } from "@/components/KnowledgeGraph/knowledgeGraph";

export type IndexUiState = "running" | "ready" | "needs_rebuild" | "failed";

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
