import { describe, expect, it } from "vitest";
import type { DomainStats, DomainSummary } from "@/api/domains";
import type { KnowledgeItem } from "@/api/knowledge";
import {
  configList,
  domainReadiness,
  filterKnowledgeItems,
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
      mvpTargets: [["knowledge_items", 50]],
    });
  });

  it("returns empty groups for missing config", () => {
    expect(configList(null)).toEqual({
      abilityDimensions: [],
      resourceTypes: [],
      mvpTargets: [],
    });
  });
});
