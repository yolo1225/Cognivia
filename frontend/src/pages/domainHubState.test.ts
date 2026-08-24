import { describe, expect, it } from "vitest";
import type { DomainStats, DomainSummary } from "@/api/domains";
import type { KnowledgeItem } from "@/api/knowledge";
import {
  configList,
  domainReadiness,
  filterKnowledgeItems,
  indexUiState,
} from "./domainHubState";

const items: KnowledgeItem[] = [
  {
    knowledge_id: "1",
    domain_code: "ai_app_dev",
    name: "RAG 检索",
    category: "RAG",
    difficulty: 3,
    tags: ["向量"],
    content: "内容",
    source_title: "课程资料",
    source_url: null,
    license_note: "授权",
    needs_reembedding: true,
  },
  {
    knowledge_id: "2",
    domain_code: "ai_app_dev",
    name: "Prompt 基础",
    category: "Prompt",
    difficulty: 1,
    tags: ["提示词"],
    content: "内容",
    source_title: "教材",
    source_url: null,
    license_note: "授权",
    needs_reembedding: false,
  },
];

const prefixedItem: KnowledgeItem = {
  ...items[0],
  knowledge_id: "3",
  name: "AI 机器学习基础知识库 (ai_ml_basics) / 77. Bahdanau 注意力机制",
};

it("combines knowledge filters", () => {
  expect(
    filterKnowledgeItems(items, {
      keyword: "向量",
      category: "RAG",
      difficulty: "3",
      indexStatus: "pending",
    }).map((item) => item.knowledge_id),
  ).toEqual(["1"]);
});

it("filters by the normalized knowledge name instead of a source-library prefix", () => {
  const filters = {
    category: "all",
    difficulty: "all",
    indexStatus: "all",
  } as const;
  expect(filterKnowledgeItems([prefixedItem], { ...filters, keyword: "Bahdanau" })).toHaveLength(1);
  expect(filterKnowledgeItems([prefixedItem], { ...filters, keyword: "ai_ml_basics" })).toHaveLength(0);
});

it("derives readiness from real targets and failures", () => {
  const stats = {
    knowledge_items: 50,
    diagnostic_questions: 59,
    pending_embeddings: 2,
    failed_documents: 1,
  } as DomainStats;
  expect(domainReadiness(stats, false).map((item) => item.state)).toEqual([
    "ready",
    "warning",
    "error",
    "error",
  ]);
});

it("does not report a ready index from pending embeddings alone", () => {
  expect(indexUiState(false, 0, "success")).toBe("needs_rebuild");
  expect(indexUiState(true, 0, "success")).toBe("ready");
  expect(indexUiState(true, 2, "success")).toBe("needs_rebuild");
  expect(indexUiState(undefined, 0, "running")).toBe("running");
});

describe("domain config parsing", () => {
  it("reads existing config values", () => {
    const domain = {
      config: {
        ability_dimensions: ["理论"],
        resource_types: ["lecture"],
        mvp_targets: { knowledge_items: 50 },
      },
    } as unknown as DomainSummary;
    expect(configList(domain)).toEqual({
      abilityDimensions: ["理论"],
      resourceTypes: ["lecture"],
      mvpTargets: [
        ["minimum_published_knowledge", 50],
        ["minimum_diagnostic_questions", 10],
      ],
      learningDirections: [],
      sources: {
        abilityDimensions: "领域配置",
        resourceTypes: "领域配置",
        mvpTargets: "领域配置",
        learningDirections: "等待文档导入",
      },
    });
  });

  it("returns empty groups for missing config", () => {
    const config = configList(null);
    expect(config.abilityDimensions).toHaveLength(5);
    expect(config.resourceTypes).toEqual(["lecture", "practice_guide", "graded_quiz"]);
    expect(config.mvpTargets).toEqual([
      ["minimum_published_knowledge", 10],
      ["minimum_diagnostic_questions", 10],
    ]);
    expect(config.sources.abilityDimensions).toBe("系统默认");
  });
});
