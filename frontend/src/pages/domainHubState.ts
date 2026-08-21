import type { DomainStats, DomainSummary } from "@/api/domains";
import type { KnowledgeItem } from "@/api/knowledge";

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
      `${item.name} ${item.category} ${item.source_title} ${item.tags.join(" ")}`.toLocaleLowerCase(
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
  return {
    abilityDimensions: Array.isArray(config.ability_dimensions)
      ? config.ability_dimensions.map(String)
      : [],
    resourceTypes: Array.isArray(config.resource_types)
      ? config.resource_types.map(String)
      : [],
    mvpTargets:
      config.mvp_targets && typeof config.mvp_targets === "object"
        ? Object.entries(config.mvp_targets as Record<string, unknown>)
        : [],
  };
}
